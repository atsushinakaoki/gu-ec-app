"""注文確定。設計仕様書 4.4 に対応する。

--- 全体の流れ ---

  0. 冪等キーの確認（同じキーの注文があれば、最初の結果を返す）
  1. 注文内容の組み立てと、金額の照合（Frontend の値を信用しない）
  2. トランザクション①：在庫の確定と注文の作成（PENDING_PAYMENT）
  3. 決済（DB のトランザクションの外。外部サービスは巻き戻せない）
  4a. 成功 → トランザクション②：注文を CONFIRMED に、カートを空に
  4b. 否決 → 補償処理：在庫を戻し、引当を解放し、注文を FAILED に
  4c. 応答なし → PENDING_PAYMENT のまま。在庫も戻さない

--- なぜ在庫を先に確定するか（DS-441） ---

決済とDBの更新は1つのトランザクションにできない。どちらかが先になる。

  決済が先: 失敗すると「代金は払ったのに商品が無い」。返金処理が要り、それも失敗しうる
  在庫が先: 失敗すると「在庫を確保したのに注文が成立しない」。在庫を戻せば済む

顧客に金銭的な不利益が生じない方を選ぶ。
"""

from __future__ import annotations

import datetime as dt
import logging
import secrets
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import config
from app.models import Cart, CartItem, Checkout, Member, Order, OrderItem, Reservation, Stock
from app.services import payment_gateway, payment_policy
from app.services.availability import get_db_now
from app.services.cart_service import get_or_create_cart, lock_cart
from app.services.checkout_service import OrderDraft, build_draft
from app.services.errors import (
    CheckoutIncompleteError,
    ConflictError,
    DataIntegrityError,
    NotFoundError,
    OrderInProgressError,
    PaymentDeclinedError,
    StockInsufficientMultiError,
    AmountMismatchError,
    ValidationError,
)
from app.services.reservation import ReservationState
from app.services.stock import (
    STATUS_ACTIVE,
    STATUS_CONFIRMED,
    ReservationRecord,
    calc_available_quantity,
)

logger = logging.getLogger("gu_ec.order")

STATUS_PENDING = "PENDING_PAYMENT"
STATUS_ORDER_CONFIRMED = "CONFIRMED"
STATUS_FAILED = "FAILED"

# 注文番号に使う文字。0/O、1/I/L のように読み違えやすい文字を除く
_ORDER_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


@dataclass(frozen=True)
class OrderOutcome:
    order: Order
    status: str  # CONFIRMED または PENDING_PAYMENT


def _generate_order_number(db: Session) -> str:
    """注文番号を発行する。

    連番にしない。連番だと、自分の注文番号から前後の番号を推測して
    他人の注文を照会する試みが容易になる（テスト仕様書【未確定24】）。
    照会は本人確認を伴うので直ちに漏洩はしないが、推測の手がかりは与えない。
    """
    today = get_db_now(db).strftime("%y%m%d")
    suffix = "".join(secrets.choice(_ORDER_CHARS) for _ in range(8))
    return f"GU{today}{suffix}"


def _find_by_key(db: Session, key: str) -> Order | None:
    return db.execute(select(Order).where(Order.idempotency_key == key)).scalar_one_or_none()


# --- 0. 冪等性 ---------------------------------------------------------


