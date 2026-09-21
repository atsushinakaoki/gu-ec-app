"""注文内容の fingerprint（DS-460）。テスト仕様書 TC-IT-ID-04 の前提となる性質を単体で確かめる。"""

from app.services.fingerprint import FingerprintLine, compute_fingerprint

BASE = dict(
    member_id=1,
    lines=[
        FingerprintLine("360411-09-M", 1, "SINGLE_FOLD", 700),
        FingerprintLine("360416-00-M", 2, None, None),
    ],
    delivery_method="HOME",
    placement_type=None,
    recipient=("テスト 太郎", "0700031", "旭川市", "09000000001"),
    payment_method="CREDIT_CARD",
    amounts=(6970, 300, 0, 0, 727, 7997),
)


def fp(**override):
    return compute_fingerprint(**{**BASE, **override})


def test_same_content_same_fingerprint():
    assert fp() == fp()


def test_line_order_does_not_matter():
    """カートへの投入順が違うだけで、別の注文と判定しない。"""
    assert fp() == fp(lines=list(reversed(BASE["lines"])))


def test_TC_IT_ID_04_same_total_different_length():
    """金額は同じで、すそ上げの丈だけが違う。本文（expectedTotal）の比較では見分けられない。"""
    changed = [FingerprintLine("360411-09-M", 1, "SINGLE_FOLD", 650), BASE["lines"][1]]
    assert fp() != fp(lines=changed)


def test_payment_method_changes_fingerprint():
    assert fp() != fp(payment_method="PAYPAY")


def test_recipient_changes_fingerprint():
    assert fp() != fp(recipient=("テスト 花子", "0700031", "旭川市", "09000000001"))


def test_placement_changes_fingerprint():
    assert fp() != fp(placement_type="FRONT_DOOR")


def test_member_changes_fingerprint():
    assert fp() != fp(member_id=2)


def test_fits_in_column():
    """orders.content_fingerprint は VARCHAR(64)。"""
    assert len(fp()) == 64
