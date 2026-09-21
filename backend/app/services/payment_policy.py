"""支払方法の選択可否。

要件定義書 5.10.2.1、設計仕様書 DS-623、テスト仕様書 4.5 に対応する。

配送方法と置き配の指定によって、選べない支払方法がある。
重要なのは「選べない」ことだけでなく「なぜ選べないか」を、
顧客が変更できる選択肢のどれが原因かまで特定して返すことである（FR-5A-02）。
「この支払方法は利用できません」とだけ言われても、顧客は何を変えれば
選べるようになるのか分からない。

    指定住所 × 置き配あり × 代引 → 原因は置き配（置き配をやめれば選べる）
    店舗受取り × 後払い         → 原因は配送方法（配送方法を変えれば選べる）
"""

from __future__ import annotations

from dataclasses import dataclass

DELIVERY_HOME = "HOME"
DELIVERY_STORE_PICKUP = "STORE_PICKUP"
DELIVERY_NEKOPOSU = "NEKOPOSU"
DELIVERY_METHODS = (DELIVERY_HOME, DELIVERY_STORE_PICKUP, DELIVERY_NEKOPOSU)

PAYMENT_METHODS = ("CREDIT_CARD", "PAYPAY", "D_BARAI", "DEFERRED", "COD")

CAUSED_BY_DELIVERY = "deliveryMethod"
CAUSED_BY_PLACEMENT = "placementType"

_DELIVERY_NAMES = {
    DELIVERY_HOME: "指定住所受取り",
    DELIVERY_STORE_PICKUP: "店舗受取り",
    DELIVERY_NEKOPOSU: "ネコポス",
}


@dataclass(frozen=True)
class UnavailableReason:
    caused_by: str  # "deliveryMethod" または "placementType"
    message: str


@dataclass(frozen=True)
class PaymentOption:
    code: str
    available: bool
    reason: UnavailableReason | None


def _validate(delivery_method: str | None, placement_type: str | None) -> None:
    """【未確定8】未定義の値は例外とする（暫定）。

    安全側に倒して「全部不可」を返す案もあるが、そうすると
    呼び出し側の誤りが「支払方法が1つも選べない画面」として顧客に現れ、
    原因の特定が遅れる。入力の誤りは入力の誤りとして早く落とす。
    """
    if delivery_method is None:
        raise ValueError("配送方法が指定されていません")
    if delivery_method not in DELIVERY_METHODS:
        raise ValueError(f"未知の配送方法です: {delivery_method}")
    if placement_type is not None and delivery_method != DELIVERY_HOME:
        # 置き配は指定住所受取りでのみ意味を持つ（TC-UT-PM-31）
        raise ValueError("置き配は指定住所受取りの場合にのみ指定できます")


def reason_for(
    payment_method: str, delivery_method: str | None, placement_type: str | None
) -> UnavailableReason | None:
    """選択できない理由を返す。選択できる場合は None。

    可否の判定と理由の有無をこの1つの関数に集約する。
    可否を返す関数と理由を返す関数を別々に書くと、両者の条件が
    いつかずれて「選べるのに理由が出る」「選べないのに理由が出ない」
    状態が生まれる（TC-UT-PM-13、14）。
    """
    _validate(delivery_method, placement_type)
    if payment_method not in PAYMENT_METHODS:
        raise ValueError(f"未知の支払方法です: {payment_method}")

    if payment_method == "DEFERRED":
        # 後払いは、受取人の確認を伴わない受取方法では請求先の特定に支障が出る
        if delivery_method != DELIVERY_HOME:
            return UnavailableReason(
                caused_by=CAUSED_BY_DELIVERY,
                message=f"{_DELIVERY_NAMES[delivery_method]}を選択した場合、後払いは利用できません",
            )
        if placement_type is not None:
            return UnavailableReason(
                caused_by=CAUSED_BY_PLACEMENT,
                message="置き配を指定した場合、後払いは利用できません",
            )

    if payment_method == "COD":
        # 代金引換えは、商品の引渡しと代金の受領が同時に行われることを前提とする。
        # 店舗受取り・ネコポスでの不可は要件定義書で【推論】とされている（TC-UT-PM-05、06）。
        # 観察で確認できていないが、選べないはずの方法を選べてしまうより、
        # 選べるはずの方法が選べないほうが被害は小さい。暫定的に不可とする。
        if delivery_method != DELIVERY_HOME:
            return UnavailableReason(
                caused_by=CAUSED_BY_DELIVERY,
                message=f"{_DELIVERY_NAMES[delivery_method]}を選択した場合、代金引換えは利用できません",
            )
        if placement_type is not None:
            return UnavailableReason(
                caused_by=CAUSED_BY_PLACEMENT,
                message="置き配を指定した場合、代金引換えは利用できません",
            )

    return None


def evaluate(delivery_method: str | None, placement_type: str | None) -> list[PaymentOption]:
    """すべての支払方法について、可否と理由を返す。"""
    options = []
    for code in PAYMENT_METHODS:
        reason = reason_for(code, delivery_method, placement_type)
        options.append(PaymentOption(code=code, available=reason is None, reason=reason))
    return options


def available_methods(delivery_method: str | None, placement_type: str | None) -> set[str]:
    return {o.code for o in evaluate(delivery_method, placement_type) if o.available}