def _replay(db: Session, member: Member, existing: Order, cart: Cart) -> OrderOutcome:
    """同じ冪等キーの注文がすでにある場合の応答（設計仕様書 4.4.8）。

    --- カートが空の場合を再送とみなす理由 ---

    設計仕様書は「冪等キーと fingerprint がともに一致すれば最初の結果を返す」とする。
    しかし注文が成功するとカートを空にする。成功後に届いた再送について
    fingerprint を計算し直すと、カートが空なので必ず一致しない。
    素直に実装すると、ボタンの二度押しに 422 を返してしまう。
    実装の段階で判明した、DS-458 と DS-460 の食い違いである。

    そこで、カートが空なら「最初の要求の再送」とみなす。
    カートに商品があるなら fingerprint を比べ、違えば 422 とする。
    カートを空にした後に同じキーで別の注文を試みる経路は、
    この判定で塞がれる。
    """
    if existing.member_id != member.member_id:
        # 他人の冪等キー。存在を示さないため、内容の不一致と同じ応答にする
        raise ConflictError("この注文は受け付けられません。確認画面を再表示してください")

    # 決済待ちの注文は、内容の比較より先に「処理中」を返す（Gemini の指摘）。
    # 比較を先にすると、決済待ちの間に商品の価格が変わっただけで fingerprint が
    # 一致しなくなり、「内容が変更されました。確認画面から注文し直してください」と
    # 案内してしまう。処理中の注文があるのに、注文し直しを促すのは誤りである。
    if existing.status == STATUS_PENDING:
        raise OrderInProgressError("この注文は処理中です。しばらくしてから注文状況をご確認ください")

    # --- 判定の順序について ---
    #
    # 当初は「カートに商品があるか」を確かめてから、中身を読んで fingerprint を
    # 比べていた。これを本物の DB で同時送信のテストにかけたところ、
    # 二度押しの2つ目の要求に 422 を返すことがあった（TC-IT-ID-02）。
    #
    #   2つ目: カートに商品がある、と確認
    #   1つ目: 決済成功。カートを空にしてコミット
    #   2つ目: カートの中身を読む → 空。注文内容を組み立てられず、422
    #
    # READ COMMITTED では SQL 文ごとに最新の確定データを読むため、
    # 「確認」と「読み取り」の間で状況が変わりうる。
    #
    # そこで先に中身を読み、組み立てられなかった場合に限って
    # 「本当にカートが空になったのか」を改めて確かめる。
    # 空になっていれば、1つ目の後片付けと重なったものとして再送扱いにする。
    try:
        draft = build_draft(db, member, cart, get_db_now(db))
    except CheckoutIncompleteError:
        draft = None

    if draft is not None:
        if draft.fingerprint != existing.content_fingerprint:
            # 同じキーで内容が違う。再送ではない（DS-461）
            raise ConflictError("注文の内容が変更されています。確認画面を再表示してください")
    else:
        has_items = (
            db.execute(
                select(CartItem.cart_item_id).where(CartItem.cart_id == cart.cart_id)
            ).first()
            is not None
        )
        if has_items:
            # カートに商品はあるのに、配送方法などが選ばれていない。
            # 成功した注文の後に、新しい注文を古いキーで試みている
            raise ConflictError("注文の内容が変更されています。確認画面を再表示してください")

    # 1つ目の要求が、この間に PENDING から CONFIRMED へ進んでいる場合がある
    db.refresh(existing)

    if existing.status == STATUS_ORDER_CONFIRMED:
        return OrderOutcome(existing, STATUS_ORDER_CONFIRMED)
    if existing.status == STATUS_PENDING:
        raise OrderInProgressError("この注文は処理中です。しばらくしてから注文状況をご確認ください")
    raise PaymentDeclinedError("決済が完了しませんでした。支払方法を変更して再度お試しください")


# --- 2. 在庫の確定と注文の作成 -------------------------------------------


