"""引当可能数の算出。

設計仕様書 DS-341:
    引当可能数 = stock.quantity - SUM(status = ACTIVE かつ expires_at > now の quantity)

CONFIRMED を減算しない点が、この設計の要である。
注文確定時に stock.quantity 自体を減らすため、CONFIRMED も引くと
1注文につき同じ数量を二重に減算してしまう（TC-UT-ST-04）。

このモジュールは DB に触れない。減算の対象となる引当は呼び出し側が
SELECT ... FOR UPDATE で読み、値として渡す。
こうすることで、計算式そのものを単体テストできる。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from app.services.errors import DataIntegrityError

STATUS_ACTIVE = "ACTIVE"
STATUS_CONFIRMED = "CONFIRMED"
STATUS_RELEASED = "RELEASED"


@dataclass(frozen=True)
class ReservationRecord:
    """引当可能数の算出に必要な引当の情報だけを持つ。"""

    quantity: int
    status: str
    expires_at: dt.datetime | None


def is_deducted(reservation: ReservationRecord, now: dt.datetime) -> bool:
    """この引当を引当可能数から減算するか。

    ACTIVE であり、かつ期限が現在時刻より後であるものだけを減算する。

    期限との比較は `expires_at > now` とする。`>=` ではない。
    期限ちょうどの瞬間、その引当はすでに失効している（TC-UT-ST-12）。
    等号をどちらに寄せるかで、境界の1件が数えられたり数えられなかったりする。
    """
    if reservation.status != STATUS_ACTIVE:
        return False
    if reservation.expires_at is None:
        # ACTIVE なら expires_at は必須（schema.sql の chk_reservation_expires）。
        # ここに来るのはデータが壊れている場合だけである。
        raise DataIntegrityError("ACTIVE な引当に expires_at が設定されていません")
    return reservation.expires_at > now


def calc_available_quantity(
    stock_quantity: int,
    reservations: list[ReservationRecord],
    now: dt.datetime,
) -> int:
    """引当可能数を返す。"""
    if stock_quantity < 0:
        # DS-322: 負の在庫はデータの破損である。0 に丸めて隠さない。
        raise DataIntegrityError(f"在庫数が負です: {stock_quantity}")

    reserved = sum(r.quantity for r in reservations if is_deducted(r, now))
    return stock_quantity - reserved


def can_reserve(available_quantity: int, requested_quantity: int) -> bool:
    """要求数量を引き当てられるか。

    引当可能数と要求が等しい場合は引き当てられる（TC-UT-ST-08）。
    最後の1点を買えないのでは在庫の意味がない。
    """
    if requested_quantity < 1:
        raise ValueError(f"要求数量は1以上である必要があります: {requested_quantity}")
    return requested_quantity <= available_quantity
