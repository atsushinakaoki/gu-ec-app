"""テーブル定義（db/schema.sql に対応する ORM モデル）。

このファイルからはテーブルを作らない。スキーマの正は db/schema.sql であり、
ここはそれを Python から触るための写像に過ぎない。
列を増やすときは schema.sql を直してから、こちらを合わせる。
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "product"

    product_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    gender: Mapped[str] = mapped_column(String(10))
    regular_price: Mapped[int] = mapped_column(Integer)
    member_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    member_price_from: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    member_price_to: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    alterable: Mapped[bool] = mapped_column(Boolean, default=False)
    original_length_mm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_alteration_length_mm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    skus: Mapped[list[Sku]] = relationship(back_populates="product")


class Sku(Base):
    __tablename__ = "sku"

    sku_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    product_id: Mapped[str] = mapped_column(String(20), ForeignKey("product.product_id"))
    color_code: Mapped[str] = mapped_column(String(10))
    color_name: Mapped[str] = mapped_column(String(50))
    size: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    product: Mapped[Product] = relationship(back_populates="skus")
    stocks: Mapped[list[Stock]] = relationship(back_populates="sku")


class Location(Base):
    __tablename__ = "location"

    location_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(100))
    address: Mapped[str | None] = mapped_column(String(200), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Stock(Base):
    __tablename__ = "stock"

    sku_id: Mapped[str] = mapped_column(String(30), ForeignKey("sku.sku_id"), primary_key=True)
    location_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("location.location_id"), primary_key=True
    )
    quantity: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    sku: Mapped[Sku] = relationship(back_populates="stocks")


class Member(Base):
    __tablename__ = "member"

    member_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(100))
    postal_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    address: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_withdrawn: Mapped[bool] = mapped_column(Boolean, default=False)
    withdrawn_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())


class Cart(Base):
    __tablename__ = "cart"

    cart_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    member_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("member.member_id"), nullable=True
    )
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    items: Mapped[list[CartItem]] = relationship(
        back_populates="cart", cascade="all, delete-orphan"
    )


class CartItem(Base):
    __tablename__ = "cart_item"

    cart_item_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cart_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("cart.cart_id"))
    sku_id: Mapped[str] = mapped_column(String(30), ForeignKey("sku.sku_id"))
    quantity: Mapped[int] = mapped_column(Integer)
    alteration_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    alteration_length_mm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    cart: Mapped[Cart] = relationship(back_populates="items")
    sku: Mapped[Sku] = relationship()


class Order(Base):
    __tablename__ = "orders"

    order_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_number: Mapped[str] = mapped_column(String(20), unique=True)
    member_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("member.member_id"))
    status: Mapped[str] = mapped_column(String(20))
    delivery_method: Mapped[str] = mapped_column(String(20))
    placement_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    payment_method: Mapped[str] = mapped_column(String(20))
    payment_transaction_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)
    content_fingerprint: Mapped[str] = mapped_column(String(64))
    recipient_name: Mapped[str] = mapped_column(String(100))
    recipient_postal_code: Mapped[str] = mapped_column(String(8))
    recipient_address: Mapped[str] = mapped_column(String(200))
    recipient_phone: Mapped[str] = mapped_column(String(20))
    subtotal: Mapped[int] = mapped_column(Integer)
    alteration_fee: Mapped[int] = mapped_column(Integer, default=0)
    shipping_fee: Mapped[int] = mapped_column(Integer, default=0)
    payment_fee: Mapped[int] = mapped_column(Integer, default=0)
    tax: Mapped[int] = mapped_column(Integer)
    total: Mapped[int] = mapped_column(Integer)
    ordered_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    items: Mapped[list[OrderItem]] = relationship(back_populates="order")


class OrderItem(Base):
    __tablename__ = "order_item"

    order_item_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.order_id"))
    sku_id: Mapped[str] = mapped_column(String(30), ForeignKey("sku.sku_id"))
    product_name: Mapped[str] = mapped_column(String(200))
    color_name: Mapped[str] = mapped_column(String(50))
    size: Mapped[str] = mapped_column(String(10))
    unit_price: Mapped[int] = mapped_column(Integer)
    price_type: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[int] = mapped_column(Integer)
    alteration_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    alteration_length_mm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    alteration_fee: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_returnable: Mapped[bool] = mapped_column(Boolean)

    order: Mapped[Order] = relationship(back_populates="items")


class Checkout(Base):
    """購入手続き中の選択。設計仕様書に定義がなく、実装時に追加した。

    経緯は db/migrate_001_checkout.sql を参照。
    """

    __tablename__ = "checkout"

    cart_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cart.cart_id"), primary_key=True
    )
    delivery_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    placement_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    recipient_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    recipient_postal_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    recipient_address: Mapped[str | None] = mapped_column(String(200), nullable=True)
    recipient_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    payment_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())


class Reservation(Base):
    __tablename__ = "reservation"

    reservation_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    sku_id: Mapped[str] = mapped_column(String(30), ForeignKey("sku.sku_id"))
    location_id: Mapped[int] = mapped_column(Integer, ForeignKey("location.location_id"))
    cart_item_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("cart_item.cart_item_id"), nullable=True
    )
    order_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("orders.order_id"), nullable=True
    )
    quantity: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
