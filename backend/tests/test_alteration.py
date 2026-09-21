"""テスト仕様書 4.6 Alteration（すそ上げの指定）"""

import pytest

from app.services.alteration import AlterableSpec, is_valid_alteration, validate_alteration
from app.services.errors import ValidationError

# seed.sql の 360411（スーパーワイドカーゴパンツ）と同じ値。元の丈800mm、下限400mm
PANTS = AlterableSpec("360411", True, original_length_mm=800, min_alteration_length_mm=400)
# 加工できない商品
TSHIRT = AlterableSpec("360402", False, original_length_mm=None, min_alteration_length_mm=None)
# 丈の値を持つが、加工サービスの対象外である商品。
# TSHIRT だけで検証すると、加工可否のチェックを外しても
# 後段の「丈が未設定」のチェックで偶然に弾かれてしまい、
# 加工可否を見ているかどうかが検証できない（変異テストで判明）。
NOT_ALTERABLE_WITH_LENGTH = AlterableSpec(
    "360499", False, original_length_mm=800, min_alteration_length_mm=400
)
# seed.sql の 360406（KIDS）。元の丈600mm、下限300mm
KIDS = AlterableSpec("360406", True, original_length_mm=600, min_alteration_length_mm=300)


# --- 4.6.1 加工方法と丈の依存関係 ---------------------------------------


@pytest.mark.parametrize(
    "spec, alteration_type, length, expected",
    [
        pytest.param(PANTS, None, None, True, id="TC-UT-AL-01_加工可_指定なし"),
        pytest.param(PANTS, "SINGLE_FOLD", 700, True, id="TC-UT-AL-02_加工可_範囲内"),
        pytest.param(PANTS, None, 700, False, id="TC-UT-AL-03_丈のみ指定"),
        pytest.param(PANTS, "SINGLE_FOLD", None, False, id="TC-UT-AL-04_方法のみ指定"),
        pytest.param(TSHIRT, "SINGLE_FOLD", 700, False, id="TC-UT-AL-05a_加工不可に指定"),
        pytest.param(
            NOT_ALTERABLE_WITH_LENGTH, "SINGLE_FOLD", 700, False, id="TC-UT-AL-05b_丈はあるが加工不可"
        ),
        pytest.param(TSHIRT, None, None, True, id="TC-UT-AL-06_加工不可_指定なし"),
    ],
)
def test_decision_table(spec, alteration_type, length, expected):
    assert is_valid_alteration(spec, alteration_type, length) is expected


# --- 4.6.2 丈の境界値 ---------------------------------------------------


@pytest.mark.parametrize(
    "length, expected",
    [
        pytest.param(395, False, id="TC-UT-AL-10_395mm_下限未満"),
        pytest.param(400, True, id="TC-UT-AL-11_400mm_下限ちょうど"),
        pytest.param(405, True, id="TC-UT-AL-12_405mm"),
        pytest.param(795, True, id="TC-UT-AL-13_795mm"),
        pytest.param(800, True, id="TC-UT-AL-14_800mm_元の丈と同一"),
        pytest.param(805, False, id="TC-UT-AL-15_805mm_元の丈を超過"),
    ],
)
def test_length_boundary(length, expected):
    assert is_valid_alteration(PANTS, "SINGLE_FOLD", length) is expected


def test_DS_311_lower_bound_is_per_product():
    """同じ300mmでも、KIDS では有効、大人用パンツでは無効。

    下限を全商品一律（例えば400mm）にしていたら、KIDS で
    本来できる加工が選べなくなる。DS-311 はこれを防ぐために
    下限を商品ごとの属性にした。
    """
    assert is_valid_alteration(KIDS, "SINGLE_FOLD", 300) is True
    assert is_valid_alteration(PANTS, "SINGLE_FOLD", 300) is False


# --- 4.6.3 刻みの検証 ---------------------------------------------------


@pytest.mark.parametrize(
    "length, expected",
    [
        pytest.param(700, True, id="TC-UT-AL-20_700mm"),
        pytest.param(705, True, id="TC-UT-AL-21_705mm"),
        pytest.param(701, False, id="TC-UT-AL-22_701mm"),
        pytest.param(703, False, id="TC-UT-AL-23_703mm"),
        pytest.param(704, False, id="TC-UT-AL-24_704mm"),
    ],
)
def test_step(length, expected):
    assert is_valid_alteration(PANTS, "SINGLE_FOLD", length) is expected


# --- 4.6.4 商品マスタの不整合および悪用の観点 ---------------------------


def test_TC_UT_AL_30_min_greater_than_original():
    broken = AlterableSpec("X", True, original_length_mm=700, min_alteration_length_mm=800)
    for length in (600, 700, 750, 800, 900):
        assert is_valid_alteration(broken, "SINGLE_FOLD", length) is False


@pytest.mark.skip(reason="【未確定9】alterable=true で min が null。実装は DataIntegrityError（無効）とする")
def test_TC_UT_AL_31_min_is_null():
    pass


@pytest.mark.parametrize(
    "spec, alteration_type, length",
    [
        pytest.param(PANTS, "SINGLE_FOLD", -5, id="TC-UT-AL-40_負の丈"),
        pytest.param(PANTS, "SINGLE_FOLD", 10**9, id="TC-UT-AL-41_極端に大きい丈"),
        pytest.param(PANTS, "TRIPLE_FOLD", 700, id="TC-UT-AL-42_未定義の加工方法"),
        # Frontend が選択肢を出さなくても、API を直接叩けば送れる
        pytest.param(TSHIRT, "DOUBLE_FOLD", 700, id="TC-UT-AL-43a_加工不可に直接指定"),
        pytest.param(
            NOT_ALTERABLE_WITH_LENGTH, "DOUBLE_FOLD", 700, id="TC-UT-AL-43b_丈はあるが加工不可"
        ),
    ],
)
def test_abuse(spec, alteration_type, length):
    assert is_valid_alteration(spec, alteration_type, length) is False


def test_TC_UT_AL_05_rejected_for_the_right_reason():
    """拒否されることだけでなく、拒否の理由が「対象外」であることを確かめる。

    True / False だけを見るテストは、別の理由でたまたま False に
    なった場合も合格と判定してしまう。
    """
    with pytest.raises(ValidationError, match="対象外"):
        validate_alteration(NOT_ALTERABLE_WITH_LENGTH, "SINGLE_FOLD", 700)
