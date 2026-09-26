"""注文確定の結合テスト（テスト仕様書 5.3〜5.7、5.9）。

本物の DB（Azure MySQL）に対して、注文確定の一連の流れを検証する。
テスト仕様書 8.3.1 のとおり、DB はモックに置き換えない。

アプリケーションはこのスクリプトの中で直接動かす（FastAPI の TestClient）。
uvicorn の起動は不要。決済代行事業者（PSP）はスタブであり、
成功・否決・タイムアウトを環境変数で切り替える。同じプロセスの中なので、
サーバを再起動せずに切り替えられる。

--- 時刻の扱い（テスト仕様書 8.4.3 TE-01） ---

引当の期限切れを再現するには60分待つ必要がある。
DB の時計は進められないので、代わりに引当の expires_at を過去の時刻に書き換える。
「時間を進める」のではなく「期限を手前にずらす」ことで同じ状態を作る。

--- 使い方 ---

    cd backend
    python scripts/order_flow_check.py

会員1・会員2の注文とカートを消してから始める。
使う SKU の在庫は、終了時に seed.sql の値へ戻す。
"""

from __future__ import annotations

import os
import pathlib
import sys
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services import payment_gateway  # noqa: E402

# 使う SKU と、seed.sql における在庫数（終了時に戻す）
PLENTY = "360416-00-M"  # ドライポンチクルーネックT。在庫 99
PANTS = "360411-09-M"  # スーパーワイドカーゴパンツ。すそ上げ可（800mm / 下限400mm）。在庫 40
LAST = "360417-09-S"  # シアーハイネックT。検証のため在庫を 1 にして使う。元は 12
ORIGINAL_STOCK = {PLENTY: 99, PANTS: 40, LAST: 12}

MEMBER_A = ("test1@example.com", 1)
MEMBER_B = ("test2@example.com", 2)
PASSWORD = "Passw0rd!"

RECIPIENT = {
    "name": "テスト 太郎",
    "postalCode": "070-0031",
    "address": "北海道旭川市一条通1丁目1-1",
    "phone": "090-0000-0001",
}

results: list[tuple[str, bool]] = []


# --- 準備と後片付け -----------------------------------------------------


def sql(statement: str, **params):
    with engine.begin() as conn:
        return conn.execute(text(statement), params)


def scalar(statement: str, **params):
    with engine.connect() as conn:
        return conn.execute(text(statement), params).scalar()


def reset(last_stock: int = 1) -> None:
    """会員1・2の注文とカートを消し、使う SKU の在庫を既知の値にする。"""
    members = "(1, 2)"
    skus = (PLENTY, PANTS, LAST)
    sql(
        f"""DELETE FROM reservation
            WHERE sku_id IN (:a, :b, :c)
               OR order_id IN (SELECT order_id FROM orders WHERE member_id IN {members})""",
        a=skus[0], b=skus[1], c=skus[2],
    )
    sql(f"DELETE FROM order_item WHERE order_id IN (SELECT order_id FROM orders WHERE member_id IN {members})")
    sql(f"DELETE FROM orders WHERE member_id IN {members}")
    sql(f"DELETE FROM cart_item WHERE cart_id IN (SELECT cart_id FROM cart WHERE member_id IN {members})")
    sql(f"DELETE FROM checkout WHERE cart_id IN (SELECT cart_id FROM cart WHERE member_id IN {members})")
    sql("UPDATE stock SET quantity = :q WHERE sku_id = :s AND location_id = 1", q=ORIGINAL_STOCK[PLENTY], s=PLENTY)
    sql("UPDATE stock SET quantity = :q WHERE sku_id = :s AND location_id = 1", q=ORIGINAL_STOCK[PANTS], s=PANTS)
    sql("UPDATE stock SET quantity = :q WHERE sku_id = :s AND location_id = 1", q=last_stock, s=LAST)
    payment_gateway.reset()
    os.environ["PSP_STUB_MODE"] = "success"
    os.environ["PSP_STUB_INQUIRY"] = "answer"


