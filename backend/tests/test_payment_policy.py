"""テスト仕様書 4.5 PaymentMethodPolicy（配送方法 × 支払方法）"""

import pytest

from app.services.payment_policy import (
    CAUSED_BY_DELIVERY,
    CAUSED_BY_PLACEMENT,
    available_methods,
    evaluate,
    reason_for,
)

ALL = {"CREDIT_CARD", "PAYPAY", "D_BARAI", "DEFERRED", "COD"}
CASHLESS = {"CREDIT_CARD", "PAYPAY", "D_BARAI"}

# --- 4.5.2 デシジョンテーブル -------------------------------------------


def test_TC_UT_PM_01_home_with_placement():
    assert available_methods("HOME", "FRONT_DOOR") == CASHLESS


def test_TC_UT_PM_02_home_without_placement():
    assert available_methods("HOME", None) == ALL


def test_TC_UT_PM_03_store_pickup_excludes_deferred():
    assert "DEFERRED" not in available_methods("STORE_PICKUP", None)


def test_TC_UT_PM_04_nekoposu_excludes_deferred():
    assert "DEFERRED" not in available_methods("NEKOPOSU", None)


@pytest.mark.skip(reason="TBD 店舗受取り × 代金引換え。要件定義書では【推論】で不可。実装は不可（暫定）")
def test_TC_UT_PM_05_store_pickup_cod():
    pass


@pytest.mark.skip(reason="TBD ネコポス × 代金引換え。要件定義書では【推論】で不可。実装は不可（暫定）")
def test_TC_UT_PM_06_nekoposu_cod():
    pass


# --- 4.5.3 理由の判定 ---------------------------------------------------


def test_TC_UT_PM_10_reason_points_to_placement():
    """置き配をやめれば選べる。原因は配送方法ではなく置き配である。"""
    reason = reason_for("COD", "HOME", "FRONT_DOOR")
    assert reason is not None
    assert reason.caused_by == CAUSED_BY_PLACEMENT


def test_TC_UT_PM_11_reason_points_to_delivery_method():
    reason = reason_for("DEFERRED", "STORE_PICKUP", None)
    assert reason is not None
    assert reason.caused_by == CAUSED_BY_DELIVERY


def test_TC_UT_PM_12_no_reason_when_available():
    assert reason_for("COD", "HOME", None) is None


# 有効な全組み合わせ（配送方法 × 置き配の有無）
VALID_CONTEXTS = [
    ("HOME", None),
    ("HOME", "FRONT_DOOR"),
    ("STORE_PICKUP", None),
    ("NEKOPOSU", None),
]


@pytest.mark.parametrize("delivery, placement", VALID_CONTEXTS)
def test_TC_UT_PM_13_14_availability_and_reason_are_consistent(delivery, placement):
    """選べるなら理由は無く、選べないなら理由が必ずある。

    全組み合わせを総当たりする。1件ずつ手で書くと、
    組み合わせが増えたときに漏れる。
    """
    for option in evaluate(delivery, placement):
        if option.available:
            assert option.reason is None, f"TC-UT-PM-13 {option.code}"
        else:
            assert option.reason is not None, f"TC-UT-PM-14 {option.code}"


# --- 4.5.4 状態の変化および異常系 ---------------------------------------


def test_TC_UT_PM_20_reevaluate_after_removing_placement():
    before = available_methods("HOME", "FRONT_DOOR")
    after = available_methods("HOME", None)
    assert {"DEFERRED", "COD"}.isdisjoint(before)
    assert {"DEFERRED", "COD"} <= after


@pytest.mark.skip(reason="【未確定8】未定義の配送方法。実装は ValueError を投げる")
def test_TC_UT_PM_30_unknown_delivery():
    pass


@pytest.mark.skip(reason="【未確定8】指定住所以外で置き配を指定。実装は ValueError を投げる")
def test_TC_UT_PM_31_placement_without_home():
    pass


@pytest.mark.skip(reason="【未確定8】配送方法が null。実装は ValueError を投げる")
def test_TC_UT_PM_32_null_delivery():
    pass


def test_cashless_always_available():
    """キャッシュレス3種はどの配送方法でも選べる（デシジョンテーブルの全行）。"""
    for delivery, placement in VALID_CONTEXTS:
        assert CASHLESS <= available_methods(delivery, placement)

