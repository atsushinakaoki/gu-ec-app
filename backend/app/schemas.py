"""API の入出力の型。設計仕様書 6章の TypeScript 定義に対応する。

JSON のキーは camelCase、Python 側は snake_case とする。
Pydantic の alias でこの変換を行い、どちらの世界でも自然な名前を使う。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


# --- 商品 ---------------------------------------------------------------


class ProductListItem(ApiModel):
    product_id: str = Field(alias="productId")
    name: str
    gender: str
    regular_price: int = Field(alias="regularPrice")
    member_price: int | None = Field(default=None, alias="memberPrice")
    applied_price: int = Field(alias="appliedPrice")
    applied_price_type: str = Field(alias="appliedPriceType")


class ProductListResponse(ApiModel):
    items: list[ProductListItem]
    total: int
    limit: int
    offset: int


class SkuAvailability(ApiModel):
    sku_id: str = Field(alias="skuId")
    color_code: str = Field(alias="colorCode")
    color_name: str = Field(alias="colorName")
    size: str
    in_stock: bool = Field(alias="inStock")


class AlterationOption(ApiModel):
    type: str
    fee: int
    min_length_mm: int | None = Field(default=None, alias="minLengthMm")
    max_length_mm: int | None = Field(default=None, alias="maxLengthMm")
    step_mm: int = Field(default=5, alias="stepMm")


class ProductDetailResponse(ApiModel):
    product_id: str = Field(alias="productId")
    name: str
    gender: str
    regular_price: int = Field(alias="regularPrice")
    member_price: int | None = Field(default=None, alias="memberPrice")
    applied_price: int = Field(alias="appliedPrice")
    applied_price_type: str = Field(alias="appliedPriceType")
    alterable: bool
    alteration_options: list[AlterationOption] | None = Field(
        default=None, alias="alterationOptions"
    )
    skus: list[SkuAvailability]


# --- カート -------------------------------------------------------------


class AlterationInput(ApiModel):
    type: str
    length_mm: int = Field(alias="lengthMm")


class AddCartItemRequest(ApiModel):
    sku_id: str = Field(alias="skuId")
    quantity: int = Field(ge=1, le=10)
    alteration: AlterationInput | None = None


class AlterationDetail(ApiModel):
    type: str
    length_mm: int = Field(alias="lengthMm")
    fee: int  # 1点あたりの加工料（税抜）


class ReservationInfo(ApiModel):
    expires_at: str = Field(alias="expiresAt")


class AddCartItemResponse(ApiModel):
    cart_item_id: int = Field(alias="cartItemId")
    sku_id: str = Field(alias="skuId")
    quantity: int
    alteration: AlterationDetail | None = None
    reservation: ReservationInfo


class CartItemView(ApiModel):
    cart_item_id: int = Field(alias="cartItemId")
    sku_id: str = Field(alias="skuId")
    product_id: str = Field(alias="productId")
    product_name: str = Field(alias="productName")
    color_name: str = Field(alias="colorName")
    size: str
    quantity: int
    unit_price: int = Field(alias="unitPrice")
    price_type: str = Field(alias="priceType")
    alteration: AlterationDetail | None = None
    # 引当が期限切れになっている明細は、注文時に改めて在庫を取り直す
    reserved: bool


class CartAmountView(ApiModel):
    subtotal: int
    alteration_fee: int = Field(alias="alterationFee")


class CartResponse(ApiModel):
    cart_id: int = Field(alias="cartId")
    items: list[CartItemView]
    amount: CartAmountView


# --- 購入手続き ---------------------------------------------------------


class DeliveryMethodOption(ApiModel):
    code: str
    name: str
    fee: int  # 送料（税抜）。現在のカートの内容で算出する
    available: bool
    unavailable_reason: str | None = Field(default=None, alias="unavailableReason")


class PlacementTypeOption(ApiModel):
    code: str
    name: str
    is_default: bool = Field(alias="isDefault")


class CheckoutOptionsResponse(ApiModel):
    delivery_methods: list[DeliveryMethodOption] = Field(alias="deliveryMethods")
    placement_types: list[PlacementTypeOption] = Field(alias="placementTypes")


class RecipientInput(ApiModel):
    name: str
    postal_code: str = Field(alias="postalCode")
    address: str
    phone: str


class SelectDeliveryRequest(ApiModel):
    delivery_method: str = Field(alias="deliveryMethod")
    placement_type: str | None = Field(default=None, alias="placementType")
    recipient: RecipientInput


class UnavailableReasonView(ApiModel):
    code: str
    message: str
    caused_by: str = Field(alias="causedBy")


class PaymentMethodOption(ApiModel):
    code: str
    name: str
    fee: int
    available: bool
    unavailable_reason: UnavailableReasonView | None = Field(
        default=None, alias="unavailableReason"
    )


class SelectDeliveryResponse(ApiModel):
    payment_methods: list[PaymentMethodOption] = Field(alias="paymentMethods")


class SelectPaymentRequest(ApiModel):
    payment_method: str = Field(alias="paymentMethod")


class SelectPaymentResponse(ApiModel):
    payment_method: str = Field(alias="paymentMethod")
    fee: int


class AmountsView(ApiModel):
    subtotal: int
    alteration_fee: int = Field(alias="alterationFee")
    shipping_fee: int = Field(alias="shippingFee")
    payment_fee: int = Field(alias="paymentFee")
    tax: int
    total: int


class SummaryAlteration(ApiModel):
    type_name: str = Field(alias="typeName")
    length_mm: int = Field(alias="lengthMm")
    fee: int


class SummaryItem(ApiModel):
    sku_id: str = Field(alias="skuId")
    product_name: str = Field(alias="productName")
    color_name: str = Field(alias="colorName")
    size: str
    unit_price: int = Field(alias="unitPrice")
    price_type: str = Field(alias="priceType")
    quantity: int
    subtotal: int
    alteration: SummaryAlteration | None = None
    is_returnable: bool = Field(alias="isReturnable")


class RecipientView(ApiModel):
    name: str
    postal_code: str = Field(alias="postalCode")
    address: str
    phone: str


class DeliveryView(ApiModel):
    method: str
    method_name: str = Field(alias="methodName")
    placement_type: str | None = Field(default=None, alias="placementType")
    recipient: RecipientView


class PaymentView(ApiModel):
    method: str
    method_name: str = Field(alias="methodName")


class Notice(ApiModel):
    code: str
    message: str


class CheckoutSummaryResponse(ApiModel):
    items: list[SummaryItem]
    amounts: AmountsView
    delivery: DeliveryView
    payment: PaymentView
    notices: list[Notice]
    idempotency_key: str = Field(alias="idempotencyKey")


# --- 注文 ---------------------------------------------------------------


class CreateOrderRequest(ApiModel):
    expected_total: int = Field(alias="expectedTotal")


class CreateOrderResponse(ApiModel):
    order_number: str = Field(alias="orderNumber")
    ordered_at: str = Field(alias="orderedAt")
    status: str
    amounts: AmountsView
    message: str | None = None


class OrderItemView(ApiModel):
    sku_id: str = Field(alias="skuId")
    product_name: str = Field(alias="productName")
    color_name: str = Field(alias="colorName")
    size: str
    unit_price: int = Field(alias="unitPrice")
    quantity: int
    alteration_type: str | None = Field(default=None, alias="alterationType")
    alteration_length_mm: int | None = Field(default=None, alias="alterationLengthMm")
    is_returnable: bool = Field(alias="isReturnable")


class OrderDetailResponse(ApiModel):
    order_number: str = Field(alias="orderNumber")
    ordered_at: str = Field(alias="orderedAt")
    status: str
    amounts: AmountsView
    items: list[OrderItemView]
    delivery_method: str = Field(alias="deliveryMethod")
    payment_method: str = Field(alias="paymentMethod")


# --- エラー -------------------------------------------------------------


class ErrorDetail(ApiModel):
    code: str
    message: str
    details: list[dict] | None = None


class ErrorResponse(ApiModel):
    error: ErrorDetail
