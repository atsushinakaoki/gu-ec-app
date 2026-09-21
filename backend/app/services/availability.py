"""引当可能数の取得（DB アクセスを伴う層）。

計算式そのものは services/stock.py にあり、ここは
「DB から材料を読んで、その関数に渡す」だけを担う。

現在時刻は必ず DB から取る。
アプリケーション側の datetime.now() を使うと、SQL 内の比較と
Python 側の比較で基準となる時計が変わり、時刻が僅かにずれた場合に
「SQL では有効、Python では失効」という食い違いが起きる。
テスト仕様書 8.4.3（TE-01）で指摘された論点である。
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app import config
from app.models import Reservation, Stock
from app.services.stock import ReservationRecord, calc_available_quantity


def get_db_now(db: Session) -> dt.datetime:
    """DB サーバの現在時刻を返す。"""
    return db.execute(text("SELECT NOW()")).scalar_one()


def get_available_quantities(
    db: Session,
    sku_ids: list[str],
    now: dt.datetime,
    location_id: int | None = None,
    for_update: bool = False,
) -> dict[str, int]:
    """SKU ごとの引当可能数を返す。

    for_update=True のとき、stock 行に排他ロックをかける。
    カート投入・注文確定のように、読んだ値をもとに書き込む場合に指定する。
    単なる表示のために指定してはならない（不要なロック待ちを生む）。

    ロックは stock 行にかける。reservation 行ではない。
    引き当てようとしている競合は必ず同じ stock 行を見に来るため、
    そこが直列化の一点になる。reservation 側をロックしても、
    まだ存在しない行（これから INSERT される引当）は押さえられない。
    """
    if not sku_ids:
        return {}

    loc = config.ONLINE_LOCATION_ID if location_id is None else location_id

    stock_stmt = select(Stock).where(
        Stock.location_id == loc, Stock.sku_id.in_(sku_ids)
    )
    if for_update:
        # 複数行をロックするときは、必ず同じ順序で取りに行く。
        # A→B の順で待つ処理と B→A の順で待つ処理が同時に走ると、
        # 互いの解放を待ち合ってデッドロックになる。
        # sku_id で整列させておけば、全員が同じ順序で並ぶ。
        stock_stmt = stock_stmt.order_by(Stock.sku_id).with_for_update()
    stocks = {s.sku_id: s.quantity for s in db.execute(stock_stmt).scalars()}

    reservation_stmt = select(Reservation).where(
        Reservation.location_id == loc, Reservation.sku_id.in_(sku_ids)
    )
    if for_update:
        # --- ここをロック読み取りにする理由 ---
        #
        # stock 行のロックは正しく機能しており、他者は確かに待たされる。
        # しかし待ち終わったあとに読むこの SELECT が、通常の読み取りだと
        # トランザクション開始時点のスナップショットを返す。
        # MySQL の既定である REPEATABLE READ の挙動である。
        #
        #   T1: 商品を読む（この瞬間にスナップショットが固定される）
        #   T2: 商品を読む（この瞬間にスナップショットが固定される）
        #   T1: stock を FOR UPDATE でロック
        #   T2: ロック待ちで停止
        #   T1: 引当を数える → 0件 → 引当を INSERT → COMMIT（ロック解放）
        #   T2: ロック取得。引当を数える
        #       → 固定済みのスナップショットのため T1 の INSERT が見えない
        #       → 0件と判定し、同じ在庫を二重に引き当てる
        #
        # ロックはかかっているのに、ロックで守った区間の中で
        # 過去を見ている。これが在庫の二重引当の正体だった。
        #
        # ロック読み取り（SQLAlchemy は LOCK IN SHARE MODE を発行する。
        # MySQL 8 の FOR SHARE と同義）は、スナップショットではなく
        # 最新の確定データを読む。分離レベルの設定に関わらず成立するため、
        # DB 側の設定が変わっても壊れない。
        #
        # FOR UPDATE ではなく FOR SHARE としているのは、ここでは
        # 引当行を書き換えないためである。必要以上に強いロックを取ると、
        # 待ち合わせが増えてデッドロックの機会を作る。
        #
        # この行の直前で stock 行の排他ロックを取得済みであり、
        # 同じ SKU を扱う処理は必ずその順序で通るため、
        # ロックの取得順序が交差することはない。
        reservation_stmt = reservation_stmt.with_for_update(read=True)

    reservations = db.execute(reservation_stmt).scalars()

    by_sku: dict[str, list[ReservationRecord]] = {sku_id: [] for sku_id in sku_ids}
    for r in reservations:
        by_sku.setdefault(r.sku_id, []).append(
            ReservationRecord(quantity=r.quantity, status=r.status, expires_at=r.expires_at)
        )

    result: dict[str, int] = {}
    for sku_id in sku_ids:
        # stock 行が存在しない SKU は、在庫を持たない扱いとする
        quantity = stocks.get(sku_id, 0)
        result[sku_id] = calc_available_quantity(quantity, by_sku.get(sku_id, []), now)
    return result
