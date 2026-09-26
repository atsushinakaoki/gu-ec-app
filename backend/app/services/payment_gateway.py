"""決済代行事業者（PSP）のスタブ。

テスト仕様書 8.2 に対応する。本物の PSP には接続しない。

--- 再現する挙動 ---

  SUCCEEDED  決済成立。取引IDを返す
  DECLINED   与信否決
  TIMEOUT    応答が得られない。ただし PSP 側では決済が成立している場合がある

TIMEOUT がこのスタブの要点である。呼び出し側からは結果が分からないが、
PSP 側には「本当の結果」が存在する。後から照会（inquire）すると
その本当の結果が返る。設計仕様書 DS-448〜450 を検証するには、
「応答は無かったが、実は成立していた」状況を作れなければならない。

--- 挙動の切り替え ---

環境変数 PSP_STUB_MODE で切り替える。

  success                 （既定）
  decline
  timeout_then_success    応答なし。照会すると成立していた
  timeout_then_decline    応答なし。照会すると否決されていた

照会（inquire）の応答は PSP_STUB_INQUIRY で切り替える。

  answer   （既定）PSP 側の本当の結果を返す
  timeout  照会にも応答しない（TC-IT-TO-04。決済待ちが続く状態を作る）

要求の内容（ヘッダ等）で切り替えられるようにはしない。
それを許すと、本番のコードに「外部から決済結果を操作できる口」が残る。
テスト仕様書【未確定26】（テスト用の制御点を本番のコードに設けることの是非）に
関わるため、プロセスの起動時にしか変えられない形にとどめている。

--- カード番号を扱わない ---

このスタブの charge() はカード番号を引数に取らない。
設計上、カード情報は PSP のトークン化により自社のシステムを経由しない（DS-582）。
引数に無ければ、誤ってログや DB に書き出すこともない（TC-IT-OK-12、13）。
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from dataclasses import dataclass

logger = logging.getLogger("gu_ec.psp")

SUCCEEDED = "SUCCEEDED"
DECLINED = "DECLINED"
TIMEOUT = "TIMEOUT"


@dataclass(frozen=True)
class PaymentResult:
    status: str
    transaction_id: str | None = None


# PSP 側の記録。注文番号をキーとする。
# 同じ注文番号で再度 charge() が来たら、新たに決済せず前回の結果を返す（DS-452）。
_ledger: dict[str, PaymentResult] = {}
_calls: list[tuple[str, int, str]] = []  # (注文番号, 金額, 支払方法)。テストでの検証用
_lock = threading.Lock()


def _mode() -> str:
    return os.getenv("PSP_STUB_MODE", "success").lower()


def charge(order_number: str, amount: int, payment_method: str) -> PaymentResult:
    """決済を要求する。"""
    # 金額と注文番号は記録するが、カード情報はそもそも受け取っていない
    logger.info("PSP charge: order=%s amount=%d method=%s", order_number, amount, payment_method)

    with _lock:
        _calls.append((order_number, amount, payment_method))

        if order_number in _ledger:
            # DS-452: 同一注文番号の重複実行を排除する。二重に課金しない
            actual = _ledger[order_number]
            return actual

        mode = _mode()
        if mode == "decline":
            actual = PaymentResult(DECLINED)
        elif mode in ("success", "timeout_then_success"):
            actual = PaymentResult(SUCCEEDED, f"TX-{uuid.uuid4().hex[:16]}")
        elif mode == "timeout_then_decline":
            actual = PaymentResult(DECLINED)
        else:
            raise RuntimeError(f"未知の PSP_STUB_MODE です: {mode}")

        _ledger[order_number] = actual

    if mode.startswith("timeout"):
        # PSP 側では結果が確定しているが、呼び出し側には届かない
        return PaymentResult(TIMEOUT)
    return actual


def inquire(order_number: str) -> PaymentResult:
    """取引の状態を照会する（DS-449）。"""
    if os.getenv("PSP_STUB_INQUIRY", "answer").lower() == "timeout":
        return PaymentResult(TIMEOUT)
    with _lock:
        result = _ledger.get(order_number)
    if result is None:
        # PSP に要求が届いていなかった。決済は成立していない
        return PaymentResult(DECLINED)
    return result


def calls() -> list[tuple[str, int, str]]:
    """テスト用。これまでに受けた決済要求の一覧。"""
    with _lock:
        return list(_calls)


def reset() -> None:
    """テスト用。"""
    with _lock:
        _ledger.clear()
        _calls.clear()
