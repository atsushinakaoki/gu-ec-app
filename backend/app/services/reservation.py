"""引当の状態遷移。

    ACTIVE ──confirm()──> CONFIRMED
      │
      └────release()───> RELEASED

設計仕様書 DS-331〜333 の対応:
  DS-331  confirm() は ACTIVE のときだけ成功する。他の状態では例外
  DS-332  release() は冪等。RELEASED に対して呼んでも何も起きない
  DS-333  CONFIRMED に release() は例外

confirm と release で冪等性の扱いが違うのは、意図的である。

release は取消・期限切れ・失敗のいずれからも呼ばれ、
同じ引当に二度到達することが普通に起こる。二度目を例外にすると、
後片付けの経路が壊れる。だから冪等にする。

confirm は「在庫を確定した」という一度きりの事実である。
二度目の confirm が黙って通ると、すでに確定した引当をもう一度確定
できることになり、呼び出し側の重複を検出できなくなる。だから例外にする。
"""

from __future__ import annotations

import datetime as dt

from app.services.errors import DataIntegrityError, InvalidStateError
from app.services.stock import STATUS_ACTIVE, STATUS_CONFIRMED, STATUS_RELEASED


class ReservationState:
    """引当1件の状態。DB の行から作り、遷移させてから書き戻す。"""

    def __init__(self, status: str, expires_at: dt.datetime | None) -> None:
        if status not in (STATUS_ACTIVE, STATUS_CONFIRMED, STATUS_RELEASED):
            raise DataIntegrityError(f"未知の引当状態です: {status}")
        self.status = status
        self.expires_at = expires_at

    def is_active(self, now: dt.datetime) -> bool:
        """有効な引当か。

        期限ちょうどは失効とする（TC-UT-RS-03）。
        stock.is_deducted と同じ境界の取り方でなければならない。
        片方が `>` で片方が `>=` だと、期限の瞬間に
        「引当可能数からは減っているのに、引当としては無効」という
        状態が1秒だけ生じる。
        """
        if self.status != STATUS_ACTIVE:
            return False
        if self.expires_at is None:
            raise DataIntegrityError("ACTIVE な引当に expires_at が設定されていません")
        return now < self.expires_at

    def confirm(self) -> None:
        """在庫を確定する。ACTIVE のときだけ成功する（DS-331）。"""
        if self.status != STATUS_ACTIVE:
            raise InvalidStateError(
                f"{self.status} の引当を確定することはできません"
            )
        self.status = STATUS_CONFIRMED
        # 確定後は期限の概念がなくなる
        self.expires_at = None

    def release(self) -> None:
        """引当を解放する。冪等（DS-332）。ただし CONFIRMED からは不可（DS-333）。"""
        if self.status == STATUS_RELEASED:
            return  # 何もしない。例外も投げない
        if self.status == STATUS_CONFIRMED:
            raise InvalidStateError(
                "確定済みの引当を解放することはできません。返品・キャンセルの手続きが必要です"
            )
        self.status = STATUS_RELEASED
        self.expires_at = None

    def revert_confirmation(self) -> None:
        """決済の失敗に伴い、確定を取り消す。補償処理でのみ使う。

        --- この遷移を release() と別に設けた理由 ---

        設計仕様書 DS-333 は「CONFIRMED に release() は例外」とし、
        DS-445 は「決済の失敗時、引当を解放する」としている。
        決済の失敗時点で引当はすでに CONFIRMED なので、この2つは衝突する。
        実装の段階で判明した設計の矛盾である。

        DS-333 を緩めて release() が CONFIRMED も受け付けるようにすると、
        本来は返品・キャンセルの手続きを経るべき確定済みの引当が、
        通常の後片付け（期限切れの解放など）の経路で黙って解放されうる。
        DS-333 が防ごうとしていたのはまさにそれである。

        そこで、補償という特定の文脈でのみ呼ぶ遷移を名前を分けて用意する。
        「どこから呼ばれうるか」をコードの検索で確認できるようにしておく。

            ACTIVE ──confirm()──> CONFIRMED ──revert_confirmation()──> RELEASED
                                               （決済失敗の補償処理のみ）
        """
        if self.status != STATUS_CONFIRMED:
            raise InvalidStateError(
                f"{self.status} の引当は確定されていないため、確定を取り消せません"
            )
        self.status = STATUS_RELEASED
        self.expires_at = None
