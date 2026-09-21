"""テスト仕様書 4.2 Stock（引当可能数の算出）"""

import datetime as dt

import pytest

from app.services.errors import DataIntegrityError
from app.services.stock import ReservationRecord, calc_available_quantity, can_reserve

NOW = dt.datetime(2026, 9, 20, 12, 0, 0)


def active(qty: int, seconds_from_now: int = 600) -> ReservationRecord:
    return ReservationRecord(qty, "ACTIVE", NOW + dt.timedelta(seconds=seconds_from_now))


def confirmed(qty: int) -> ReservationRecord:
    return ReservationRecord(qty, "CONFIRMED", None)


def released(qty: int) -> ReservationRecord:
    return ReservationRecord(qty, "RELEASED", None)


# --- 4.2.2 引当可能数 ---------------------------------------------------


@pytest.mark.parametrize(
    "stock, reservations, expected",
    [
        pytest.param(10, [], 10, id="TC-UT-ST-01_引当なし"),
        pytest.param(10, [active(3)], 7, id="TC-UT-ST-02_ACTIVE期限内"),
        pytest.param(10, [released(3)], 10, id="TC-UT-ST-03_RELEASEDは減算しない"),
        # 二重減算の検出。8 が返れば設計か実装に誤りがある
        pytest.param(9, [confirmed(1)], 9, id="TC-UT-ST-04_CONFIRMEDは減算しない"),
        pytest.param(
            10, [active(2), confirmed(3), released(1)], 8, id="TC-UT-ST-05_混在"
        ),
        pytest.param(10, [active(10)], 0, id="TC-UT-ST-06_全数引当"),
        pytest.param(0, [], 0, id="TC-UT-ST-07_在庫0"),
    ],
)
def test_available_quantity(stock, reservations, expected):
    assert calc_available_quantity(stock, reservations, NOW) == expected


@pytest.mark.parametrize(
    "available, requested, expected",
    [
        pytest.param(5, 5, True, id="TC-UT-ST-08_要求と同数"),
        pytest.param(5, 6, False, id="TC-UT-ST-09_要求が1多い"),
        pytest.param(5, 4, True, id="TC-UT-ST-10_要求が1少ない"),
    ],
)
def test_can_reserve(available, requested, expected):
    assert can_reserve(available, requested) is expected


@pytest.mark.parametrize(
    "seconds_from_now, expected",
    [
        pytest.param(-1, 10, id="TC-UT-ST-11_期限の1秒後は減算しない"),
        # expires_at > now であり、一致は条件を満たさない
        pytest.param(0, 10, id="TC-UT-ST-12_期限ちょうどは減算しない"),
        pytest.param(1, 7, id="TC-UT-ST-13_期限の1秒前は減算する"),
    ],
)
def test_expiry_boundary(seconds_from_now, expected):
    assert calc_available_quantity(10, [active(3, seconds_from_now)], NOW) == expected


def test_TC_UT_ST_14_negative_stock_raises():
    """在庫が負であれば、0 に丸めず例外とする（DS-322）。"""
    with pytest.raises(DataIntegrityError):
        calc_available_quantity(-2, [], NOW)


@pytest.mark.skip(reason="【未確定1】要求数量0。実装は ValueError を投げる")
def test_TC_UT_ST_15_zero_request():
    pass


@pytest.mark.skip(reason="【未確定1】要求数量-1。実装は ValueError を投げる")
def test_TC_UT_ST_16_negative_request():
    pass


# --- 4.2.3 悪用の観点 ---------------------------------------------------


def test_TC_UT_ST_20_huge_request_does_not_overflow():
    """Python の int は桁あふれしないが、他言語への移植時に壊れないことの記録として残す。"""
    assert can_reserve(5, 10**18) is False


@pytest.mark.skip(reason="【未確定2】同一の引当の重複。実装は重複ぶんも二重に計上する")
def test_TC_UT_ST_21_duplicate_reservations():
    pass
