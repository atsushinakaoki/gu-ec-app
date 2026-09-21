"""環境設定。

.env はリポジトリのルートに置く（db/run_sql.py と同じファイルを共用する）。
カレントディレクトリから親をたどって探すため、どこから起動しても読める。
"""

import os
import pathlib

from dotenv import load_dotenv


def _load_env() -> None:
    here = pathlib.Path(__file__).resolve()
    for parent in [pathlib.Path.cwd(), *here.parents]:
        candidate = parent / ".env"
        if candidate.is_file():
            load_dotenv(candidate)
            return


_load_env()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"環境変数 {name} が設定されていません。リポジトリ直下の .env を確認してください。"
        )
    return value


DB_HOST = _require("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = _require("DB_USER")
DB_PASSWORD = _require("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME", "gu_ec_nakaoki")
DB_SSL = os.getenv("DB_SSL", "on").lower() != "off"

# JWT の署名鍵。本番では必ず .env で与える（DS-521）
JWT_SECRET = os.getenv("JWT_SECRET", "dev-only-secret-do-not-use-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))

# (1) ではオンライン在庫のみを扱う（設計仕様書 2章）
ONLINE_LOCATION_ID = int(os.getenv("ONLINE_LOCATION_ID", "1"))

# 引当の有効期間（分）。設計仕様書 DS-331
RESERVATION_TTL_MINUTES = int(os.getenv("RESERVATION_TTL_MINUTES", "60"))
