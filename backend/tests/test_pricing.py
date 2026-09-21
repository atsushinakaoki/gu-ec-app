"""テスト仕様書 4.4 PriceCalculator（送料・手数料・消費税・会員価格）"""

import datetime as dt

import pytest

from app.services import pricing
from app.services.pricing import LineItem, calc_order_amount, calc_tax

# --- 4.4.2 送料の境界値 -------------------------------------------------


@pytest.mark.parametrize(
    "method, subtotal, expected",
    [
        pytest.param("HOME", 4999, 500, id="TC-UT-PC-01_4999円_指定住所"),
        pytest.param("HOME", 5000, 0, id="TC-UT-PC-02_5000円ちょうど_指定住所"),
        pytest.param("HOME", 5001, 0, id="TC-UT-PC-03_5001円_指定住所"),
        pytest.param("NEKOPOSU", 4999, 200, id="TC-UT-PC-04_4999円_ネコポス"),
        pytest.param("NEKOPOSU", 5000, 0, id="TC-UT-PC-05_5000円_ネコポス"),
        pytest.param("STORE_PICKUP", 1, 0, id="TC-UT-PC-06_1円_店舗受取り"),
        pytest.param("STORE_PICKUP", 100000, 0, id="TC-UT-PC-07_10万円_店舗受取り"),
    ],
)
def test_shipping_fee(method, subtotal, expected):
    assert pricing.resolve_shipping_fee(method, subtotal) == expected


@pytest.mark.parametrize(
    "unit_price, expected_shipping",
    [
        # 加工料を含めれば5,100円だが、判定は商品合計のみで行う
        pytest.param(4800, 500, id="TC-UT-PC-08_商品4800円+加工料300円"),
        pytest.param(5000, 0, id="TC-UT-PC-09_商品5000円+加工料300円"),
    ],
)
def test_shipping_threshold_excludes_alteration_fee(unit_price, expected_shipping):
    amount = calc_order_amount(
        items=[LineItem(unit_price, 1, "SINGLE_FOLD")],
        delivery_method="HOME",
        payment_method="CREDIT_CARD",
    )
    assert amount.shipping_fee == expected_shipping


# --- 4.4.3 支払手数料 ---------------------------------------------------


@pytest.mark.parametrize(
    "method, expected",
    [
        pytest.param("CREDIT_CARD", 0, id="TC-UT-PC-10_クレジットカード"),
        pytest.param("PAYPAY", 0, id="TC-UT-PC-11_PayPay"),
        pytest.param("D_BARAI", 0, id="TC-UT-PC-12_d払い"),
        pytest.param("DEFERRED", 250, id="TC-UT-PC-13_後払い"),
        pytest.param("COD", 330, id="TC-UT-PC-14_代金引換え"),
    ],
)
def test_payment_fee(method, expected):
    assert pricing.resolve_payment_fee(method) == expected


# --- 4.4.4 消費税の算出 -------------------------------------------------


@pytest.mark.parametrize(
    "taxable, expected",
    [
        pytest.param(1000, 100, id="TC-UT-PC-20_1000円"),
        pytest.param(1999, 199, id="TC-UT-PC-21_1999円_199.9を切捨て"),
        pytest.param(1995, 199, id="TC-UT-PC-22_1995円_199.5を切捨て"),
        pytest.param(1990, 199, id="TC-UT-PC-23_1990円_ちょうど"),
        pytest.param(9, 0, id="TC-UT-PC-24_9円_0.9を切捨て"),
        pytest.param(10, 1, id="TC-UT-PC-25_10円"),
    ],
)
def test_tax(taxable, expected):
    assert calc_tax(taxable) == expected


@pytest.mark.parametrize(
    "items",
    [
        pytest.param([LineItem(1999, 2)], id="TC-UT-PC-26a_1明細x数量2"),
        # 1明細・数量2 だけでは、明細ごとに丸める実装でも 3998 → 399 となり区別できない。
        # 別明細に分けて初めて、明細ごとの端数処理（199 + 199 = 398）が露見する。
        # 変異テストでこの見逃しを検出したため追加した。
        pytest.param([LineItem(1999, 1), LineItem(1999, 1)], id="TC-UT-PC-26b_2明細x数量1"),
    ],
)
def test_TC_UT_PC_26_tax_is_rounded_once_per_order(items):
    """明細ごとに端数処理すると 199 × 2 = 398 になる。注文単位では 3998 × 0.1 = 399（DS-393）。"""
    amount = calc_order_amount(
        items=items,
        delivery_method="STORE_PICKUP",
        payment_method="PAYPAY",
    )
    assert amount.tax == 399


