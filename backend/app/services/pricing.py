"""金額計算。

ここは DB にもネットワークにも触れない純粋な計算だけを置く。
設計仕様書の DS-391〜393（端数処理）と、テスト仕様書 4.3 PriceCalculator の
単体テスト対象がこのモジュールである。

金額はすべて円単位の int で扱う。float は使わない（設計仕様書 7章）。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal

# --- 定数 -------------------------------------------------------------
# いずれも事業判断により変わりうるため、定数として一箇所に集約する。
# 注文時点の値は orders / order_item にコピーして保持する（DS-390台）。

TAX_RATE = Decimal("0.10")  # 衣料品は軽減税率の対象外

FREE_SHIPPING_THRESHOLD_EX_TAX = 5000  # 税抜5,000円以上で送料無料

SHIPPING_FEES_EX_TAX: dict[str, int] = {
    "HOME": 500,  # 指定住所受取り
    "NEKOPOSU": 200,  # ネコポス
    "STORE_PICKUP": 0,  # 店舗受取り
}

PAYMENT_FEES_EX_TAX: dict[str, int] = {
    "CREDIT_CARD": 0,
    "PAYPAY": 0,
    "D_BARAI": 0,
    "DEFERRED": 250,  # 後払い
    "COD": 330,  # 代金引換え
}

# すそ上げ加工料（税抜）。設計仕様書 3.1 によりマスタ化せず定数で保持する。
ALTERATION_FEES_EX_TAX: dict[str, int] = {
    "SINGLE_FOLD": 300,  # シングル
    "DOUBLE_FOLD": 560,  # ダブル
}

PRICE_TYPE_REGULAR = "REGULAR"
PRICE_TYPE_MEMBER = "MEMBER"


# --- 会員価格の適用判定 -------------------------------------------------


def resolve_unit_price(
    *,
    regular_price: int,
    member_price: int | None,
    member_price_from: dt.datetime | None,
    member_price_to: dt.datetime | None,
    now: dt.datetime,
    is_member: bool,
) -> tuple[int, str]:
    """適用する単価と、その種別を返す。

    会員価格は「会員であること」と「期間内であること」の両方を満たす場合にのみ
    適用する。期間の片方だけが設定されている場合は、設定されていない側を
    無制限として扱う。

    now を引数で受け取るのは、テストから時刻を固定できるようにするためである
    （テスト仕様書 8.4.3 TE-01）。モジュール内で datetime.now() を呼ぶと
    期間の境界値をテストできない。
    """
    if not is_member or member_price is None:
        return regular_price, PRICE_TYPE_REGULAR

    if member_price_from is not None and now < member_price_from:
        return regular_price, PRICE_TYPE_REGULAR
    if member_price_to is not None and now > member_price_to:
        return regular_price, PRICE_TYPE_REGULAR

    return member_price, PRICE_TYPE_MEMBER


# --- 送料・手数料・加工料 -----------------------------------------------


def resolve_shipping_fee(delivery_method: str, subtotal_ex_tax: int) -> int:
    """送料（税抜）を返す。

    基準額の判定は税抜の商品合計で行う。加工料や手数料は含めない。
    """
    if delivery_method not in SHIPPING_FEES_EX_TAX:
        raise ValueError(f"未知の配送方法です: {delivery_method}")
    if subtotal_ex_tax >= FREE_SHIPPING_THRESHOLD_EX_TAX:
        return 0
    return SHIPPING_FEES_EX_TAX[delivery_method]


def resolve_payment_fee(payment_method: str) -> int:
    """支払手数料（税抜）を返す。"""
    if payment_method not in PAYMENT_FEES_EX_TAX:
        raise ValueError(f"未知の支払方法です: {payment_method}")
    return PAYMENT_FEES_EX_TAX[payment_method]


def resolve_alteration_fee(alteration_type: str | None) -> int:
    """すそ上げ加工料（税抜、1点あたり）を返す。指定がなければ 0。"""
    if alteration_type is None:
        return 0
    if alteration_type not in ALTERATION_FEES_EX_TAX:
        raise ValueError(f"未知の加工方法です: {alteration_type}")
    fee = ALTERATION_FEES_EX_TAX[alteration_type]
    if fee < 0:
        # 定数の設定誤り。入力では起きないが、起きれば総額を不正に下げる（TC-UT-PC-44）
        raise ValueError(f"加工料が負に設定されています: {alteration_type}={fee}")
    return fee


# --- 合計の算出 ---------------------------------------------------------


@dataclass(frozen=True)
class LineItem:
    """金額計算に必要な明細の情報だけを持つ値オブジェクト。"""

    unit_price_ex_tax: int
    quantity: int
    alteration_type: str | None = None

    def __post_init__(self) -> None:
        # DS-571: 負の単価・数量は、総額を引き下げる方向の改ざんになりうる。
        # 総額が負の注文は、決済において「返金」を意味する（TC-UT-PC-42、43）。
        if self.unit_price_ex_tax < 0:
            raise ValueError(f"単価が負です: {self.unit_price_ex_tax}")
        if self.quantity < 1:
            raise ValueError(f"数量は1以上である必要があります: {self.quantity}")

    @property
    def goods_amount(self) -> int:
        return self.unit_price_ex_tax * self.quantity

    @property
    def alteration_amount(self) -> int:
        # 加工料は点数ぶん発生する
        return resolve_alteration_fee(self.alteration_type) * self.quantity


@dataclass(frozen=True)
class OrderAmount:
    subtotal: int  # 商品合計（税抜）
    alteration_fee: int  # 加工料の合計（税抜）
    shipping_fee: int  # 送料（税抜）
    payment_fee: int  # 支払手数料（税抜）
    tax: int  # 消費税
    total: int  # 総額（税込）


def calc_tax(taxable_ex_tax: int) -> int:
    """消費税額を返す。

    DS-392: 1円未満を切り捨てる。
    DS-393: 端数処理は注文単位で1回だけ行う。明細ごとには行わない。

    Decimal を使うのは、float の 0.1 が正確に 0.1 ではないためである。
    たとえば 4999 * 0.1 は float では 499.90000000000003 になり、
    切り捨ての境界で 1 円ずれうる。
    """
    if taxable_ex_tax < 0:
        raise ValueError("課税対象額が負です")
    return int((Decimal(taxable_ex_tax) * TAX_RATE).to_integral_value(rounding=ROUND_FLOOR))


def calc_order_amount(
    *,
    items: list[LineItem],
    delivery_method: str,
    payment_method: str,
) -> OrderAmount:
    """注文金額の内訳を算出する。

    消費税は、商品・加工料・送料・手数料をすべて足した税抜合計に対して
    1回だけ乗じる（DS-391）。明細ごとに税を出して足し上げると、
    明細数によって総額が変わってしまう。
    """
    if not items:
        raise ValueError("明細が空です")

    subtotal = sum(item.goods_amount for item in items)
    alteration_fee = sum(item.alteration_amount for item in items)
    shipping_fee = resolve_shipping_fee(delivery_method, subtotal)
    payment_fee = resolve_payment_fee(payment_method)

    taxable = subtotal + alteration_fee + shipping_fee + payment_fee
    tax = calc_tax(taxable)

    # TC-UT-PC-45: 総額が0以下の注文は成立させない。
    # 各項目が非負でも、単価0円の商品だけを店舗受取り・カード払いで
    # 注文すると0円になる。0円の決済要求は PSP 側で弾かれるか、
    # 最悪の場合「決済済み」として素通りし、商品だけが出荷される。
    if taxable + tax <= 0:
        raise ValueError("総額が0円以下の注文は受け付けられません")

    return OrderAmount(
        subtotal=subtotal,
        alteration_fee=alteration_fee,
        shipping_fee=shipping_fee,
        payment_fee=payment_fee,
        tax=tax,
        total=taxable + tax,
    )
