"""すそ上げの指定の検証。

テスト仕様書 4.6 に対応する。DB に触れないため、単体でテストできる。
商品の属性は引数で受け取る。呼び出し側（cart_service）が DB から読んで渡す。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services import pricing
from app.services.errors import DataIntegrityError, ValidationError

ALTERATION_STEP_MM = 5


@dataclass(frozen=True)
class AlterableSpec:
    """検証に必要な商品の属性だけを持つ。"""

    product_id: str
    alterable: bool
    original_length_mm: int | None
    min_alteration_length_mm: int | None


def validate_alteration(
    spec: AlterableSpec, alteration_type: str | None, length_mm: int | None
) -> None:
    """すそ上げの指定が有効でなければ例外を投げる。有効なら何も返さない。"""
    # 表 #1、#6: 加工しない指定は、商品の加工可否に関わらず有効
    if alteration_type is None and length_mm is None:
        return

    # 表 #3、#4: 加工方法と丈は、双方が指定されるか双方が無いか（FR-564-02）
    if alteration_type is None or length_mm is None:
        raise ValidationError("加工方法と仕上がり丈は、両方を指定してください")

    # 表 #5: 加工できない商品への加工指定（DS-414）。
    # Frontend が選択肢を出さなくても、API を直接叩けば送れてしまう（TC-UT-AL-43）
    if not spec.alterable:
        raise ValidationError(f"この商品はすそ上げの対象外です: {spec.product_id}")

    if alteration_type not in pricing.ALTERATION_FEES_EX_TAX:
        raise ValidationError(f"未知の加工方法です: {alteration_type}")

    # 【未確定9】alterable なのに範囲が未設定。入力の誤りではなくマスタの破損である。
    # schema.sql の CHECK 制約で本来は起きないため、起きたらデータの問題として扱う。
    if spec.min_alteration_length_mm is None or spec.original_length_mm is None:
        raise DataIntegrityError(
            f"加工可能な商品に丈の範囲が設定されていません: {spec.product_id}"
        )

    # TC-UT-AL-30: min > original の商品はどの丈も有効にならない
    if spec.min_alteration_length_mm > spec.original_length_mm:
        raise DataIntegrityError(
            f"加工可能な最短の丈が元の丈を超えています: {spec.product_id}"
        )

    if length_mm % ALTERATION_STEP_MM != 0:
        raise ValidationError(f"仕上がり丈は{ALTERATION_STEP_MM}mm刻みで指定してください")

    # DS-311: 範囲は商品ごと。両端を含む（元の丈ちょうど＝実質加工なし、も許す: TC-UT-AL-14）
    if not (spec.min_alteration_length_mm <= length_mm <= spec.original_length_mm):
        raise ValidationError(
            "仕上がり丈が範囲外です: "
            f"{spec.min_alteration_length_mm}〜{spec.original_length_mm}mm の範囲で指定してください"
        )


def is_valid_alteration(
    spec: AlterableSpec, alteration_type: str | None, length_mm: int | None
) -> bool:
    """真偽値で返す版。テスト仕様書の期待値（true / false）に合わせるため。"""
    try:
        validate_alteration(spec, alteration_type, length_mm)
        return True
    except (ValidationError, DataIntegrityError):
        return False
