"""FastAPI アプリケーション。

業務例外を HTTP のステータスコードへ対応付ける場所でもある。
routers は HTTP を知らず、services はドメインの言葉で例外を投げる。
その翻訳をここで1箇所にまとめる。
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.db import SessionLocal, engine
from app.routers import auth, cart, checkout, orders, products
from app.services.errors import (
    AmountMismatchError,
    AuthenticationError,
    CheckoutIncompleteError,
    ConflictError,
    DataIntegrityError,
    DomainError,
    InvalidStateError,
    NotFoundError,
    OrderInProgressError,
    PaymentDeclinedError,
    StockInsufficientError,
    StockInsufficientMultiError,
    ValidationError,
)

logger = logging.getLogger("gu_ec")


# --- 決済待ちの注文の定期照会 -------------------------------------------
#
# ChatGPT のレビューで指摘された欠陥への対処。決済の応答が得られなかった注文は、
# 以前は利用者が注文の画面を開いたときにしか照会していなかった。
# 開かなければ、否決された注文の在庫が永久に戻らない。
#
# 同じプロセスの中で定期的に照会する。別プロセスのバッチにしないのは、
# 決済代行のスタブが PSP 側の記録をプロセスの中に持っているため。
# 本物の PSP に接続する場合は、外部のジョブや PSP からの通知（webhook）に置き換える。
#
# 照会の間隔（既定5分）は設計仕様書 4.5 の未確定事項（テスト仕様書【未確定14】）。

RECONCILE_INTERVAL_SECONDS = int(os.getenv("RECONCILE_INTERVAL_SECONDS", "300"))
RECONCILE_MIN_AGE_SECONDS = int(os.getenv("RECONCILE_MIN_AGE_SECONDS", "60"))


def _reconcile_loop(stop: threading.Event) -> None:
    from app.services.order_service import reconcile_pending_orders

    while not stop.wait(RECONCILE_INTERVAL_SECONDS):
        db = SessionLocal()
        try:
            counts = reconcile_pending_orders(db, RECONCILE_MIN_AGE_SECONDS)
            if counts:
                logger.info("決済待ちの注文を照会しました: %s", counts)
        except Exception:
            logger.error("定期照会に失敗しました", exc_info=True)
        finally:
            db.close()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    stop = threading.Event()
    worker = None
    if RECONCILE_INTERVAL_SECONDS > 0:
        worker = threading.Thread(target=_reconcile_loop, args=(stop,), daemon=True)
        worker.start()
    yield
    stop.set()


app = FastAPI(
    title="GUオンラインストア API",
    description="tech0 Step4 Lv3 個人課題。設計仕様書 6章に対応する。",
    version="0.1.0",
    lifespan=lifespan,
)

# フロントエンド（Next.js）からの呼び出しを許可する。
# Cookie を送るため allow_credentials=True とし、オリジンは明示列挙する。
# allow_origins=["*"] と allow_credentials=True は併用できない。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(products.router)
app.include_router(cart.router)
app.include_router(checkout.router)
app.include_router(orders.router)


_STATUS_BY_ERROR: list[tuple[type[DomainError], int]] = [
    (NotFoundError, 404),
    (AuthenticationError, 401),
    (StockInsufficientError, 409),
    (StockInsufficientMultiError, 409),
    (OrderInProgressError, 409),
    (InvalidStateError, 409),
    (ConflictError, 422),  # 同じ冪等キーで内容が違う（DS-461）
    (AmountMismatchError, 422),  # 金額の不一致（DS-628）
    (PaymentDeclinedError, 402),
    (CheckoutIncompleteError, 400),
    (ValidationError, 400),
    (DataIntegrityError, 500),
]


@app.exception_handler(DomainError)
def handle_domain_error(request: Request, exc: DomainError) -> JSONResponse:
    status = 400
    for error_type, code in _STATUS_BY_ERROR:
        if isinstance(exc, error_type):
            status = code
            break

    details = None
    if isinstance(exc, StockInsufficientError):
        # DS-622: 引当可能数を応答に含める
        details = [
            {
                "skuId": exc.sku_id,
                "requested": exc.requested,
                "available": exc.available,
            }
        ]
    elif isinstance(exc, StockInsufficientMultiError):
        # DS-454: 確保できなかった SKU を示す
        details = exc.shortages

    if status >= 500:
        # データの破損は握りつぶさず、必ずログに残す
        logger.error("DataIntegrityError: %s", exc, exc_info=True)

    return JSONResponse(
        status_code=status,
        content={"error": {"code": exc.code, "message": str(exc), "details": details}},
    )


@app.get("/api/health", tags=["health"])
def health() -> dict:
    """DB への疎通を含めた死活確認。"""
    with engine.connect() as conn:
        now = conn.execute(text("SELECT NOW()")).scalar_one()
        products_count = conn.execute(text("SELECT COUNT(*) FROM product")).scalar_one()
        skus_count = conn.execute(text("SELECT COUNT(*) FROM sku")).scalar_one()
    return {
        "status": "ok",
        "dbTime": str(now),
        "products": products_count,
        "skus": skus_count,
    }
