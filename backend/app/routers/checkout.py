"""購入手続きAPI。設計仕様書 6.4.2〜6.4.4 に対応する。すべてログインが必要。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_member
from app.models import CartItem, Member
from app.schemas import (
    AmountsView,
    CheckoutOptionsResponse,
    CheckoutSummaryResponse,
    DeliveryMethodOption,
    DeliveryView,
    Notice,
    PaymentMethodOption,
    PaymentView,
    PlacementTypeOption,
    RecipientView,
    SelectDeliveryRequest,
    SelectDeliveryResponse,
    SelectPaymentRequest,
    SelectPaymentResponse,
    SummaryAlteration,
    SummaryItem,
    UnavailableReasonView,
)
from app.services import checkout_service, payment_policy, pricing
from app.services.availability import get_db_now
from app.services.cart_service import get_or_create_cart

router = APIRouter(prefix="/api/checkout", tags=["checkout"])

# 支払方法が選べない理由のコード（設計仕様書 6.4.3 の応答例）
_REASON_CODES = {
    payment_policy.CAUSED_BY_PLACEMENT: "PLACEMENT_SPECIFIED",
    payment_policy.CAUSED_BY_DELIVERY: "DELIVERY_METHOD_RESTRICTED",
}


def _payment_options(delivery_method: str, placement_type: str | None) -> list[PaymentMethodOption]:
    options = []
    for opt in payment_policy.evaluate(delivery_method, placement_type):
        reason = None
        if opt.reason is not None:
            reason = UnavailableReasonView(
                code=_REASON_CODES[opt.reason.caused_by],
                message=opt.reason.message,
                causedBy=opt.reason.caused_by,
            )
        options.append(
            PaymentMethodOption(
                code=opt.code,
                name=checkout_service.PAYMENT_NAMES[opt.code],
                # 手数料は選択前に示す（要件定義書 FR-563-02）
                fee=pricing.resolve_payment_fee(opt.code),
                feeTaxIncluded=pricing.tax_included_unit_price(pricing.resolve_payment_fee(opt.code)),
                available=opt.available,
                unavailableReason=reason,
            )
        )
    return options


@router.get("/options", response_model=CheckoutOptionsResponse)
def get_options(
    db: Session = Depends(get_db), member: Member = Depends(require_member)
) -> CheckoutOptionsResponse:
    cart, _ = get_or_create_cart(db, member, None)
    db.commit()

    # 送料はカートの商品合計で決まるので、いまのカートで算出して示す
    now = get_db_now(db)
    subtotal = 0
    for item in db.execute(select(CartItem).where(CartItem.cart_id == cart.cart_id)).scalars():
        product = item.sku.product
        price, _ = pricing.resolve_unit_price(
            regular_price=product.regular_price,
            member_price=product.member_price,
            member_price_from=product.member_price_from,
            member_price_to=product.member_price_to,
            now=now,
            is_member=True,
        )
        subtotal += price * item.quantity

    # 商品属性による配送方法の制約（ネコポスの寸法など。要件定義書 5.10.2.2）は
    # ①では扱わない。すべて選択可能として返す
    methods = [
        DeliveryMethodOption(
            code=code,
            name=name,
            fee=pricing.resolve_shipping_fee(code, subtotal),
            feeTaxIncluded=pricing.tax_included_unit_price(pricing.resolve_shipping_fee(code, subtotal)),
            available=True,
            unavailableReason=None,
        )
        for code, name in checkout_service.DELIVERY_NAMES.items()
    ]
    placements = [
        PlacementTypeOption(code=code, name=name, isDefault=code == checkout_service.DEFAULT_PLACEMENT)
        for code, name in checkout_service.PLACEMENT_NAMES.items()
    ]
    return CheckoutOptionsResponse(deliveryMethods=methods, placementTypes=placements)


@router.post("/delivery", response_model=SelectDeliveryResponse)
def select_delivery(
    body: SelectDeliveryRequest,
    db: Session = Depends(get_db),
    member: Member = Depends(require_member),
) -> SelectDeliveryResponse:
    try:
        cart, _ = get_or_create_cart(db, member, None)
        recipient = checkout_service.validate_recipient(
            body.recipient.name,
            body.recipient.postal_code,
            body.recipient.address,
            body.recipient.phone,
        )
        checkout = checkout_service.set_delivery(
            db, cart, body.delivery_method, body.placement_type, recipient
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return SelectDeliveryResponse(
        paymentMethods=_payment_options(checkout.delivery_method, checkout.placement_type)
    )


@router.post("/payment", response_model=SelectPaymentResponse)
def select_payment(
    body: SelectPaymentRequest,
    db: Session = Depends(get_db),
    member: Member = Depends(require_member),
) -> SelectPaymentResponse:
    try:
        cart, _ = get_or_create_cart(db, member, None)
        checkout = checkout_service.set_payment(db, cart, body.payment_method)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return SelectPaymentResponse(
        paymentMethod=checkout.payment_method,
        fee=pricing.resolve_payment_fee(checkout.payment_method),
    )


@router.get("/summary", response_model=CheckoutSummaryResponse)
def get_summary(
    db: Session = Depends(get_db), member: Member = Depends(require_member)
) -> CheckoutSummaryResponse:
    cart, _ = get_or_create_cart(db, member, None)
    db.commit()
    draft = checkout_service.build_draft(db, member, cart, get_db_now(db))

    items = [
        SummaryItem(
            skuId=l.sku_id,
            productName=l.product_name,
            colorName=l.color_name,
            size=l.size,
            unitPrice=l.unit_price,
            priceType=l.price_type,
            quantity=l.quantity,
            subtotal=l.unit_price * l.quantity,
            alteration=(
                SummaryAlteration(
                    typeName=checkout_service.ALTERATION_NAMES[l.alteration_type],
                    lengthMm=l.alteration_length_mm,
                    fee=l.alteration_fee,
                )
                if l.alteration_type
                else None
            ),
            isReturnable=l.is_returnable,
        )
        for l in draft.lines
    ]
    a = draft.amounts
    return CheckoutSummaryResponse(
        items=items,
        # DS-624: 総額だけでなく内訳を返す
        amounts=AmountsView(
            subtotal=a.subtotal,
            alterationFee=a.alteration_fee,
            shippingFee=a.shipping_fee,
            paymentFee=a.payment_fee,
            tax=a.tax,
            total=a.total,
        ),
        delivery=DeliveryView(
            method=draft.delivery_method,
            methodName=checkout_service.DELIVERY_NAMES[draft.delivery_method],
            placementType=draft.placement_type,
            recipient=RecipientView(
                name=draft.recipient.name,
                postalCode=draft.recipient.postal_code,
                address=draft.recipient.address,
                phone=draft.recipient.phone,
            ),
        ),
        payment=PaymentView(
            method=draft.payment_method,
            methodName=checkout_service.PAYMENT_NAMES[draft.payment_method],
        ),
        notices=[Notice(**n) for n in draft.notices],
        # DS-627: 冪等キーはここで発行する。注文確定の要求にこれを付けてもらう
        idempotencyKey=uuid.uuid4().hex,
    )