def _reserve_and_create(
    db: Session, member: Member, draft: OrderDraft, key: str
) -> Order:
    """トランザクション①。この関数はコミットしない。"""
    loc = config.ONLINE_LOCATION_ID
    now = get_db_now(db)

    required: dict[str, int] = defaultdict(int)
    for line in draft.lines:
        required[line.sku_id] += line.quantity
    sku_ids = sorted(required)  # 全員が同じ順序でロックを取る（デッドロックの回避）

    # stock 行を排他ロック。カート投入と同じ「門」を通る
    stocks = {
        s.sku_id: s
        for s in db.execute(
            select(Stock)
            .where(Stock.location_id == loc, Stock.sku_id.in_(sku_ids))
            .order_by(Stock.sku_id)
            .with_for_update()
        ).scalars()
    }

    # ロックを待っていた間に、同じキーの注文が先にコミットされたかもしれない。
    # ボタンの二度押しで2つの要求がほぼ同時に届いた場合がこれにあたる。
    # ここで確かめないと、2つ目の要求が在庫を再計算して「在庫不足」を返してしまう。
    # （最終的な重複の排除は UNIQUE 制約が担う。これはその手前の親切である）
    if _find_by_key(db, key) is not None:
        raise _DuplicateKey()

    # 引当を読む。ロック読み取りにする理由は availability.py を参照
    rows = list(
        db.execute(
            select(Reservation)
            .where(Reservation.location_id == loc, Reservation.sku_id.in_(sku_ids))
            .with_for_update()
        ).scalars()
    )
    own_item_ids = {line.cart_item_id for line in draft.lines}

    # 自分以外の引当だけを差し引いて、自分が使える数を出す。
    # 自分の引当が期限切れでも、他人に取られていなければ注文は成立させる（DS-453）。
    # 引当の期限は在庫の死蔵を防ぐためのもので、注文を妨げるためのものではない。
    shortages = []
    for sku_id in sku_ids:
        others = [
            ReservationRecord(r.quantity, r.status, r.expires_at)
            for r in rows
            if r.sku_id == sku_id and r.cart_item_id not in own_item_ids
        ]
        stock_qty = stocks[sku_id].quantity if sku_id in stocks else 0
        available = calc_available_quantity(stock_qty, others, now)
        if available < required[sku_id]:
            shortages.append(
                {"skuId": sku_id, "requested": required[sku_id], "available": max(available, 0)}
            )
    if shortages:
        # DS-454: どの商品が足りないかを示す
        raise StockInsufficientMultiError(shortages)

    # 在庫を減らす
    for sku_id in sku_ids:
        stock = stocks[sku_id]
        if stock.quantity - required[sku_id] < 0:
            raise DataIntegrityError(f"在庫が負になります: {sku_id}")
        stock.quantity -= required[sku_id]

    order = Order(
        order_number=_generate_order_number(db),
        member_id=member.member_id,
        status=STATUS_PENDING,
        delivery_method=draft.delivery_method,
        placement_type=draft.placement_type,
        payment_method=draft.payment_method,
        idempotency_key=key,
        content_fingerprint=draft.fingerprint,
        # 注文時点の値をコピーする。会員の住所が後で変わっても、この注文の届け先は変わらない
        recipient_name=draft.recipient.name,
        recipient_postal_code=draft.recipient.postal_code,
        recipient_address=draft.recipient.address,
        recipient_phone=draft.recipient.phone,
        subtotal=draft.amounts.subtotal,
        alteration_fee=draft.amounts.alteration_fee,
        shipping_fee=draft.amounts.shipping_fee,
        payment_fee=draft.amounts.payment_fee,
        tax=draft.amounts.tax,
        total=draft.amounts.total,
    )
    db.add(order)
    db.flush()  # ここで UNIQUE 制約に触れれば IntegrityError になる

    for line in draft.lines:
        # 商品名・価格もコピーする。商品マスタが後で変わっても、注文の記録は変わらない
        db.add(
            OrderItem(
                order_id=order.order_id,
                sku_id=line.sku_id,
                product_name=line.product_name,
                color_name=line.color_name,
                size=line.size,
                unit_price=line.unit_price,
                price_type=line.price_type,
                quantity=line.quantity,
                alteration_type=line.alteration_type,
                alteration_length_mm=line.alteration_length_mm,
                alteration_fee=line.alteration_fee,
                is_returnable=line.is_returnable,
            )
        )

    # 自分の引当を確定する。期限切れのものは解放し、足りない分は確定済みの行を作る
    confirmed: dict[int, int] = defaultdict(int)
    for r in rows:
        if r.cart_item_id not in own_item_ids or r.status != STATUS_ACTIVE:
            continue
        state = ReservationState(r.status, r.expires_at)
        if state.is_active(now):
            state.confirm()
            r.order_id = order.order_id
            confirmed[r.cart_item_id] += r.quantity
        else:
            state.release()
        r.status, r.expires_at = state.status, state.expires_at

    for line in draft.lines:
        shortfall = line.quantity - confirmed[line.cart_item_id]
        if shortfall > 0:
            db.add(
                Reservation(
                    sku_id=line.sku_id,
                    location_id=loc,
                    cart_item_id=line.cart_item_id,
                    order_id=order.order_id,
                    quantity=shortfall,
                    status=STATUS_CONFIRMED,
                    expires_at=None,
                )
            )

    db.flush()
    return order


class _DuplicateKey(Exception):
    """同じ冪等キーの注文が、並行する別の要求によって先に作られた。"""


