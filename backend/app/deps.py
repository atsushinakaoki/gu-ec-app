"""FastAPI の依存性。

トークンは Cookie から読む。Authorization ヘッダは受け付けない。

設計仕様書 5章の判断:
JWT はフロントエンドの localStorage ではなく HttpOnly Cookie に置く。
localStorage は JavaScript から読めるため、XSS が1つでもあれば
トークンをそのまま持ち出される。HttpOnly Cookie なら JS から読めない。

代わりに CSRF のリスクが生じる。ブラウザは Cookie を自動で送るため、
別サイトのフォームから POST されると、利用者の意図しない操作が通りうる。
これには SameSite=Lax と、状態を変える操作への CSRF トークンで対処する。

どちらのリスクを取るかの選択であり、XSS の方が被害が大きいと判断した。
XSS は「トークンが盗まれて任意の操作が継続的に可能になる」のに対し、
CSRF は「特定の操作が1回通る」に留まり、対策も定型化している。
"""

from __future__ import annotations

from fastapi import Cookie, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Member
from app.services.errors import AuthenticationError
from app.services.security import decode_access_token

ACCESS_TOKEN_COOKIE = "gu_access_token"


def get_optional_member(
    db: Session = Depends(get_db),
    gu_access_token: str | None = Cookie(default=None, alias=ACCESS_TOKEN_COOKIE),
) -> Member | None:
    """ログインしていれば会員を、していなければ None を返す。

    商品閲覧やカート投入は未ログインでも成立するため、
    トークンが無いことをエラーにしない。
    """
    if not gu_access_token:
        return None

    member_id = decode_access_token(gu_access_token)
    if member_id is None:
        return None

    member = db.get(Member, member_id)
    if member is None or member.is_withdrawn:
        # 退会した会員のトークンは、期限内であっても無効とする。
        # 認可の判断をトークンの中身だけで済ませず、毎回 DB を見る。
        return None
    return member


def require_member(
    member: Member | None = Depends(get_optional_member),
) -> Member:
    """ログインを必須とする。注文確定など、会員でなければ行えない操作で使う。"""
    if member is None:
        raise AuthenticationError("ログインが必要です")
    return member
