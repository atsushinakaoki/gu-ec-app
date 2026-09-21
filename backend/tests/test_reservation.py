"""テスト仕様書 4.3 Reservation（有効性の判定と状態遷移）"""

import datetime as dt

import pytest

from app.services.errors import InvalidStateError
from app.services.reservation import ReservationState

CREATED = dt.datetime(2026, 9, 20, 12, 0, 0)
EXPIRES = CREATED + dt.timedelta(minutes=60)


def at(minutes: int, seconds: int = 0) -> dt.datetime:
    return CREATED + dt.timedelta(minutes=minutes, seconds=seconds)


# --- 4.3.2 有効性の判定 -------------------------------------------------


@pytest.mark.parametrize(
    "status, now, expected",
    [
        pytest.param("ACTIVE", at(30), True, id="TC-UT-RS-01_30分00秒"),
        pytest.param("ACTIVE", at(59, 59), True, id="TC-UT-RS-02_59分59秒"),
        pytest.param("ACTIVE", at(60), False, id="TC-UT-RS-03_60分00秒ちょうど"),
        pytest.param("ACTIVE", at(60, 1), False, id="TC-UT-RS-04_60分01秒"),
        pytest.param("ACTIVE", at(0), True, id="TC-UT-RS-05_投入直後"),
        pytest.param("CONFIRMED", at(30), False, id="TC-UT-RS-06_CONFIRMED"),
        pytest.param("RELEASED", at(30), False, id="TC-UT-RS-07_RELEASED"),
    ],
)
def test_is_active(status, now, expected):
    assert ReservationState(status, EXPIRES).is_active(now) is expected


@pytest.mark.skip(reason="【未確定3】ACTIVE かつ expires_at が null。実装は DataIntegrityError を投げる")
def test_TC_UT_RS_08_active_without_expiry():
    pass


# --- 4.3.3 状態遷移 -----------------------------------------------------


def test_TC_UT_RS_10_confirm_from_active():
    state = ReservationState("ACTIVE", EXPIRES)
    state.confirm()
    assert state.status == "CONFIRMED"


def test_TC_UT_RS_11_release_from_active():
    state = ReservationState("ACTIVE", EXPIRES)
    state.release()
    assert state.status == "RELEASED"


@pytest.mark.parametrize(
    "initial, operation",
    [
        pytest.param("CONFIRMED", "confirm", id="TC-UT-RS-12_CONFIRMEDにconfirm"),
        pytest.param("RELEASED", "confirm", id="TC-UT-RS-13_RELEASEDにconfirm"),
        pytest.param("CONFIRMED", "release", id="TC-UT-RS-14_CONFIRMEDにrelease"),
    ],
)
def test_invalid_transition_raises_and_keeps_state(initial, operation):
    """例外が出ることに加え、状態が変化していないことを確かめる。

    例外を投げる前に status を書き換えてしまう実装だと、
    例外は出るのに状態は壊れている、という最も発見しにくい不具合になる。
    """
    state = ReservationState(initial, None)
    with pytest.raises(InvalidStateError):
        getattr(state, operation)()
    assert state.status == initial


def test_TC_UT_RS_15_release_is_idempotent():
    """RELEASED への release() は何もしない。例外も投げない（DS-332）。"""
    state = ReservationState("RELEASED", None)
    state.release()
    assert state.status == "RELEASED"


# --- 4.3.4 悪用の観点 ---------------------------------------------------


def test_TC_UT_RS_20_future_time_after_expiry():
    assert ReservationState("ACTIVE", EXPIRES).is_active(at(24 * 60)) is False


def test_TC_UT_RS_21_double_confirm():
    state = ReservationState("ACTIVE", EXPIRES)
    state.confirm()
    with pytest.raises(InvalidStateError):
        state.confirm()
    assert state.status == "CONFIRMED"


# --- 補償処理の遷移（実装時に追加。DS-333 と DS-445 の矛盾への対処） ---


def test_revert_confirmation_from_confirmed():
    """決済の失敗時、確定済みの引当を解放できる。"""
    state = ReservationState("CONFIRMED", None)
    state.revert_confirmation()
    assert state.status == "RELEASED"


@pytest.mark.parametrize("initial", ["ACTIVE", "RELEASED"])
def test_revert_confirmation_only_from_confirmed(initial):
    state = ReservationState(initial, EXPIRES if initial == "ACTIVE" else None)
    with pytest.raises(InvalidStateError):
        state.revert_confirmation()
    assert state.status == initial


def test_release_still_rejects_confirmed():
    """補償用の遷移を足しても、通常の release() は CONFIRMED を拒否し続ける（DS-333）。"""
    state = ReservationState("CONFIRMED", None)
    with pytest.raises(InvalidStateError):
        state.release()
