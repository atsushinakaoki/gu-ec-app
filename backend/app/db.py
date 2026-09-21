"""データベース接続。

SELECT ... FOR UPDATE を使うため、トランザクションの境界を明示的に制御する。
FastAPI の依存性注入で 1 リクエスト 1 セッションとし、
例外が出た場合は必ずロールバックする（設計仕様書 4.3）。
"""

import datetime as dt
from collections.abc import Iterator

from sqlalchemy import URL, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app import config

_connect_args: dict = {}
if config.DB_SSL:
    # Azure Database for MySQL は TLS を必須とする
    _connect_args["ssl"] = {"ssl": {}}

# パスワードに @ や & が含まれるため、文字列連結で URL を組み立てない。
# URL.create() に値のまま渡すと、SQLAlchemy 側で正しくエスケープされる。
_url = URL.create(
    drivername="mysql+pymysql",
    username=config.DB_USER,
    password=config.DB_PASSWORD,
    host=config.DB_HOST,
    port=config.DB_PORT,
    database=config.DB_NAME,
    query={"charset": "utf8mb4"},
)

engine = create_engine(
    _url,
    connect_args=_connect_args,
    pool_pre_ping=True,  # 接続が切れていた場合に再接続する
    pool_recycle=280,
    future=True,
    # --- 分離レベルを READ COMMITTED にする理由 ---
    #
    # MySQL の既定は REPEATABLE READ であり、トランザクション開始時点の
    # スナップショットを最後まで見せ続ける。これが在庫の引当と噛み合わない。
    #
    # SELECT ... FOR UPDATE は最新の確定データを読むが、
    # ロックなしの SELECT はスナップショットを読む。
    # 両者を1つのトランザクションで併用すると、こうなる。
    #
    #   T1: 商品を読む（この時点でスナップショットが確定）
    #   T2: 商品を読む（この時点でスナップショットが確定）
    #   T1: stock を FOR UPDATE でロック
    #   T2: ロック待ちで停止
    #   T1: 引当を数える → 0件 → 引当を INSERT → COMMIT
    #   T2: ロック取得。引当を数える
    #       → 古いスナップショットのため T1 の INSERT が見えず 0件
    #       → 引当可能と判定し、重複して引当が成立する
    #
    # ロックは正しく機能しているのに、ロックで守った区間の中で
    # 古いデータを読んでいる、という食い違いである。
    #
    # READ COMMITTED では、各 SQL 文がその実行時点の確定データを読む。
    # ロックの解放後に読み直せば、他者の INSERT が見える。
    #
    # 別解として、引当の集計にも FOR SHARE を付けてロック読み取りにする
    # 方法がある。こちらは局所的に直せるが、reservation 側にも
    # ギャップロックがかかり、デッドロックの機会が増える。
    # 在庫引当のように「読んで、判定して、書く」処理が中心の系では
    # READ COMMITTED を既定に据えるほうが素直だと判断した。
    isolation_level="READ COMMITTED",
)

@event.listens_for(engine, "connect")
def _set_utc(dbapi_connection, _record) -> None:
    """接続ごとに、セッションのタイムゾーンを UTC に固定する。

    NOW() や CURRENT_TIMESTAMP の値は、MySQL のセッションのタイムゾーンで決まる。
    サーバの既定に任せると、サーバの設定が変わっただけで全時刻がずれる。
    アプリケーション側は「DB の時刻は常に UTC」を前提にして、
    API で返すときに UTC であることを明示する（to_utc_iso）。
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("SET time_zone = '+00:00'")
    cursor.close()


def to_utc_iso(value: dt.datetime) -> str:
    """DB から読んだ時刻（タイムゾーン情報なし、中身は UTC）を ISO 8601 で返す。

    タイムゾーンを付けずに "2026-09-20T15:24:36" と返すと、
    ブラウザの JavaScript はそれを利用者の端末の時刻（日本なら JST）と解釈し、
    引当の残り時間が9時間ずれて表示される。
    """
    return value.replace(tzinfo=dt.timezone.utc).isoformat()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
