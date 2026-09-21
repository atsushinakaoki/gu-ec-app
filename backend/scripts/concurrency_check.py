"""TC-IT-CC-01 排他制御の確認。

在庫1点の SKU に対して、複数の利用者が同時にカート投入を行い、
成功が1件だけであることを確かめる。

--- なぜ単なる連続リクエストでは検証にならないか ---

テスト仕様書 8.3.3（TE-02）で指摘した論点である。
for 文でリクエストを並べても、1件目が完了してから2件目が始まるため、
競合が再現しない。ロックが効いていなくても、すべて順番に処理されて
「成功1件・失敗N件」になってしまい、テストが通ってしまう。

そこで threading.Barrier を使う。全スレッドが barrier.wait() に到達するまで
誰も進まず、最後の1つが到着した瞬間に全員が同時に解放される。
送信のタイミングを、数ミリ秒の幅に押し込むための仕掛けである。

それでも完全な同時性は保証できない。ネットワークとサーバのスケジューリングが
入るためである。回数を重ねて、一度も破れないことを確かめる形にしている。
ロックを外して実行すると成功が2件以上になることを確認しておくと、
このテストが実際に競合を捉えていることの裏が取れる。

--- 使い方 ---

    uvicorn app.main:app --port 8000    # 別のターミナルで起動しておく
    python scripts/concurrency_check.py
"""

from __future__ import annotations

import pathlib
import sys
import threading

# scripts/ の中から実行されるため、親ディレクトリ（backend/）を
# import の探索先に加える。これがないと app パッケージを見つけられない。
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

BASE_URL = "http://localhost:8000"
TARGET_SKU = "360400-09-M"  # seed.sql で在庫を 1 にしてある
CONCURRENCY = 10
ROUNDS = 5


def reset_stock() -> None:
    """引当をすべて解放し、在庫1の状態に戻す。

    DB を直接触るため、アプリケーションの層を通さない。
    テストの前処理であり、本番の経路には存在しない操作である。
    """
    from sqlalchemy import text

    from app.db import engine

    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM reservation WHERE sku_id = :sku"), {"sku": TARGET_SKU}
        )
        conn.execute(
            text("DELETE FROM cart_item WHERE sku_id = :sku"), {"sku": TARGET_SKU}
        )
        conn.execute(
            text(
                "UPDATE stock SET quantity = 1 "
                "WHERE sku_id = :sku AND location_id = 1"
            ),
            {"sku": TARGET_SKU},
        )


def run_round(round_no: int) -> tuple[int, int, list[int]]:
    reset_stock()

    barrier = threading.Barrier(CONCURRENCY)
    results: list[int] = [0] * CONCURRENCY

    def worker(index: int) -> None:
        # 利用者ごとに別のクライアントを使う。
        # 同じ Cookie を共有すると同一カートへの追加になり、
        # 別人同士の競合にならない。
        with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
            payload = {"skuId": TARGET_SKU, "quantity": 1}
            barrier.wait()  # 全員がここに揃うまで待ち、同時に発射する
            try:
                res = client.post("/api/cart/items", json=payload)
                results[index] = res.status_code
            except httpx.HTTPError:
                results[index] = -1

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(CONCURRENCY)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    created = sum(1 for code in results if code == 201)
    conflict = sum(1 for code in results if code == 409)
    return created, conflict, results


def main() -> None:
    print(f"対象SKU: {TARGET_SKU}（在庫1）")
    print(f"同時リクエスト数: {CONCURRENCY}  試行回数: {ROUNDS}")
    print()

    failures = 0
    for round_no in range(1, ROUNDS + 1):
        created, conflict, results = run_round(round_no)
        ok = created == 1
        if not ok:
            failures += 1
        mark = "✔" if ok else "✘"
        other = [c for c in results if c not in (201, 409)]
        print(
            f"{mark} 第{round_no}回: 成功 {created} 件 / 在庫不足 {conflict} 件"
            + (f" / その他 {other}" if other else "")
        )

    print()
    if failures == 0:
        print(f"TC-IT-CC-01 合格。{ROUNDS}回すべてで成功が1件のみでした。")
    else:
        print(f"TC-IT-CC-01 不合格。{failures}/{ROUNDS} 回で成功が1件ではありません。")
        print("在庫1点に対して複数の引当が成立しています。排他制御を確認してください。")


if __name__ == "__main__":
    main()