def restore() -> None:
    reset(last_stock=ORIGINAL_STOCK[LAST])


# --- 操作 ---------------------------------------------------------------


def login(email: str) -> TestClient:
    client = TestClient(app)
    res = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return client


def add(client: TestClient, sku: str, qty: int = 1, alteration: dict | None = None):
    body = {"skuId": sku, "quantity": qty}
    if alteration:
        body["alteration"] = alteration
    res = client.post("/api/cart/items", json=body)
    assert res.status_code == 201, res.text
    return res.json()


def checkout(client: TestClient, delivery="HOME", placement="NONE", payment="CREDIT_CARD") -> dict:
    res = client.post(
        "/api/checkout/delivery",
        json={"deliveryMethod": delivery, "placementType": placement, "recipient": RECIPIENT},
    )
    assert res.status_code == 200, res.text
    res = client.post("/api/checkout/payment", json={"paymentMethod": payment})
    assert res.status_code == 200, res.text
    res = client.get("/api/checkout/summary")
    assert res.status_code == 200, res.text
    return res.json()


def order(client: TestClient, summary: dict, key: str | None = None, total: int | None = None):
    return client.post(
        "/api/orders",
        json={"expectedTotal": summary["amounts"]["total"] if total is None else total},
        headers={"Idempotency-Key": key or summary["idempotencyKey"]},
    )


def stock(sku: str) -> int:
    return scalar("SELECT quantity FROM stock WHERE sku_id = :s AND location_id = 1", s=sku)


def orders_count(member_id: int = 1, status: str | None = None) -> int:
    if status:
        return scalar(
            "SELECT COUNT(*) FROM orders WHERE member_id = :m AND status = :st", m=member_id, st=status
        )
    return scalar("SELECT COUNT(*) FROM orders WHERE member_id = :m", m=member_id)


def reservation_statuses(order_number: str) -> list[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """SELECT r.status FROM reservation r
                   JOIN orders o ON o.order_id = r.order_id
                   WHERE o.order_number = :n ORDER BY r.status"""
            ),
            {"n": order_number},
        ).all()
    return [r[0] for r in rows]


def cart_count(member_id: int = 1) -> int:
    return scalar(
        """SELECT COUNT(*) FROM cart_item ci JOIN cart c ON c.cart_id = ci.cart_id
           WHERE c.member_id = :m""",
        m=member_id,
    )


def check(test_id: str, label: str, condition: bool, detail: object = "") -> None:
    results.append((test_id, bool(condition)))
    mark = "✔" if condition else "✘"
    print(f"  {mark} {test_id} {label}" + ("" if condition else f"\n      → {detail}"))


# --- シナリオ -----------------------------------------------------------