# --- 4. 決済の結果に応じた後処理 ----------------------------------------


def _lock_order(db: Session, order_id: int) -> Order:
    """注文の行に排他ロックをかけ、最新の状態を読み直す。

    決済の後処理（確定・補償）は、必ずこれを通してから状態を確かめる。
    """
    return db.execute(
        select(Order)
        .where(Order.order_id == order_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()


def _finalize_success(db: Session, order: Order, transaction_id: str) -> None:
    """トランザクション②：注文を確定し、注文した明細をカートから消す。

    注文の行をロックし、まだ決済待ちの場合だけ処理する。
    照会と注文確定の応答処理が同時に走っても、確定は1回しか起きない。
    """
    try:
        order = _lock_order(db, order.order_id)
        if order.status != STATUS_PENDING:
            db.rollback()
            return
        order.status = STATUS_ORDER_CONFIRMED
        order.payment_transaction_id = transaction_id

        # 注文に紐づく引当から、カート明細を特定する。
        # カートを丸ごと消さないのは、別タブで追加した商品まで消さないため
        item_ids = [
            r.cart_item_id
            for r in db.execute(
                select(Reservation).where(Reservation.order_id == order.order_id)
            ).scalars()
            if r.cart_item_id is not None
        ]
        cart_id = None
        if item_ids:
            first = db.get(CartItem, item_ids[0])
            cart_id = first.cart_id if first else None
            db.execute(delete(CartItem).where(CartItem.cart_item_id.in_(item_ids)))
        if cart_id is not None:
            db.execute(delete(Checkout).where(Checkout.cart_id == cart_id))
        db.commit()
    except Exception:
        db.rollback()
        # 決済は成立しているのに、注文が PENDING のまま残る。
        # 照会（reconcile）で後から CONFIRMED にできるため、記録して上に返す
        logger.error("決済成立後の確定処理に失敗: order=%s", order.order_number, exc_info=True)
        raise


def _compensate(db: Session, order: Order) -> None:
    """補償処理：在庫を戻し、引当を解放し、注文を FAILED にする（DS-445）。

    カートは消さない（DS-447）。支払方法を変えて再試行できるようにする。

    --- 冪等にする理由（ChatGPT の指摘。再現を確認） ---

    否決が判明した注文を、2つの要求が同時に照会すると、両方が
    「まだ決済待ち」を読んでから補償に入る。在庫の行はロックしていたが、
    ロックを取った後に「この注文の補償はまだか」を確かめていなかったため、
    在庫が2回戻された。在庫40 → 注文で38 → 補償で40 → 二重補償で42。
    実在しない在庫が2点生まれ、そのまま売り越しにつながる。

    注文の行をロックしてから状態を確かめ、決済待ちのときだけ補償する。
    2つ目の要求は、ロックが解けた時点で FAILED を読み、何もせずに戻る。
    ロックの順序は「注文 → 在庫」。
    """
    try:
        order = _lock_order(db, order.order_id)
        if order.status != STATUS_PENDING:
            db.rollback()
            return

        items = list(
            db.execute(select(OrderItem).where(OrderItem.order_id == order.order_id)).scalars()
        )
        restore: dict[str, int] = defaultdict(int)
        for item in items:
            restore[item.sku_id] += item.quantity

        stocks = {
            s.sku_id: s
            for s in db.execute(
                select(Stock)
                .where(
                    Stock.location_id == config.ONLINE_LOCATION_ID,
                    Stock.sku_id.in_(sorted(restore)),
                )
                .order_by(Stock.sku_id)
                .with_for_update()
            ).scalars()
        }
        for sku_id, qty in restore.items():
            stocks[sku_id].quantity += qty

        for r in db.execute(
            select(Reservation).where(Reservation.order_id == order.order_id)
        ).scalars():
            state = ReservationState(r.status, r.expires_at)
            if state.status == STATUS_CONFIRMED:
                state.revert_confirmation()  # 補償専用の遷移。reservation.py を参照
                r.status, r.expires_at = state.status, state.expires_at

        order.status = STATUS_FAILED
        db.commit()
    except Exception:
        db.rollback()
        # DS-446: 補償の失敗は必ず記録する。在庫が減ったまま注文が成立していない状態であり、
        # 自動では回復しない（テスト仕様書【未確定12】）
        logger.error("補償処理に失敗: order=%s", order.order_number, exc_info=True)
        raise


def reconcile(db: Session, order: Order) -> str:
    """決済待ちの注文を PSP に照会し、結果に応じて確定または補償する（DS-449）。

    戻り値は照会後の注文の状態。照会しても結果が分からなければ PENDING のまま。
    注文確定・注文の閲覧・定期照会のどこから呼ばれても、結果は1回しか反映されない
    （_finalize_success と _compensate が注文の行をロックして状態を確かめるため）。
    """
    if order.status != STATUS_PENDING:
        return order.status
    result = payment_gateway.inquire(order.order_number)
    if result.status == payment_gateway.SUCCEEDED:
        _finalize_success(db, order, result.transaction_id)
    elif result.status == payment_gateway.DECLINED:
        _compensate(db, order)
    # 照会も応答しなければ何もしない（TC-IT-TO-04）
    return db.execute(
        select(Order.status).where(Order.order_id == order.order_id)
    ).scalar_one()


def reconcile_pending_orders(db: Session, min_age_seconds: int = 60) -> dict[str, int]:
    """決済待ちのまま一定時間が経った注文を、まとめて照会する。

    ChatGPT の指摘への対処。以前は、利用者が注文の画面を開いたときにしか
    照会していなかった。利用者が二度と開かなければ、否決された注文の在庫が
    減ったまま永久に戻らず、その会員は新しい注文もできなくなる。

    main.py の定期処理から呼ぶ。照会の間隔は設計仕様書 4.5 の未確定事項
    （テスト仕様書【未確定14】）であり、既定の5分は暫定値である。
    """
    now = get_db_now(db)
    threshold = now - dt.timedelta(seconds=min_age_seconds)
    targets = list(
        db.execute(
            select(Order).where(Order.status == STATUS_PENDING, Order.ordered_at <= threshold)
        ).scalars()
    )
    counts: dict[str, int] = defaultdict(int)
    for order in targets:
        try:
            counts[reconcile(db, order)] += 1
        except Exception:
            db.rollback()
            counts["ERROR"] += 1
            logger.error("定期照会に失敗: order=%s", order.order_number, exc_info=True)
    return dict(counts)


# --- 公開する関数 -------------------------------------------------------


def create_order(
    db: Session, member: Member, idempotency_key: str | None, expected_total: int
) -> OrderOutcome:
    if not idempotency_key or len(idempotency_key) > 64:
        raise ValidationError("Idempotency-Key ヘッダが必要です（64文字以内）")

    # 会員のカートを引く。要求にカートIDを含めないので、
    # 他人のカートを指定するという操作がそもそも成立しない（DS-455）
    cart, _ = get_or_create_cart(db, member, None)

    existing = _find_by_key(db, idempotency_key)
    if existing is not None:
        return _replay(db, member, existing, cart)

    # 決済待ちの注文があれば、まず照会して結果を確定させてみる。
    # 結果が分かれば、利用者は待たずに次の注文へ進める。
    # カートのロックより前に行う。照会の後処理は「注文 → カート明細」の順で
    # 触るので、カートを押さえたまま照会すると、ロックの順序が逆転する。
    for pending_order in db.execute(
        select(Order).where(Order.member_id == member.member_id, Order.status == STATUS_PENDING)
    ).scalars().all():
        reconcile(db, pending_order)

    # --- ここから、このカートに対する操作を一列に並べる ---
    #
    # ChatGPT の指摘（再現を確認）：2つのタブから別々の冪等キーでほぼ同時に
    # 注文すると、同じカートから注文が2件でき、決済も2回走っていた。
    # 在庫のロックは取っていたが、同じ冪等キーの重複しか確かめていなかったため、
    # キーが違う2件目は素通りしていた。
    #
    # カートの行をロックしてから、決済待ちの有無の確認・注文内容の組み立て・
    # 在庫の確定までを行う。2件目は、1件目のトランザクションが終わるまで待ち、
    # 決済待ちの注文（1件目）を見つけて止まる。
    #
    # 注文内容の組み立てもロックの内側に置く。外に置くと、組み立てた後に
    # 別タブでカートの数量が変わり、注文の数量と確定する引当の数量が
    # 食い違う（ChatGPT の別の指摘）。
    cart = lock_cart(db, cart)

    # 決済の結果が未確定の注文がある間は、新しい注文を受け付けない。
    # その注文の引当は CONFIRMED のままカートに残っている（【未確定13】）。
    pending = db.execute(
        select(Order.order_number).where(
            Order.member_id == member.member_id, Order.status == STATUS_PENDING
        )
    ).first()
    if pending is not None:
        db.rollback()
        raise OrderInProgressError(
            "処理中のご注文があります。注文状況をご確認のうえ、しばらくしてからお試しください"
        )

    draft = build_draft(db, member, cart, get_db_now(db))

    # --- 確認画面で見せた内容と、いまの注文内容が一致するか ---
    #
    # ChatGPT の指摘（再現を確認）：確認画面を開いた後、別タブで中身を
    # 同額のまま差し替えると（丈 700mm → 650mm など）、古い確認画面から
    # 押した「注文を確定する」で、差し替え後の内容が注文されていた。
    # 金額だけを照合していたため、利用者が確認していない内容で注文が成立した。
    #
    # 確認画面を出した時点の冪等キーと fingerprint を保存しておき、
    # 両方が一致しなければ注文させない。
    checkout = db.get(Checkout, cart.cart_id)
    if (
        checkout is None
        or checkout.summary_idempotency_key != idempotency_key
        or checkout.summary_fingerprint != draft.fingerprint
    ):
        db.rollback()
        raise ConflictError("ご注文の内容が変更されています。確認画面を再表示してください")

    # 配送方法と支払方法の整合を再検証する。
    # 選択後に別タブで配送方法を変えられている可能性がある
    reason = payment_policy.reason_for(
        draft.payment_method, draft.delivery_method, draft.placement_type
    )
    if reason is not None:
        db.rollback()
        raise CheckoutIncompleteError(reason.message)

    # DS-628: Frontend の算出額と照合する。
    # DS-629: 一致しなくても、正しい金額は教えない
    if expected_total != draft.amounts.total:
        db.rollback()
        raise AmountMismatchError("ご注文の金額が変更されています。確認画面を再表示してください")

    # トランザクション①
    try:
        order = _reserve_and_create(db, member, draft, idempotency_key)
        db.commit()
    except (_DuplicateKey, IntegrityError) as exc:
        db.rollback()
        if isinstance(exc, IntegrityError) and "idempotency" not in str(exc.orig).lower():
            raise
        # DS-459: 同時に届いた同じキーの要求。先に作られた注文の結果を返す
        existing = _find_by_key(db, idempotency_key)
        if existing is None:
            raise
        return _replay(db, member, existing, cart)
    except Exception:
        db.rollback()
        raise

    # 決済。ここは DB のトランザクションの外
    result = payment_gateway.charge(order.order_number, order.total, order.payment_method)

    if result.status == payment_gateway.SUCCEEDED:
        _finalize_success(db, order, result.transaction_id)
        return OrderOutcome(db.get(Order, order.order_id), STATUS_ORDER_CONFIRMED)

    if result.status == payment_gateway.DECLINED:
        logger.error("決済が否決されました: order=%s", order.order_number)  # TC-IT-NG-03
        _compensate(db, order)
        raise PaymentDeclinedError("決済が完了しませんでした。支払方法を変更して再度お試しください")

    # 応答なし。失敗として扱わない（DS-448）。在庫も戻さない（DS-450）
    logger.warning("決済の応答が得られません。照会待ち: order=%s", order.order_number)
    return OrderOutcome(order, STATUS_PENDING)


def get_order(db: Session, member: Member, order_number: str) -> Order:
    """注文を取得する。決済待ちなら PSP に照会して状態を確定させる（DS-449）。"""
    order = db.execute(
        select(Order).where(
            Order.order_number == order_number, Order.member_id == member.member_id
        )
    ).scalar_one_or_none()
    if order is None:
        # 他人の注文と存在しない注文を区別しない（DS-456）
        raise NotFoundError("注文が見つかりません")

    if order.status == STATUS_PENDING:
        reconcile(db, order)
        db.refresh(order)

    return order
