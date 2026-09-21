"""業務例外。

HTTP のステータスコードは routers 側で対応付ける。
services はドメインの言葉で例外を投げ、HTTP を知らない。
"""


class DomainError(Exception):
    """業務上の例外の基底。"""

    code = "DOMAIN_ERROR"


class DataIntegrityError(DomainError):
    """データが取りうるはずのない状態にある（DS-322）。

    在庫数が負である等。要求の誤りではないため、利用者に再試行を促しても
    解決しない。握りつぶさず、必ず失敗として扱う。
    """

    code = "DATA_INTEGRITY"


class InvalidStateError(DomainError):
    """その状態では行えない操作が呼ばれた（DS-331、DS-333）。"""

    code = "INVALID_STATE"


class StockInsufficientError(DomainError):
    """引当可能数が要求に満たない（DS-622）。"""

    code = "STOCK_INSUFFICIENT"

    def __init__(self, sku_id: str, requested: int, available: int) -> None:
        super().__init__(
            f"在庫が不足しています: sku_id={sku_id}, 要求={requested}, 引当可能={available}"
        )
        self.sku_id = sku_id
        self.requested = requested
        self.available = available


class ValidationError(DomainError):
    """入力値が要件を満たさない。"""

    code = "VALIDATION_ERROR"


class NotFoundError(DomainError):
    code = "NOT_FOUND"


class AuthenticationError(DomainError):
    code = "AUTHENTICATION_FAILED"


class ConflictError(DomainError):
    """冪等キーの再送で、内容が一致しない（DS-461）。422 を返す。

    同じキーで内容が違う要求は、通信の再送ではない。
    Frontend の不具合か、要求の改ざんである。
    """

    code = "IDEMPOTENCY_CONFLICT"


class OrderInProgressError(DomainError):
    """同じ冪等キーの注文が、まだ処理中である（設計仕様書 4.4.8）。409 を返す。"""

    code = "ORDER_IN_PROGRESS"


class AmountMismatchError(DomainError):
    """Frontend の算出額と Backend の算出額が一致しない（DS-628）。422 を返す。

    正しい金額は応答に含めない（DS-629）。改ざんの試行に手がかりを与えないため。
    """

    code = "AMOUNT_MISMATCH"


class CheckoutIncompleteError(DomainError):
    """配送方法・支払方法が未選択、またはカートが空。400 を返す。"""

    code = "CHECKOUT_INCOMPLETE"


class PaymentDeclinedError(DomainError):
    """決済が否決された（DS-445）。402 を返す。"""

    code = "PAYMENT_DECLINED"


class StockInsufficientMultiError(DomainError):
    """注文確定の時点で、複数の SKU について在庫が確保できない（DS-454）。409 を返す。"""

    code = "STOCK_INSUFFICIENT"

    def __init__(self, shortages: list[dict]) -> None:
        super().__init__("在庫が確保できない商品があります")
        self.shortages = shortages
