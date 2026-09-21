"""認証API。設計仕様書 5章に対応する。

トークンは応答の本文に入れず、HttpOnly Cookie にだけ載せる。
本文に入れると、フロントエンドがそれを localStorage に保存できてしまい、
HttpOnly にした意味が失われる。読めないものは漏らせない。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from pydantic import EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.db import get_db
from app.deps import ACCESS_TOKEN_COOKIE, require_member
from app.models import Member
from app.schemas import ApiModel
from app.services.errors import AuthenticationError
from app.services.security import create_access_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(ApiModel):
    email: EmailStr
    password: str


class MemberResponse(ApiModel):
    member_id: int
    name: str
    email: str


@router.post("/login", response_model=MemberResponse)
def login(
    body: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> MemberResponse:
    member = db.execute(
        select(Member).where(Member.email == body.email)
    ).scalar_one_or_none()

    # メールアドレスが存在しない場合も、パスワードが違う場合も、
    # 退会済みの場合も、すべて同じ文言で返す。
    # 「そのメールアドレスは登録されていません」と返すと、
    # 総当たりで「登録済みのメールアドレスの一覧」を作れてしまう。
    # 会員であること自体が、本人以外に知られてよい情報ではない。
    failure = AuthenticationError("メールアドレスまたはパスワードが正しくありません")

    if member is None:
        # 存在しない場合もハッシュ照合と同程度の時間をかけたいところだが、
        # ①では簡略化する（設計仕様書 1.2）。応答時間の差から
        # 登録の有無が推測されうる点は、既知の制約として残す。
        raise failure
    if member.is_withdrawn:
        raise failure
    if not verify_password(body.password, member.password_hash):
        raise failure

    token = create_access_token(member.member_id)
    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE,
        value=token,
        httponly=True,  # JavaScript から読めない。XSS でも持ち出せない
        samesite="lax",  # 別サイトからの POST では送られない（CSRF 対策）
        max_age=config.JWT_EXPIRE_MINUTES * 60,
        # 本番では secure=True を必ず付ける（HTTPS 以外に送らない）
    )

    return MemberResponse(
        member_id=member.member_id, name=member.name, email=member.email
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> Response:
    # Cookie を消すだけで、サーバ側にトークンの失効リストは持たない。
    # JWT は自己完結型のため、発行済みトークンを期限前に無効化できない。
    # ①ではこれを受け入れ、有効期間を60分と短くすることで影響を抑える。
    response.delete_cookie(key=ACCESS_TOKEN_COOKIE)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=MemberResponse)
def me(member: Member = Depends(require_member)) -> MemberResponse:
    return MemberResponse(
        member_id=member.member_id, name=member.name, email=member.email
    )