def scenario_success() -> None:
    print("\n5.3 注文確定・決済成功")
    reset()
    a = login(MEMBER_A[0])
    add(a, PANTS, 2, {"type": "SINGLE_FOLD", "lengthMm": 700})
    before = stock(PANTS)
    summary = checkout(a)
    res = order(a, summary)
    check("TC-IT-OK-01", "201 が返る", res.status_code == 201, res.text)
    number = res.json().get("orderNumber", "")
    check("TC-IT-OK-01", "在庫が注文数量ぶん減る", stock(PANTS) == before - 2, (before, stock(PANTS)))
    check("TC-IT-OK-01", "引当が CONFIRMED", reservation_statuses(number) == ["CONFIRMED"], reservation_statuses(number))
    check("TC-IT-OK-01", "注文が CONFIRMED", orders_count(1, "CONFIRMED") == 1)
    tx = scalar("SELECT payment_transaction_id FROM orders WHERE order_number = :n", n=number)
    check("TC-IT-OK-01", "取引IDが保存される", bool(tx), tx)
    check("TC-IT-OK-01", "カートが空になる", cart_count(1) == 0, cart_count(1))
    call = payment_gateway.calls()[-1]
    check("TC-IT-OK-10", "PSP への金額が Backend の算出額と一致", call[1] == summary["amounts"]["total"], call)
    check("TC-IT-OK-11", "PSP に注文番号が送られる", call[0] == number, call)

    # 注文時点の値のコピー
    sql("UPDATE product SET name = CONCAT(name, '（改）'), regular_price = regular_price + 1000 WHERE product_id = '360411'")
    try:
        detail = a.get(f"/api/orders/{number}").json()
        item = detail["items"][0]
        check("TC-IT-OK-20", "商品の価格を変えても注文の金額は変わらない", detail["amounts"]["total"] == summary["amounts"]["total"], detail["amounts"])
        check("TC-IT-OK-21", "商品名を変えても注文の商品名は変わらない", "（改）" not in item["productName"], item["productName"])
    finally:
        sql("UPDATE product SET name = REPLACE(name, '（改）', ''), regular_price = regular_price - 1000 WHERE product_id = '360411'")

    # 二重送信（成功後の再送）
    again = order(a, summary)
    check("TC-IT-ID-01", "同じキーの再送は最初の結果を返す", again.status_code == 201 and again.json().get("orderNumber") == number, again.text)
    check("TC-IT-ID-10", "決済の要求は1回だけ", len([c for c in payment_gateway.calls() if c[0] == number]) == 1)
    check("TC-IT-ID-12", "注文は1件だけ", orders_count(1) == 1)

    # 他人の注文
    b = login(MEMBER_B[0])
    check("TC-IT-AZ-01", "他人の注文は 404", b.get(f"/api/orders/{number}").status_code == 404)
    check("TC-IT-AZ-20", "他人の注文と存在しない注文で応答が同一",
          b.get(f"/api/orders/{number}").json() == b.get("/api/orders/GU000000XXXXXXXX").json())


