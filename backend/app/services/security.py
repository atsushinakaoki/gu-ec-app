"""パスワードの検証と JWT の発行・検証。

設計仕様書 5章に対応する。

パスワードは bcrypt でハッシュ化して保持し、平文は一切保持しない。
照合は bcrypt.checkpw で行う。これは意図的に遅い関数であり、
総当たり攻撃の速度を抑えるために遅さそのものが機能である。
"""

from __future__ import annotations

import datetime as dt

import bcrypt
import jwt

from app import config


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # ハッシュの形式が不正な場合。照合失敗として扱う
        return False


def create_access_token(member_id: int, now: dt.datetime | None = None) -> str:
    issued_at = now or dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": str(member_id),
        "iat": int(issued_at.timestamp()),
        "exp": int(
            (issued_at + dt.timedelta(minutes=config.JWT_EXPIRE_MINUTES)).timestamp()
        ),
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def decode_access_token(token: str) -> int | None:
    """トークンが有効なら member_id を、無効なら None を返す。

    アルゴリズムを明示して検証する。指定を省略すると、
    ヘッダに alg: none を書いたトークンを受け入れてしまう実装がある。
    署名の検証を攻撃者が無効化できる、よく知られた穴である。
    """
    try:
        payload = jwt.decode(
            token,
            config.JWT_SECRET,
            algorithms=[config.JWT_ALGORITHM],
        )
    except jwt.PyJWTError:
        return None

    sub = payload.get("sub")
    if sub is None:
        return None
    try:
        return int(sub)
    except (TypeError, ValueError):
        return None
