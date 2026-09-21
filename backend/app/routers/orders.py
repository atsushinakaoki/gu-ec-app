"""注文API。設計仕様書 6.4.5 に対応する。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db, to_utc_iso
from app.deps import require_member
from app.models import Member, Order, OrderItem
from app.schemas import (
    AmountsView,
    CreateOrderRequest,
    CreateOrderResponse,
    OrderDetailResponse,
    OrderItemView,
)
from app.services import order_service

router = APIRouter(prefix="/api/orders", tags=["orders"])


def _amounts(order: Order) -> AmountsView:
    return AmountsView(
        subtotal=order.subtotal,
        alterationFee=order.alteration_fee,
        shippingFee=order.shipping_fee,
        paymentFee=order.payment_fee,
        tax=order.tax,
        total=order.total,
    )


@router.post(
    "",
    response_model=CreateOrderResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        202: {"description": "決済の結果が未確定（処理中）"},
        402: {"description": "決済が否決された"},
        409: {"description": "在庫不足、または同じ注文が処理中"},
        422: {"description": "金額の不一致、または冪等キーの内容不一致"},
    },
)
def create_order(
    body: CreateOrderRequest,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    member: Member = Depends(require_member),
) -> CreateOrderResponse:
    outcome = order_service.create_order(db, member, idempotency_key, body.expected_total)
    order = outcome.order

    if outcome.status == order_service.STATUS_PENDING:
        # DS-451: 失敗ではなく処理中として返す
        response.status_code = status.HTTP_202_ACCEPTED
        message = "決済の確認に時間がかかっています。注文状況は後ほどご確認ください"
    else:
        message = None

    return CreateOrderResponse(
        orderNumber=order.order_number,
        orderedAt=to_utc_iso(order.ordered_at),
        status=outcome.status,
        amounts=_amounts(order),
        message=message,
    )


@router.get("/{order_number}", response_model=OrderDetailResponse)
def get_order(
    order_number: str,
    db: Session = Depends(get_db),
    member: Member = Depends(require_member),
) -> OrderDetailResponse:
    order = order_service.get_order(db, member, order_number)
    items = db.execute(
        select(OrderItem).where(OrderItem.order_id == order.order_id).order_by(OrderItem.order_item_id)
    ).scalars()
    return OrderDetailResponse(
        orderNumber=order.order_number,
        orderedAt=to_utc_iso(order.ordered_at),
        status=order.status,
        amounts=_amounts(order),
        items=[
            OrderItemView(
                skuId=i.sku_id,
                productName=i.product_name,
                colorName=i.color_name,
                size=i.size,
                unitPrice=i.unit_price,
                quantity=i.quantity,
                alterationType=i.alteration_type,
                alterationLengthMm=i.alteration_length_mm,
                isReturnable=i.is_returnable,
            )
            for i in items
        ],
        deliveryMethod=order.delivery_method,
        paymentMethod=order.payment_method,
    )