def scenario_idempotency() -> None:
    print("\n5.6 注文確定の二重送信")
    # ID-04: 同じキーで内容が違う
    reset()
    a = login(MEMBER_A[0])
    add(a, PANTS, 1, {"type": "SINGLE_FOLD", "lengthMm": 700})
    summary = checkout(a)
    res = order(a, summary)
    assert res.status_code == 201, res.text
    add(a, PANTS, 1, {"type": "SINGLE_FOLD", "lengthMm": 650})  # 金額は同じ、丈だけ違う
    checkout(a)
    res = order(a, summary)  # 1件目と同じキー
    check("TC-IT-ID-04", "同じキー・異なる内容は 422", res.status_code == 422, res.text)

    # ID-05: 違うキー・同じ内容
    reset()
    a = login(MEMBER_A[0])
    add(a, PLENTY)
    r1 = order(a, checkout(a))
    add(a, PLENTY)
    r2 = order(a, checkout(a))
    check("TC-IT-ID-05", "違うキーなら2件の注文", r1.status_code == 201 and r2.status_code == 201 and orders_count(1) == 2)

    # ID-02: 同じキー・同じ内容を同時に送る。
    # タイミングに依存する不具合を1回で捕まえられるとは限らないため、5回繰り返す
    # （実際に、1回目の実装はここで 422 を返すことがあった）
    rounds_ok = 0
    all_codes = []
    for _ in range(5):
        reset()
        a1, a2 = login(MEMBER_A[0]), login(MEMBER_A[0])  # 同じ会員。同じカートを見る
        add(a1, PLENTY, 2)
        summary = checkout(a1)
        before = stock(PLENTY)
        barrier = threading.Barrier(2)
        codes: list[int] = []

        def fire(client: TestClient) -> None:
            barrier.wait()
            codes.append(order(client, summary).status_code)

        threads = [threading.Thread(target=fire, args=(c,)) for c in (a1, a2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        all_codes.append(sorted(codes))
        rounds_ok += (
            orders_count(1) == 1
            and stock(PLENTY) == before - 2
            and sorted(codes)[0] == 201
            and set(codes) <= {201, 409}
        )
    check("TC-IT-ID-02", "同時送信を5回。いずれも注文1件・減算1回・応答は201と(201か409)",
          rounds_ok == 5, all_codes)

    # 金額の改ざん
    reset()
    a = login(MEMBER_A[0])
    add(a, PLENTY)
    summary = checkout(a)
    before = stock(PLENTY)
    res = order(a, summary, total=1)
    check("DS-628", "金額が違えば 422", res.status_code == 422, res.text)
    check("DS-629", "正しい金額を応答に含めない", str(summary["amounts"]["total"]) not in res.text, res.text)
    check("DS-628", "在庫は変わらない", stock(PLENTY) == before)


def scenario_decline() -> None:
    print("\n5.4 注文確定・決済失敗")
    reset()
    a = login(MEMBER_A[0])
    add(a, PANTS, 2)
    before = stock(PANTS)
    summary = checkout(a)
    os.environ["PSP_STUB_MODE"] = "decline"
    res = order(a, summary)
    check("TC-IT-NG-01", "402 が返る", res.status_code == 402, res.text)
    number = scalar("SELECT order_number FROM orders WHERE member_id = 1")
    check("TC-IT-NG-01", "在庫が元に戻る", stock(PANTS) == before, (before, stock(PANTS)))
    check("TC-IT-NG-01", "引当が RELEASED", reservation_statuses(number) == ["RELEASED"], reservation_statuses(number))
    check("TC-IT-NG-01", "注文が FAILED", orders_count(1, "FAILED") == 1)
    check("TC-IT-NG-01", "カートは残る", cart_count(1) == 1, cart_count(1))

    os.environ["PSP_STUB_MODE"] = "success"
    res = order(a, checkout(a, payment="PAYPAY"))
    check("TC-IT-NG-02", "支払方法を変えて再試行すると成立", res.status_code == 201, res.text)
    check("TC-IT-NG-02", "在庫の減算は1回ぶんだけ", stock(PANTS) == before - 2, (before, stock(PANTS)))


def scenario_timeout() -> None:
    print("\n5.5 決済のタイムアウト")
    for mode, test_id, final in (
        ("timeout_then_success", "TC-IT-TO-02", "CONFIRMED"),
        ("timeout_then_decline", "TC-IT-TO-03", "FAILED"),
    ):
        reset()
        a = login(MEMBER_A[0])
        add(a, PANTS, 2)
        before = stock(PANTS)
        summary = checkout(a)
        os.environ["PSP_STUB_MODE"] = mode
        res = order(a, summary)
        number = res.json().get("orderNumber", "")
        if mode == "timeout_then_success":
            check("TC-IT-TO-01", "202 が返る（失敗扱いにしない）", res.status_code == 202, res.text)
            check("TC-IT-TO-01", "在庫は減ったまま", stock(PANTS) == before - 2)
            check("TC-IT-TO-01", "注文は PENDING_PAYMENT", orders_count(1, "PENDING_PAYMENT") == 1)
            check("TC-IT-TO-01", "引当は CONFIRMED のまま", reservation_statuses(number) == ["CONFIRMED"], reservation_statuses(number))
            # 注文を始める時点で照会を試みるので、照会にも応答しない状態にして確かめる
            os.environ["PSP_STUB_INQUIRY"] = "timeout"
            try:
                blocked = a.post("/api/orders", json={"expectedTotal": 1}, headers={"Idempotency-Key": "another"})
                check("【未確定13】", "決済待ちの間は新しい注文を受け付けない（暫定）", blocked.status_code == 409, blocked.text)
                check("TC-IT-TO-04", "照会も応答しなければ決済待ちのまま", orders_count(1, "PENDING_PAYMENT") == 1)
            finally:
                os.environ["PSP_STUB_INQUIRY"] = "answer"
        detail = a.get(f"/api/orders/{number}").json()
        expected_stock = before - 2 if final == "CONFIRMED" else before
        check(test_id, f"照会の結果、注文が {final} になる", detail.get("status") == final, detail)
        check(test_id, "在庫が正しい", stock(PANTS) == expected_stock, (expected_stock, stock(PANTS)))


def scenario_expiry() -> None:
    print("\n5.7 引当期限切れ後の注文")

    # 最後の1点を自分が引き当てている（変異テストで見逃したため追加）
    reset(last_stock=1)
    a = login(MEMBER_A[0])
    add(a, LAST)
    res = order(a, checkout(a))
    check("LAST-01", "在庫1を自分が引当済みなら注文できる", res.status_code == 201, res.text)

    # EX-02: 期限切れ。在庫はある
    reset(last_stock=1)
    a = login(MEMBER_A[0])
    add(a, LAST)
    summary = checkout(a)
    sql("UPDATE reservation SET expires_at = NOW() - INTERVAL 1 SECOND WHERE sku_id = :s AND status = 'ACTIVE'", s=LAST)
    res = order(a, summary)
    check("TC-IT-EX-02", "期限切れでも在庫があれば成立", res.status_code == 201, res.text)
    check("TC-IT-EX-02", "在庫 1 → 0", stock(LAST) == 0, stock(LAST))

    # EX-03: 期限切れ。その間に他人が確保した
    reset(last_stock=1)
    a = login(MEMBER_A[0])
    add(a, LAST)
    summary = checkout(a)
    sql("UPDATE reservation SET expires_at = NOW() - INTERVAL 1 SECOND WHERE sku_id = :s AND status = 'ACTIVE'", s=LAST)
    b = login(MEMBER_B[0])
    add(b, LAST)
    res = order(a, summary)
    check("TC-IT-EX-03", "409 で、足りない SKU を示す", res.status_code == 409 and LAST in res.text, res.text)
    check("TC-IT-EX-03", "在庫は変わらない", stock(LAST) == 1, stock(LAST))


def scenario_merge() -> None:
    print("\n5.8 未ログインカートの統合")
    reset()
    # 会員として、すそ上げ700mmのパンツを2点入れておく
    member_session = login(MEMBER_A[0])
    add(member_session, PANTS, 2, {"type": "SINGLE_FOLD", "lengthMm": 700})

    # 別の端末で、ログインせずにカートへ入れる
    guest = TestClient(app)
    add(guest, PLENTY, 1)
    add(guest, PANTS, 1, {"type": "SINGLE_FOLD", "lengthMm": 700})  # 会員側と同じ明細
    add(guest, PANTS, 1, {"type": "SINGLE_FOLD", "lengthMm": 650})  # 丈が違う＝別の明細
    guest_expiry = scalar(
        "SELECT MIN(expires_at) FROM reservation WHERE sku_id = :s AND status = 'ACTIVE'", s=PLENTY
    )

    # その端末でログインし、統合する
    res = guest.post("/api/auth/login", json={"email": MEMBER_A[0], "password": PASSWORD})
    assert res.status_code == 200, res.text
    merged = guest.post("/api/cart/merge")
    check("TC-IT-MG", "統合が成功する", merged.status_code == 200, merged.text)
    discarded = merged.json().get("discarded", [])
    check("DS-425", "破棄した明細（同じ丈のパンツ1件）を返す",
          len(discarded) == 1 and discarded[0]["alterationLengthMm"] == 700, discarded)

    cart = guest.get("/api/cart").json()["items"]
    lines = sorted((i["skuId"], (i["alteration"] or {}).get("lengthMm"), i["quantity"]) for i in cart)
    check("DS-424", "同じ明細は合算せず会員側（2点）を残す", (PANTS, 700, 2) in lines, lines)
    check("DS-428", "丈が違う明細は別物として移る", (PANTS, 650, 1) in lines, lines)
    check("TC-IT-MG", "未ログインの別商品も移る", (PLENTY, None, 1) in lines, lines)
    released = scalar(
        "SELECT COUNT(*) FROM reservation WHERE sku_id = :s AND status = 'RELEASED'", s=PANTS
    )
    check("DS-426", "破棄した明細の引当を解放する", released == 1, released)
    after = scalar(
        "SELECT MIN(expires_at) FROM reservation WHERE sku_id = :s AND status = 'ACTIVE'", s=PLENTY
    )
    check("DS-427", "ログインで引当期限を延ばさない", after == guest_expiry, (guest_expiry, after))


def race(*fns):
    """渡した関数を、できるだけ同時に実行する。"""
    barrier = threading.Barrier(len(fns))
    out = [None] * len(fns)

    def run(i, fn):
        barrier.wait()
        out[i] = fn()

    threads = [threading.Thread(target=run, args=(i, fn)) for i, fn in enumerate(fns)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return out


def scenario_review_findings() -> None:
    """Gemini と ChatGPT のコードレビューで見つかった欠陥の再発防止。

    どれも、指摘を受けて実際に再現させた手順をそのままテストにしたもの。
    タイミングに依存するため、何回か繰り返す。
    """
    print("\nレビュー指摘の再発防止")

    # --- Gemini-1 / ChatGPT-4：同じカートへの同時投入 ---
    ok_new, ok_add = 0, 0
    detail = []
    for _ in range(5):
        reset()
        a1 = login(MEMBER_A[0])
        a2 = login(MEMBER_A[0])  # 同じ会員＝同じカート
        codes = race(
            lambda: a1.post("/api/cart/items", json={"skuId": PLENTY, "quantity": 6}).status_code,
            lambda: a2.post("/api/cart/items", json={"skuId": PLENTY, "quantity": 6}).status_code,
        )
        lines = [(i["quantity"]) for i in a1.get("/api/cart").json()["items"] if i["skuId"] == PLENTY]
        reserved = scalar(
            "SELECT COALESCE(SUM(quantity),0) FROM reservation WHERE sku_id=:s AND status='ACTIVE'", s=PLENTY
        )
        ok_new += lines == [6] and reserved == 6 and sorted(codes) == [201, 400]
        detail.append((sorted(codes), lines, reserved))

        reset()
        a1, a2 = login(MEMBER_A[0]), login(MEMBER_A[0])
        add(a1, PLENTY, 4)
        codes = race(
            lambda: a1.post("/api/cart/items", json={"skuId": PLENTY, "quantity": 5}).status_code,
            lambda: a2.post("/api/cart/items", json={"skuId": PLENTY, "quantity": 5}).status_code,
        )
        lines = [(i["quantity"]) for i in a1.get("/api/cart").json()["items"] if i["skuId"] == PLENTY]
        reserved = scalar(
            "SELECT COALESCE(SUM(quantity),0) FROM reservation WHERE sku_id=:s AND status='ACTIVE'", s=PLENTY
        )
        ok_add += lines == [9] and reserved == 9 and sorted(codes) == [201, 400]
        detail.append((sorted(codes), lines, reserved))
    check("Gemini-1", "同時投入でも明細は1行・10点の上限を守る（5回）", ok_new == 5, detail[0::2])
    check("Gemini-1", "既存明細への同時追加で、明細の数量と引当が一致する（5回）", ok_add == 5, detail[1::2])

    # --- ChatGPT-1：2つのタブから同時に注文 ---
    ok = 0
    detail = []
    for variant in ("同じ内容の確認画面", "片方が支払方法を変えた後"):
        for _ in range(3):
            reset()
            a, b = login(MEMBER_A[0]), login(MEMBER_A[0])
            add(a, PANTS, 2)
            before = stock(PANTS)
            sa = checkout(a)
            if variant == "同じ内容の確認画面":
                sb = b.get("/api/checkout/summary").json()
            else:
                b.post("/api/checkout/payment", json={"paymentMethod": "PAYPAY"})
                sb = b.get("/api/checkout/summary").json()
            codes = race(lambda: order(a, sa).status_code, lambda: order(b, sb).status_code)
            charges = len(payment_gateway.calls())
            good = orders_count(1) == 1 and charges == 1 and stock(PANTS) == before - 2 and 201 in codes
            ok += good
            detail.append((variant, sorted(codes), orders_count(1), charges, before - stock(PANTS)))
    check("ChatGPT-1", "2タブから同時に注文しても、注文1件・決済1回・減算1回（6回）", ok == 6, detail)

    # --- ChatGPT-2：否決が判明した注文を同時に照会 ---
    ok = 0
    detail = []
    for _ in range(3):
        reset()
        a = login(MEMBER_A[0])
        add(a, PANTS, 2)
        before = stock(PANTS)
        summary = checkout(a)
        os.environ["PSP_STUB_MODE"] = "timeout_then_decline"
        number = order(a, summary).json()["orderNumber"]
        a2 = login(MEMBER_A[0])
        race(lambda: a.get(f"/api/orders/{number}").status_code, lambda: a2.get(f"/api/orders/{number}").status_code)
        ok += stock(PANTS) == before
        detail.append((before, stock(PANTS)))
    check("ChatGPT-2", "同時に照会しても、在庫は1回だけ戻る（3回）", ok == 3, detail)

    # --- ChatGPT-3：確認画面の後に、同額のまま中身を差し替える ---
    reset()
    a = login(MEMBER_A[0])
    add(a, PANTS, 1, {"type": "SINGLE_FOLD", "lengthMm": 700})
    summary = checkout(a)
    item = a.get("/api/cart").json()["items"][0]["cartItemId"]
    a.delete(f"/api/cart/items/{item}")
    add(a, PANTS, 1, {"type": "SINGLE_FOLD", "lengthMm": 650})
    res = order(a, summary)
    check("ChatGPT-3", "確認画面と中身が違えば、同額でも注文させない（422）", res.status_code == 422, res.text)
    check("ChatGPT-3", "注文は作られない", orders_count(1) == 0)

    # --- ChatGPT-5：注文確定と同時に、同じ明細へ追加する ---
    ok = 0
    detail = []
    for _ in range(5):
        reset()
        a, a2 = login(MEMBER_A[0]), login(MEMBER_A[0])
        add(a, PANTS, 1)
        before = stock(PANTS)
        summary = checkout(a)
        codes = race(
            lambda: order(a, summary).status_code,
            lambda: a2.post("/api/cart/items", json={"skuId": PANTS, "quantity": 1}).status_code,
        )
        ordered = scalar(
            "SELECT COALESCE(SUM(oi.quantity),0) FROM order_item oi JOIN orders o ON o.order_id=oi.order_id WHERE o.member_id=1"
        )
        confirmed = scalar(
            "SELECT COALESCE(SUM(r.quantity),0) FROM reservation r JOIN orders o ON o.order_id=r.order_id WHERE o.member_id=1 AND r.status='CONFIRMED'"
        )
        cart_qty = sum(i["quantity"] for i in a.get("/api/cart").json()["items"])
        # カート明細に結び付いた引当だけでなく、その商品の有効な引当をすべて数える。
        # 明細から切り離された「持ち主のいない引当」も在庫を塞ぐので、見逃してはならない。
        # （最初の版はカート明細とつないで数えており、変異テストでこの見逃しが判明した）
        active = scalar(
            "SELECT COALESCE(SUM(quantity),0) FROM reservation WHERE sku_id=:s AND status='ACTIVE'", s=PANTS
        )
        good = ordered == confirmed == before - stock(PANTS) and cart_qty == active
        ok += good
        detail.append((sorted(codes), ordered, confirmed, before - stock(PANTS), cart_qty, active))
    check("ChatGPT-5", "注文と追加が重なっても、注文・引当・在庫・カートが一致する（5回）", ok == 5, detail)

    # --- ChatGPT-5（確定的な再現）：決済待ちの明細へ、同じ商品を追加する ---
    # 上の同時実行テストは、追加が先に勝つ回が多く、欠陥の経路を通らないことがある
    # （修正を外しても検出できない回があった）。決済待ちの状態を先に作り、順番を固定して確かめる。
    from app.db import SessionLocal
    from app.services.order_service import reconcile_pending_orders

    reset()
    a = login(MEMBER_A[0])
    add(a, PANTS, 1)
    summary = checkout(a)
    os.environ["PSP_STUB_MODE"] = "timeout_then_success"
    os.environ["PSP_STUB_INQUIRY"] = "timeout"
    res = order(a, summary)
    assert res.status_code == 202, res.text
    add(a, PANTS, 1)  # 決済待ちの明細と同じ商品・同じ内容
    lines_pending = len(a.get("/api/cart").json()["items"])
    os.environ["PSP_STUB_INQUIRY"] = "answer"
    db = SessionLocal()
    try:
        reconcile_pending_orders(db, min_age_seconds=0)
    finally:
        db.close()
    cart_qty = sum(i["quantity"] for i in a.get("/api/cart").json()["items"])
    active = scalar(
        "SELECT COALESCE(SUM(quantity),0) FROM reservation WHERE sku_id=:s AND status='ACTIVE'", s=PANTS
    )
    orphan = scalar(
        "SELECT COUNT(*) FROM reservation WHERE sku_id=:s AND status='ACTIVE' AND cart_item_id IS NULL", s=PANTS
    )
    check("ChatGPT-5", "決済待ちの明細には合算せず、別の明細として追加する", lines_pending == 2, lines_pending)
    check("ChatGPT-5", "決済が成立した後も、追加した1点がカートに残り、引当と一致する",
          orders_count(1, "CONFIRMED") == 1 and cart_qty == 1 and active == 1 and orphan == 0,
          (orders_count(1, "CONFIRMED"), cart_qty, active, orphan))

    # --- ChatGPT-6：利用者が画面を開かなくても、決済待ちが解消される ---
    from app.db import SessionLocal
    from app.services.order_service import reconcile_pending_orders

    reset()
    a = login(MEMBER_A[0])
    add(a, PANTS, 2)
    before = stock(PANTS)
    summary = checkout(a)
    os.environ["PSP_STUB_MODE"] = "timeout_then_decline"
    order(a, summary)
    db = SessionLocal()
    try:
        counts = reconcile_pending_orders(db, min_age_seconds=0)
    finally:
        db.close()
    check("ChatGPT-6", "定期照会で、否決された注文が FAILED になり在庫が戻る",
          orders_count(1, "FAILED") == 1 and stock(PANTS) == before, (counts, before, stock(PANTS)))

    # --- ChatGPT-7：会員のカートを同時に初めて作る ---
    ok = 0
    for _ in range(3):
        sql("DELETE FROM cart_item WHERE cart_id IN (SELECT cart_id FROM cart WHERE member_id = 2)")
        sql("DELETE FROM checkout WHERE cart_id IN (SELECT cart_id FROM cart WHERE member_id = 2)")
        sql("DELETE FROM cart WHERE member_id = 2")
        b1, b2 = login(MEMBER_B[0]), login(MEMBER_B[0])
        codes = race(lambda: b1.get("/api/cart").status_code, lambda: b2.get("/api/cart").status_code)
        ok += codes == [200, 200] and scalar("SELECT COUNT(*) FROM cart WHERE member_id = 2") == 1
    check("ChatGPT-7", "会員カートの同時作成でもエラーにならない（3回）", ok == 3)

    # --- Gemini-4：決済待ちの間に価格が変わっても、再送には「処理中」を返す ---
    reset()
    a = login(MEMBER_A[0])
    add(a, PLENTY, 1)
    summary = checkout(a)
    os.environ["PSP_STUB_MODE"] = "timeout_then_success"
    os.environ["PSP_STUB_INQUIRY"] = "timeout"
    order(a, summary)
    sql("UPDATE product SET regular_price = regular_price + 100 WHERE product_id = '360416'")
    try:
        res = order(a, summary)
        check("Gemini-4", "決済待ちの注文への再送は、内容の比較より先に 409", res.status_code == 409, res.text)
    finally:
        sql("UPDATE product SET regular_price = regular_price - 100 WHERE product_id = '360416'")


def main() -> None:
    print("注文確定の結合テスト（Azure MySQL に接続して実行）")
    try:
        scenario_success()
        scenario_idempotency()
        scenario_decline()
        scenario_timeout()
        scenario_expiry()
        scenario_merge()
        scenario_review_findings()
    finally:
        restore()

    passed = sum(ok for _, ok in results)
    print(f"\n{passed}/{len(results)} 件合格")
    if passed != len(results):
        print("不合格の項目があります。上の ✘ を確認してください。")


if __name__ == "__main__":
    main()
