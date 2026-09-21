"""購入手続き（配送方法・支払方法の選択と、確認画面の内容の組み立て）。

設計仕様書 4.3、6.4.2〜6.4.4 に対応する。

確認画面に出す金額と、注文確定で使う金額は、同じ関数（build_draft）から作る。
2か所で別々に計算すると、いつか食い違い、
「確認画面では 3,980円 だったのに請求は 4,378円」が起きる。
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Cart, CartItem, Checkout, Member, Product, Sku
from app.services import payment_policy, pricing
from app.services.errors import CheckoutIncompleteError, ValidationError
from app.services.fingerprint import FingerprintLine, compute_fingerprint

DELIVERY_NAMES = {
    "HOME": "指定住所受取り",
    "STORE_PICKUP": "店舗受取り",
    "NEKOPOSU": "ネコポス",
}

PAYMENT_NAMES = {
    "CREDIT_CARD": "クレジットカード",
    "PAYPAY": "PayPay",
    "D_BARAI": "d払い",
    "DEFERRED": "後払い",
    "COD": "代金引換え",
}

# 設計仕様書 6.4.2。FRONT_DOOR を初期値とする（要件定義書 FR-562-10）
PLACEMENT_NAMES = {
    "FRONT_DOOR": "玄関ドア前",
    "DELIVERY_BOX": "宅配ボックス",
    "METER_BOX": "メーターボックス",
    "GARAGE": "車庫",
    "BICYCLE_BASKET": "自転車のかご",
    "STORAGE": "物置",
    "RECEPTION": "管理人室・受付",
    "NONE": "置き配を利用しない",
}
DEFAULT_PLACEMENT = "FRONT_DOOR"

ALTERATION_NAMES = {
    "SINGLE_FOLD": "シングル",
    "DOUBLE_FOLD": "ダブル",
}


def normalize_placement(placement_type: str | None) -> str | None:
    """"NONE"（置き配を利用しない）を None に揃える。

    API では選択肢の1つとして "NONE" を受け付けるが、
    内部では「置き配の指定が無い」を None の1通りで表す。
    同じ意味に2つの表現があると、判定の条件がどちらかを見落とす。
    """
    if placement_type in (None, "", "NONE"):
        return None
    if placement_type not in PLACEMENT_NAMES:
        raise ValidationError(f"未知の置き配の場所です: {placement_type}")
    return placement_type


# --- 届け先の検証 -------------------------------------------------------

_POSTAL = re.compile(r"^\d{7}$")
_PHONE = re.compile(r"^\d{10,11}$")


@dataclass(frozen=True)
class Recipient:
    name: str
    postal_code: str
    address: str
    phone: str

    def as_tuple(self) -> tuple[str, str, str, str]:
        return (self.name, self.postal_code, self.address, self.phone)


def validate_recipient(name: str, postal_code: str, address: str, phone: str) -> Recipient:
    """届け先を検証し、正規化した値を返す。

    郵便番号と電話番号はハイフンを除いて保持する。
    「070-0031」と「0700031」が別の値として保存されると、
    fingerprint が一致しなくなり、同じ内容の再送が 422 になる。
    """
    name = (name or "").strip()
    address = (address or "").strip()
    postal = (postal_code or "").replace("-", "").replace("－", "").strip()
    tel = (phone or "").replace("-", "").replace("－", "").strip()

    if not name or len(name) > 100:
        raise ValidationError("お名前を100文字以内で入力してください")
    if not _POSTAL.match(postal):
        raise ValidationError("郵便番号は7桁の数字で入力してください")
    if not address or len(address) > 200:
        raise ValidationError("住所を200文字以内で入力してください")
    if not _PHONE.match(tel):
        raise ValidationError("電話番号は10桁または11桁の数字で入力してください")
    return Recipient(name, postal, address, tel)


# --- 選択の保存 ---------------------------------------------------------


def get_or_create_checkout(db: Session, cart: Cart) -> Checkout:
    checkout = db.get(Checkout, cart.cart_id)
    if checkout is None:
        checkout = Checkout(cart_id=cart.cart_id)
        db.add(checkout)
        db.flush()
    return checkout


def set_delivery(
    db: Session,
    cart: Cart,
    delivery_method: str,
    placement_type: str | None,
    recipient: Recipient,
) -> Checkout:
    if delivery_method not in DELIVERY_NAMES:
        raise ValidationError(f"未知の配送方法です: {delivery_method}")
    placement = normalize_placement(placement_type)
    if placement is not None and delivery_method != "HOME":
        raise ValidationError("置き配は指定住所受取りの場合にのみ指定できます")

    checkout = get_or_create_checkout(db, cart)
    checkout.delivery_method = delivery_method
    checkout.placement_type = placement
    checkout.recipient_name = recipient.name
    checkout.recipient_postal_code = recipient.postal_code
    checkout.recipient_address = recipient.address
    checkout.recipient_phone = recipient.phone

    # 配送方法を変えたことで、選択済みの支払方法が使えなくなる場合がある。
    # 黙って残すと、確認画面まで進んでから「その支払方法は使えません」になる。
    # その場で選択を外し、選び直してもらう。
    if checkout.payment_method is not None:
        if payment_policy.reason_for(checkout.payment_method, delivery_method, placement):
            checkout.payment_method = None
    return checkout


def set_payment(db: Session, cart: Cart, payment_method: str) -> Checkout:
    checkout = db.get(Checkout, cart.cart_id)
    if checkout is None or checkout.delivery_method is None:
        raise CheckoutIncompleteError("先に配送方法を選択してください")
    if payment_method not in PAYMENT_NAMES:
        raise ValidationError(f"未知の支払方法です: {payment_method}")

    # 可否の判定は Backend で行う（設計仕様書 4.3.2）。
    # Frontend が選択肢を無効化していても、API を直接叩けば送れる。
    reason = payment_policy.reason_for(
        payment_method, checkout.delivery_method, checkout.placement_type
    )
    if reason is not None:
        raise ValidationError(reason.message)

    checkout.payment_method = payment_method
    return checkout


# --- 注文内容の組み立て -------------------------------------------------


@dataclass(frozen=True)
class DraftLine:
    cart_item_id: int
    sku_id: str
    product_name: str
    color_name: str
    size: str
    unit_price: int
    price_type: str
    quantity: int
    alteration_type: str | None
    alteration_length_mm: int | None
    alteration_fee: int | None  # 1点あたり
    is_returnable: bool


@dataclass(frozen=True)
class OrderDraft:
    member_id: int
    lines: list[DraftLine]
    amounts: pricing.OrderAmount
    delivery_method: str
    placement_type: str | None
    recipient: Recipient
    payment_method: str
    fingerprint: str
    notices: list[dict]


def build_draft(db: Session, member: Member, cart: Cart, now: dt.datetime) -> OrderDraft:
    """カートと購入手続きの選択から、注文の内容を組み立てる。

    確認画面（GET /api/checkout/summary）と注文確定（POST /api/orders）の
    両方がこの関数を使う。
    """
    items = list(
        db.execute(
            select(CartItem).where(CartItem.cart_id == cart.cart_id).order_by(CartItem.cart_item_id)
        ).scalars()
    )
    if not items:
        raise CheckoutIncompleteError("カートに商品がありません")

    checkout = db.get(Checkout, cart.cart_id)
    if checkout is None or checkout.delivery_method is None:
        raise CheckoutIncompleteError("配送方法が選択されていません")
    if checkout.payment_method is None:
        raise CheckoutIncompleteError("支払方法が選択されていません")

    lines: list[DraftLine] = []
    line_items: list[pricing.LineItem] = []
    for item in items:
        sku = db.get(Sku, item.sku_id)
        product = db.get(Product, sku.product_id)
        unit_price, price_type = pricing.resolve_unit_price(
            regular_price=product.regular_price,
            member_price=product.member_price,
            member_price_from=product.member_price_from,
            member_price_to=product.member_price_to,
            now=now,
            is_member=True,  # 注文確定はログインが前提
        )
        fee = pricing.resolve_alteration_fee(item.alteration_type) if item.alteration_type else None
        lines.append(
            DraftLine(
                cart_item_id=item.cart_item_id,
                sku_id=item.sku_id,
                product_name=product.name,
                color_name=sku.color_name,
                size=sku.size,
                unit_price=unit_price,
                price_type=price_type,
                quantity=item.quantity,
                alteration_type=item.alteration_type,
                alteration_length_mm=item.alteration_length_mm,
                alteration_fee=fee,
                # すそ上げ加工品は返品できない（要件定義書 5.6.4.1）
                is_returnable=item.alteration_type is None,
            )
        )
        line_items.append(pricing.LineItem(unit_price, item.quantity, item.alteration_type))

    amounts = pricing.calc_order_amount(
        items=line_items,
        delivery_method=checkout.delivery_method,
        payment_method=checkout.payment_method,
    )

    recipient = Recipient(
        checkout.recipient_name or "",
        checkout.recipient_postal_code or "",
        checkout.recipient_address or "",
        checkout.recipient_phone or "",
    )

    fingerprint = compute_fingerprint(
        member_id=member.member_id,
        lines=[
            FingerprintLine(l.sku_id, l.quantity, l.alteration_type, l.alteration_length_mm)
            for l in lines
        ],
        delivery_method=checkout.delivery_method,
        placement_type=checkout.placement_type,
        recipient=recipient.as_tuple(),
        payment_method=checkout.payment_method,
        amounts=(
            amounts.subtotal,
            amounts.alteration_fee,
            amounts.shipping_fee,
            amounts.payment_fee,
            amounts.tax,
            amounts.total,
        ),
    )

    # 表示義務（DS-625、DS-626）。判定は Backend が行い、Frontend は表示するだけ
    notices = []
    if any(not l.is_returnable for l in lines):
        notices.append(
            {
                "code": "ALTERATION_NOT_RETURNABLE",
                "message": "すそ上げ加工をした商品は、交換・返品ができません",
            }
        )
    if checkout.placement_type is not None:
        notices.append(
            {
                "code": "PLACEMENT_RESPONSIBILITY",
                "message": "置き配を指定した場合、指定場所へのお届け完了後の紛失・盗難について当社は責任を負いません",
            }
        )

    return OrderDraft(
        member_id=member.member_id,
        lines=lines,
        amounts=amounts,
        delivery_method=checkout.delivery_method,
        placement_type=checkout.placement_type,
        recipient=recipient,
        payment_method=checkout.payment_method,
        fingerprint=fingerprint,
        notices=notices,
    )
