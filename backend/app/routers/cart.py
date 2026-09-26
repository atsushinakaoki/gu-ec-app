"""カートAPI。設計仕様書 6.4.1 に対応する。

トランザクションの境界をこの層で持つ。
services 側はコミットせず、ここで commit / rollback を決める。
"""

from __future__ import annotations

from fastapi import APIRouter, Cookie, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db, to_utc_iso
from app.deps import get_optional_member, require_member
from app.models import CartItem, Member, Product, Reservation, Sku
from app.schemas import (
    AddCartItemRequest,
    AddCartItemResponse,
    AlterationDetail,
    CartAmountView,
    CartItemView,
    CartResponse,
    DiscardedLineView,
    MergeCartResponse,
    ReservationInfo,
)
from app.services import cart_service, pricing
from app.services.availability import get_db_now
from app.services.errors import NotFoundError
from app.services.reservation import ReservationState

router = APIRouter(prefix="/api/cart", tags=["cart"])

CART_SESSION_COOKIE = "gu_cart_session"


def _set_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        key=CART_SESSION_COOKIE,
        value=session_id,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 14,  # 14日
        # secure=True は HTTPS でのみ送られる。ローカル開発は http のため外す。
        # 本番では必ず有効にすること。
    )


@router.post("/items", response_model=AddCartItemResponse, status_code=status.HTTP_201_CREATED)
def add_cart_item(
    body: AddCartItemRequest,
    response: Response,
    db: Session = Depends(get_db),
    member: Member | None = Depends(get_optional_member),
    gu_cart_session: str | None = Cookie(default=None, alias=CART_SESSION_COOKIE),
) -> AddCartItemResponse:
    cart, new_session_id = cart_service.get_or_create_cart(db, member, gu_cart_session)

    try:
        item, expires_at = cart_service.add_item(
            db,
            cart,
            sku_id=body.sku_id,
            quantity=body.quantity,
            alteration_type=body.alteration.type if body.alteration else None,
            alteration_length_mm=body.alteration.length_mm if body.alteration else None,
        )
        db.commit()
    except Exception:
        # 在庫不足でも入力エラーでも、引当とカート明細をまとめて巻き戻す。
        # 片方だけ残ると、誰のカートにも入っていない引当が在庫を押さえ続ける。
        db.rollback()
        raise

    if new_session_id:
        _set_session_cookie(response, new_session_id)

    alteration = None
    if item.alteration_type:
        alteration = AlterationDetail(
            type=item.alteration_type,
            lengthMm=item.alteration_length_mm,
            fee=pricing.resolve_alteration_fee(item.alteration_type),
            feeTaxIncluded=pricing.tax_included_unit_price(
                pricing.resolve_alteration_fee(item.alteration_type)
            ),
        )

    return AddCartItemResponse(
        cartItemId=item.cart_item_id,
        skuId=item.sku_id,
        quantity=item.quantity,
        alteration=alteration,
        reservation=ReservationInfo(expiresAt=to_utc_iso(expires_at)),
    )


