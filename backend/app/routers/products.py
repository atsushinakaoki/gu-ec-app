"""商品API。設計仕様書 6.2 に対応する。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.deps import get_optional_member
from app.models import Member, Product, Sku
from app.schemas import (
    AlterationOption,
    ProductDetailResponse,
    ProductListItem,
    ProductListResponse,
    SkuAvailability,
)
from app.services import pricing
from app.services.availability import get_available_quantities, get_db_now
from app.services.errors import NotFoundError

router = APIRouter(prefix="/api/products", tags=["products"])

SIZE_ORDER = ["XS", "S", "M", "L", "XL", "XXL", "3XL", "ONE"]


def _size_key(size: str) -> int:
    return SIZE_ORDER.index(size) if size in SIZE_ORDER else len(SIZE_ORDER)


@router.get("", response_model=ProductListResponse)
def list_products(
    gender: str | None = Query(default=None, description="WOMEN / MEN / KIDS"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    member: Member | None = Depends(get_optional_member),
) -> ProductListResponse:
    stmt = select(Product).order_by(Product.product_id)
    count_stmt = select(func.count()).select_from(Product)
    if gender:
        stmt = stmt.where(Product.gender == gender.upper())
        count_stmt = count_stmt.where(Product.gender == gender.upper())

    total = db.execute(count_stmt).scalar_one()
    products = list(db.execute(stmt.limit(limit).offset(offset)).scalars())
    now = get_db_now(db)
    is_member = member is not None

    items = []
    for p in products:
        unit_price, price_type = pricing.resolve_unit_price(
            regular_price=p.regular_price,
            member_price=p.member_price,
            member_price_from=p.member_price_from,
            member_price_to=p.member_price_to,
            now=now,
            is_member=is_member,
        )
        # 会員価格が「いま期間内である」ことは、未ログインでも表示する。
        # 適用されるかどうか（price_type）とは別の情報である。
        member_price_active, _ = pricing.resolve_unit_price(
            regular_price=p.regular_price,
            member_price=p.member_price,
            member_price_from=p.member_price_from,
            member_price_to=p.member_price_to,
            now=now,
            is_member=True,
        )
        items.append(
            ProductListItem(
                productId=p.product_id,
                name=p.name,
                gender=p.gender,
                regularPrice=p.regular_price,
                memberPrice=(
                    member_price_active if member_price_active != p.regular_price else None
                ),
                appliedPrice=unit_price,
                appliedPriceType=price_type,
                regularPriceTaxIncluded=pricing.tax_included_unit_price(p.regular_price),
                memberPriceTaxIncluded=(
                    pricing.tax_included_unit_price(member_price_active)
                    if member_price_active != p.regular_price
                    else None
                ),
                appliedPriceTaxIncluded=pricing.tax_included_unit_price(unit_price),
            )
        )

    return ProductListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{product_id}", response_model=ProductDetailResponse)
def get_product(
    product_id: str,
    db: Session = Depends(get_db),
    member: Member | None = Depends(get_optional_member),
) -> ProductDetailResponse:
    product = db.execute(
        select(Product)
        .options(selectinload(Product.skus))
        .where(Product.product_id == product_id)
    ).scalar_one_or_none()

    if product is None:
        raise NotFoundError(f"商品が見つかりません: {product_id}")

    now = get_db_now(db)
    is_member = member is not None

    unit_price, price_type = pricing.resolve_unit_price(
        regular_price=product.regular_price,
        member_price=product.member_price,
        member_price_from=product.member_price_from,
        member_price_to=product.member_price_to,
        now=now,
        is_member=is_member,
    )
    member_price_active, _ = pricing.resolve_unit_price(
        regular_price=product.regular_price,
        member_price=product.member_price,
        member_price_from=product.member_price_from,
        member_price_to=product.member_price_to,
        now=now,
        is_member=True,
    )

    sku_ids = [s.sku_id for s in product.skus]
    available = get_available_quantities(db, sku_ids, now)

    skus = sorted(product.skus, key=lambda s: (s.color_code, _size_key(s.size)))
    sku_items = [
        SkuAvailability(
            skuId=s.sku_id,
            colorCode=s.color_code,
            colorName=s.color_name,
            size=s.size,
            # 在庫の実数は返さない。「買えるか」だけを返す。
            # 実数を返すと競合他社に在庫の動きを読まれる（設計仕様書 5章）。
            # 数量不足の具体値は、投入を試みた時点で 409 として返す（DS-622）。
            inStock=available.get(s.sku_id, 0) > 0,
        )
        for s in skus
    ]

    alteration = None
    if product.alterable:
        alteration = [
            AlterationOption(
                type=alteration_type,
                fee=fee,
                feeTaxIncluded=pricing.tax_included_unit_price(fee),
                # DS-311: 加工可能な最短の丈は商品ごとに持つ
                minLengthMm=product.min_alteration_length_mm,
                maxLengthMm=product.original_length_mm,
                stepMm=5,
            )
            for alteration_type, fee in pricing.ALTERATION_FEES_EX_TAX.items()
        ]

    return ProductDetailResponse(
        productId=product.product_id,
        name=product.name,
        gender=product.gender,
        regularPrice=product.regular_price,
        memberPrice=(
            member_price_active if member_price_active != product.regular_price else None
        ),
        appliedPrice=unit_price,
        appliedPriceType=price_type,
        regularPriceTaxIncluded=pricing.tax_included_unit_price(product.regular_price),
        memberPriceTaxIncluded=(
            pricing.tax_included_unit_price(member_price_active)
            if member_price_active != product.regular_price
            else None
        ),
        appliedPriceTaxIncluded=pricing.tax_included_unit_price(unit_price),
        alterable=product.alterable,
        alterationOptions=alteration,
        skus=sku_items,
    )
