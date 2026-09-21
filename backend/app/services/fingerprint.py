"""注文内容の fingerprint（DS-460）。

注文確定の要求本文は expectedTotal だけである。
同じ冪等キーで「カートの中身は変わったが金額はたまたま同じ」要求が来たとき、
本文だけを比べると同一の注文と誤認する（テスト仕様書 TC-IT-ID-04）。
そこで、注文を構成する内容をすべて正規化してハッシュ値にし、それで比べる。

DB に触れないため単体でテストできる。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class FingerprintLine:
    sku_id: str
    quantity: int
    alteration_type: str | None
    alteration_length_mm: int | None


def compute_fingerprint(
    *,
    member_id: int,
    lines: list[FingerprintLine],
    delivery_method: str,
    placement_type: str | None,
    recipient: tuple[str, str, str, str],
    payment_method: str,
    amounts: tuple[int, int, int, int, int, int],
) -> str:
    """注文内容のハッシュ値（SHA-256、16進64文字）を返す。

    正規化の要点:
      - 明細は並べ替えてから使う。カートへの投入順が違うだけで
        別の注文と判定されないようにするため
      - JSON のキーを整列し、区切り文字も固定する。
        同じ内容から必ず同じ文字列が作られるようにするため
    """
    canonical = {
        "member_id": member_id,
        "lines": sorted(
            [
                [
                    line.sku_id,
                    line.quantity,
                    line.alteration_type or "",
                    line.alteration_length_mm or 0,
                ]
                for line in lines
            ]
        ),
        "delivery_method": delivery_method,
        "placement_type": placement_type or "",
        "recipient": list(recipient),
        "payment_method": payment_method,
        "amounts": list(amounts),
    }
    text = json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