@router.get("", response_model=CartResponse)
def get_cart(
    db: Session = Depends(get_db),
    member: Member | None = Depends(get_optional_member),
    gu_cart_session: str | None = Cookie(default=None, alias=CART_SESSION_COOKIE),
) -> CartResponse:
    cart, _ = cart_service.get_or_create_cart(db, member, gu_cart_session)
    db.commit()

    now = get_db_now(db)
    is_member = member is not None

    items = list(
        db.execute(
            select(CartItem)
            .where(CartItem.cart_id == cart.cart_id)
            .order_by(CartItem.cart_item_id)
        ).scalars()
    )

    # 明細ごとに、有効な引当が残っているかを見る。
    # 60分で失効するため、カートに入っていても在庫が確保されているとは限らない。
    # ここで嘘をつくと、決済まで進んでから在庫不足になる。
    reservations = list(
        db.execute(
            select(Reservation).where(
                Reservation.cart_item_id.in_([i.cart_item_id for i in items] or [-1])
            )
        ).scalars()
    )
    reserved_qty: dict[int, int] = {}
    earliest: dict[int, object] = {}
    for r in reservations:
        if ReservationState(r.status, r.expires_at).is_active(now):
            reserved_qty[r.cart_item_id] = reserved_qty.get(r.cart_item_id, 0) + r.quantity
            if r.cart_item_id not in earliest or r.expires_at < earliest[r.cart_item_id]:
                earliest[r.cart_item_id] = r.expires_at

    views: list[CartItemView] = []
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
            is_member=is_member,
        )
        alteration = None
        if item.alteration_type:
            alteration = AlterationDetail(
                type=item.alteration_type,
                lengthMm=item.alteration_length_mm,
                fee=pricing.resolve_alteration_fee(item.alteration_type),
            feeTaxIncluded=pricing.tax_included_unit_price(
                pricing.resolve_alteration_fee(item.alteration_type)
            ),
            )
        views.append(
            CartItemView(
                cartItemId=item.cart_item_id,
                skuId=item.sku_id,
                productId=product.product_id,
                productName=product.name,
                colorName=sku.color_name,
                size=sku.size,
                quantity=item.quantity,
                unitPrice=unit_price,
                unitPriceTaxIncluded=pricing.tax_included_unit_price(unit_price),
                priceType=price_type,
                alteration=alteration,
                reserved=reserved_qty.get(item.cart_item_id, 0) >= item.quantity,
                reservedUntil=(
                    to_utc_iso(earliest[item.cart_item_id])
                    if item.cart_item_id in earliest
                    else None
                ),
            )
        )
        line_items.append(
            pricing.LineItem(
                unit_price_ex_tax=unit_price,
                quantity=item.quantity,
                alteration_type=item.alteration_type,
            )
        )

    # カートの段階では送料・手数料・消費税を出さない。
    # 配送方法と支払方法が決まっていないため、算出できない。
    # 「送料込みの見込み額」を出すと、後で変わったときに不信を招く。
    return CartResponse(
        cartId=cart.cart_id,
        items=views,
        amount=CartAmountView(
            subtotal=sum(li.goods_amount for li in line_items),
            alterationFee=sum(li.alteration_amount for li in line_items),
        ),
    )


@router.delete("/items/{cart_item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cart_item(
    cart_item_id: int,
    db: Session = Depends(get_db),
    member: Member | None = Depends(get_optional_member),
    gu_cart_session: str | None = Cookie(default=None, alias=CART_SESSION_COOKIE),
) -> Response:
    cart, _ = cart_service.get_or_create_cart(db, member, gu_cart_session)
    cart_service.lock_cart(db, cart)  # 注文確定や投入と同時に走っても、カートの形を崩さない

    item = db.get(CartItem, cart_item_id)
    # 他人のカートの明細を、IDを推測して削除できてはならない。
    # 「見つからない」と「あなたのものではない」を区別せず、どちらも404にする。
    # 区別すると、IDを総当たりするだけで他人の明細の存在が分かってしまう。
    if item is None or item.cart_id != cart.cart_id:
        db.rollback()
        raise NotFoundError(f"カート明細が見つかりません: {cart_item_id}")

    try:
        for r in db.execute(
            select(Reservation).where(Reservation.cart_item_id == cart_item_id)
        ).scalars():
            state = ReservationState(r.status, r.expires_at)
            state.release()  # 冪等。すでに RELEASED でも例外にならない
            r.status = state.status
            r.expires_at = state.expires_at
        db.delete(item)
        db.commit()
    except Exception:
        db.rollback()
        raise

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/merge", response_model=MergeCartResponse)
def merge_cart(
    response: Response,
    db: Session = Depends(get_db),
    member: Member = Depends(require_member),
    gu_cart_session: str | None = Cookie(default=None, alias=CART_SESSION_COOKIE),
) -> MergeCartResponse:
    """ログイン直後に呼ぶ。未ログインで入れた商品を会員のカートへ移す（設計仕様書 4.2.2）。"""
    try:
        discarded = cart_service.merge_guest_cart(db, member, gu_cart_session)
        db.commit()
    except Exception:
        db.rollback()
        raise
    # 統合が済んだ未ログインのカートの識別子は、もう使わない
    response.delete_cookie(CART_SESSION_COOKIE)
    return MergeCartResponse(
        discarded=[
            DiscardedLineView(
                productName=d.product_name,
                colorName=d.color_name,
                size=d.size,
                alterationLengthMm=d.alteration_length_mm,
            )
            for d in discarded
        ]
    )