# --- 4.4.5 会員価格 -----------------------------------------------------

FROM = dt.datetime(2026, 9, 1, 0, 0, 0)
TO = dt.datetime(2026, 9, 30, 23, 59, 59)


def resolve(now, member_price=1990, is_member=True):
    return pricing.resolve_unit_price(
        regular_price=2490,
        member_price=member_price,
        member_price_from=FROM,
        member_price_to=TO,
        now=now,
        is_member=is_member,
    )


def test_TC_UT_PC_30_member_price_applied_within_period():
    assert resolve(dt.datetime(2026, 9, 15)) == (1990, "MEMBER")


def test_TC_UT_PC_31_no_member_price_set():
    assert resolve(dt.datetime(2026, 9, 15), member_price=None) == (2490, "REGULAR")


@pytest.mark.skip(reason="【未確定6】適用開始時刻ちょうど。実装は会員価格を適用する（開始時刻を含む）")
def test_TC_UT_PC_32_at_start():
    pass


@pytest.mark.skip(reason="【未確定6】適用終了時刻ちょうど。実装は会員価格を適用する（終了時刻を含む）")
def test_TC_UT_PC_33_at_end():
    pass


def test_TC_UT_PC_34_one_second_before_start():
    assert resolve(FROM - dt.timedelta(seconds=1)) == (2490, "REGULAR")


def test_TC_UT_PC_35_one_second_after_end():
    assert resolve(TO + dt.timedelta(seconds=1)) == (2490, "REGULAR")


def test_member_price_not_applied_when_logged_out():
    """期間内でも、未ログインなら通常売価（テスト仕様書に ID なし。実装の前提の確認）"""
    assert resolve(dt.datetime(2026, 9, 15), is_member=False) == (2490, "REGULAR")


# --- 4.4.6 複数明細および異常系 -----------------------------------------


def test_TC_UT_PC_40_multiple_lines_with_alteration():
    amount = calc_order_amount(
        items=[
            LineItem(1990, 2),  # 3,980
            LineItem(2490, 1, "SINGLE_FOLD"),  # 2,490 + 加工料 300
            LineItem(990, 1),  # 990
        ],
        delivery_method="HOME",
        payment_method="CREDIT_CARD",
    )
    assert amount.subtotal == 7460
    assert amount.alteration_fee == 300
    assert amount.shipping_fee == 0  # 7,460 >= 5,000
    assert amount.payment_fee == 0
    assert amount.tax == 776  # 7,760 × 0.1
    assert amount.total == 8536


@pytest.mark.skip(reason="【未確定7】明細0件。実装は ValueError を投げる")
def test_TC_UT_PC_41_no_items():
    pass


def test_TC_UT_PC_42_negative_unit_price():
    with pytest.raises(ValueError):
        LineItem(-100, 1)


def test_TC_UT_PC_43_negative_quantity():
    with pytest.raises(ValueError):
        LineItem(1000, -1)


def test_TC_UT_PC_44_negative_alteration_fee(monkeypatch):
    """加工料は定数だが、設定を誤って負にした場合も総額を下げさせない。"""
    monkeypatch.setitem(pricing.ALTERATION_FEES_EX_TAX, "SINGLE_FOLD", -300)
    with pytest.raises(ValueError):
        calc_order_amount(
            items=[LineItem(1000, 1, "SINGLE_FOLD")],
            delivery_method="STORE_PICKUP",
            payment_method="CREDIT_CARD",
        )


def test_TC_UT_PC_45_total_zero_or_less():
    with pytest.raises(ValueError):
        calc_order_amount(
            items=[LineItem(0, 1)],
            delivery_method="STORE_PICKUP",
            payment_method="CREDIT_CARD",
        )
