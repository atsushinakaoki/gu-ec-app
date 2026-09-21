"""カートへの投入と、それに伴う在庫引当。

設計仕様書 4.2（カート投入シーケンス）に対応する。
このアプリケーションで最も壊れやすい箇所であり、
同時実行の正しさをここで担保する。

--- 悲観ロックを選んだ理由 ---

在庫1点を2人が同時に取りに来た場合、何もしなければ両方が
「引当可能数 1 >= 要求 1」と判定して、2件の引当が入る。在庫は1点しかない。

対策には大きく2通りある。

  楽観ロック: version 列を持ち、更新時に version が変わっていたら失敗させる
  悲観ロック: 読む時点で行に排他ロックをかけ、他を待たせる

ここでは悲観ロックを採る。理由は、引当可能数が stock 行だけでは決まらず、
reservation テーブルの集計を伴うためである。楽観ロックは「自分が読んだ行が
変わっていないこと」しか保証できないが、ここで守りたいのは
「stock を読んでから reservation を INSERT するまでの間に、
他者が reservation を INSERT しないこと」である。守りたい範囲が
単一行の更新に収まっていないため、楽観ロックでは表現できない。

--- どの行をロックするか ---

stock 行にロックをかける。reservation 行ではない。

reservation をロックしても、これから INSERT される行は存在しないので
押さえられない。一方 stock 行は、同じ SKU を取りに来る全員が必ず読む。
そこを直列化の一点にすれば、「読む→判定する→書く」が一人ずつ順番に行われる。

在庫を減らさない（カート投入では stock.quantity を触らない）のに
stock 行をロックするのは奇妙に見えるが、ここでは stock 行を
「その SKU の在庫に関する操作の門」として使っている。
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import config
from app.models import Cart, CartItem, Member, Product, Reservation, Sku
from app.services.alteration import AlterableSpec, validate_alteration
from app.services.availability import get_available_quantities, get_db_now
from app.services.errors import (
    NotFoundError,
    StockInsufficientError,
    ValidationError,
)
from app.services.reservation import ReservationState
from app.services.stock import STATUS_ACTIVE, can_reserve

MAX_QUANTITY_PER_ITEM = 10  # schema.sql の chk_cart_item_quantity と対応
MAX_ITEMS_PER_CART = 100


# --- カートの特定 -------------------------------------------------------


def get_or_create_cart(
    db: Session, member: Member | None, session_id: str | None
) -> tuple[Cart, str | None]:
    """カートを取得する。無ければ作る。

    戻り値の第2要素は、新たに発行したセッションID（未ログインの場合のみ）。
    呼び出し側がこれを Cookie に載せる。

    ログイン済みなら member_id、未ログインなら session_id でカートを引く。
    未ログインでもカートが成立するのは要件（設計仕様書 3.3.7）であり、
    購入意思が固まる前にログインを強制しない、というGUの設計に従っている。
    """
    if member is not None:
        cart = db.execute(
            select(Cart).where(Cart.member_id == member.member_id)
        ).scalar_one_or_none()
        if cart is None:
            cart = Cart(member_id=member.member_id)
            db.add(cart)
            db.flush()
        return cart, None

    if session_id:
        cart = db.execute(
            select(Cart).where(Cart.session_id == session_id)
        ).scalar_one_or_none()
        if cart is not None:
            return cart, None

    new_session_id = uuid.uuid4().hex
    cart = Cart(session_id=new_session_id)
    db.add(cart)
    db.flush()
    return cart, new_session_id


# --- カートの統合 -------------------------------------------------------


@dataclass(frozen=True)
class DiscardedLine:
    product_name: str
    color_name: str
    size: str
    alteration_length_mm: int | None


def merge_guest_cart(db: Session, member: Member, session_id: str | None) -> list[DiscardedLine]:
    """未ログインのカートを会員のカートへ統合する（設計仕様書 4.2.2）。

    戻り値は、統合により破棄した明細（DS-425: 顧客に知らせるため）。
    この関数はコミットしない。

    規則:
      - 会員のカートが無ければ、未ログインのカートをそのまま会員のものにする
      - 同じ明細（sku + 加工方法 + 丈。DS-428）が両方にあれば、会員側を残す（DS-424）
        合算しないのは、合算すると追加の引当が必要になり、
        「ログインしたら在庫不足のエラーが出た」が起こりうるため
      - 破棄する明細の引当は解放する（DS-426）
      - 引当の期限は延ばさない（DS-427）。明細を移すだけで reservation には触れない
    """
    if not session_id:
        return []
    guest = db.execute(
        select(Cart).where(Cart.session_id == session_id, Cart.member_id.is_(None))
    ).scalar_one_or_none()
    if guest is None:
        return []

    member_cart = db.execute(
        select(Cart).where(Cart.member_id == member.member_id)
    ).scalar_one_or_none()

    if member_cart is None:
        guest.member_id = member.member_id
        guest.session_id = None
        db.flush()
        return []

    member_items = list(
        db.execute(select(CartItem).where(CartItem.cart_id == member_cart.cart_id)).scalars()
    )
    member_keys = {(i.sku_id, i.alteration_type, i.alteration_length_mm) for i in member_items}
    count = len(member_items)

    guest_items = list(
        db.execute(select(CartItem).where(CartItem.cart_id == guest.cart_id)).scalars()
    )
    discarded: list[DiscardedLine] = []
    for item in guest_items:
        key = (item.sku_id, item.alteration_type, item.alteration_length_mm)
        if key in member_keys or count >= MAX_ITEMS_PER_CART:
            sku = db.get(Sku, item.sku_id)
            product = db.get(Product, sku.product_id)
            discarded.append(
                DiscardedLine(product.name, sku.color_name, sku.size, item.alteration_length_mm)
            )
            for r in db.execute(
                select(Reservation).where(Reservation.cart_item_id == item.cart_item_id)
            ).scalars():
                state = ReservationState(r.status, r.expires_at)
                state.release()
                r.status, r.expires_at = state.status, state.expires_at
            db.execute(delete(CartItem).where(CartItem.cart_item_id == item.cart_item_id))
        else:
            item.cart_id = member_cart.cart_id
            member_keys.add(key)
            count += 1

    db.flush()
    # ORM の cascade（Cart.items の delete-orphan）を通すと、移したはずの明細まで
    # メモリ上の関連に残っていて一緒に消える。SQL で直接、空のカートだけを消す
    db.execute(delete(Cart).where(Cart.cart_id == guest.cart_id))
    db.expunge(guest)
    return discarded


# --- 入力値の検証 -------------------------------------------------------
# すそ上げの検証は services/alteration.py に置く。DB を読まずに単体テストするため。


# --- 投入 ---------------------------------------------------------------


def add_item(
    db: Session,
    cart: Cart,
    sku_id: str,
    quantity: int,
    alteration_type: str | None = None,
    alteration_length_mm: int | None = None,
) -> tuple[CartItem, dt.datetime]:
    """カートに1明細を投入し、在庫を引き当てる。

    この関数はコミットしない。トランザクションの境界は呼び出し側が持つ。
    引当の INSERT とカート明細の INSERT が別々にコミットされると、
    「引当はあるのにカートに無い」在庫が生まれる。
    """
    if quantity < 1:
        raise ValidationError("数量は1以上を指定してください")
    if quantity > MAX_QUANTITY_PER_ITEM:
        raise ValidationError(
            f"1明細あたりの数量は{MAX_QUANTITY_PER_ITEM}点までです"
        )

    sku = db.get(Sku, sku_id)
    if sku is None:
        raise NotFoundError(f"SKUが見つかりません: {sku_id}")

    product = db.get(Product, sku.product_id)
    if product is None:
        raise NotFoundError(f"商品が見つかりません: {sku.product_id}")

    validate_alteration(
        AlterableSpec(
            product_id=product.product_id,
            alterable=product.alterable,
            original_length_mm=product.original_length_mm,
            min_alteration_length_mm=product.min_alteration_length_mm,
        ),
        alteration_type,
        alteration_length_mm,
    )

    # DS-428: 明細の同一性は sku_id + alteration_type + alteration_length_mm。
    # 同じ SKU でも、丈が違えば別物として扱う。
    # SKU だけで同一と見なすと、シングル仕上げとダブル仕上げが
    # 1明細に統合されてしまい、どちらで加工すべきか決まらなくなる。
    existing = db.execute(
        select(CartItem).where(
            CartItem.cart_id == cart.cart_id,
            CartItem.sku_id == sku_id,
            CartItem.alteration_type.is_(alteration_type)
            if alteration_type is None
            else CartItem.alteration_type == alteration_type,
            CartItem.alteration_length_mm.is_(alteration_length_mm)
            if alteration_length_mm is None
            else CartItem.alteration_length_mm == alteration_length_mm,
        )
    ).scalar_one_or_none()

    if existing is None:
        item_count = len(
            db.execute(
                select(CartItem.cart_item_id).where(CartItem.cart_id == cart.cart_id)
            ).all()
        )
        if item_count >= MAX_ITEMS_PER_CART:
            raise ValidationError(f"カートの明細数は{MAX_ITEMS_PER_CART}件までです")
        new_quantity = quantity
    else:
        new_quantity = existing.quantity + quantity
        if new_quantity > MAX_QUANTITY_PER_ITEM:
            raise ValidationError(
                f"同じ明細の合計数量は{MAX_QUANTITY_PER_ITEM}点までです"
                f"（現在{existing.quantity}点）"
            )

    # --- ここから在庫の判定。stock 行に排他ロックをかける ---
    now = get_db_now(db)
    available = get_available_quantities(
        db, [sku_id], now, location_id=config.ONLINE_LOCATION_ID, for_update=True
    )[sku_id]

    # 今回追加する分だけを要求として判定する。
    # 既存明細ぶんは、すでに引当が入っているため available から差し引かれている。
    if not can_reserve(available, quantity):
        raise StockInsufficientError(sku_id=sku_id, requested=quantity, available=available)

    if existing is None:
        item = CartItem(
            cart_id=cart.cart_id,
            sku_id=sku_id,
            quantity=new_quantity,
            alteration_type=alteration_type,
            alteration_length_mm=alteration_length_mm,
        )
        db.add(item)
        db.flush()
    else:
        existing.quantity = new_quantity
        item = existing

    expires_at = now + dt.timedelta(minutes=config.RESERVATION_TTL_MINUTES)

    # 追加分について、新しい引当行を作る。既存の引当の数量を増やして
    # 期限を延ばす実装も考えられるが、それだと1点ずつ追加を繰り返すだけで
    # 在庫を無期限に押さえられてしまう（テスト仕様書7章の濫用観点）。
    # 行を分ければ、先に入れた分は先に失効する。
    db.add(
        Reservation(
            sku_id=sku_id,
            location_id=config.ONLINE_LOCATION_ID,
            cart_item_id=item.cart_item_id,
            quantity=quantity,
            status=STATUS_ACTIVE,
            expires_at=expires_at,
        )
    )
    db.flush()

    return item, expires_at
