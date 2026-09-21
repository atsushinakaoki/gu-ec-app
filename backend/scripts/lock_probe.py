"""排他制御の診断。

concurrency_check.py が不合格になったとき、原因の切り分けに使う。
「ロックが取れていないのか」「ロックは取れているが見えているデータが
古いのか」を区別する。

    python scripts/lock_probe.py
"""

from __future__ import annotations

import datetime as dt
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from sqlalchemy import select, text  # noqa: E402

from app.db import SessionLocal, engine  # noqa: E402
from app.models import Reservation, Stock  # noqa: E402

SKU = "360400-09-M"
LOC = 1


def line(title: str) -> None:
    print()
    print("=" * 62)
    print(title)
    print("=" * 62)


def probe_1_environment() -> None:
    line("1. 接続の設定を確認する")
    with engine.connect() as conn:
        iso = conn.execute(text("SELECT @@transaction_isolation")).scalar_one()
        ver = conn.execute(text("SELECT VERSION()")).scalar_one()
        autocommit = conn.execute(text("SELECT @@autocommit")).scalar_one()
    print(f"  MySQL バージョン : {ver}")
    print(f"  分離レベル       : {iso}")
    print(f"  autocommit       : {autocommit}")
    if iso != "READ-COMMITTED":
        print("  ⚠ READ-COMMITTED になっていません。db.py の変更が効いていません。")


def probe_2_sql() -> None:
    line("2. 実際に発行されるSQLを確認する")
    stmt = (
        select(Stock)
        .where(Stock.location_id == LOC, Stock.sku_id.in_([SKU]))
        .order_by(Stock.sku_id)
        .with_for_update()
    )
    sql = str(stmt.compile(engine)).replace("\n", " ")
    print(f"  {sql}")
    if "FOR UPDATE" not in sql.upper():
        print("  ⚠ FOR UPDATE が付いていません。ロックは取得されていません。")
    else:
        print("  FOR UPDATE が付いています。")


def probe_3_lock() -> None:
    """ロックが実際に他の接続を待たせるか。"""
    line("3. ロックが他の接続を待たせるか")

    stmt = (
        select(Stock)
        .where(Stock.location_id == LOC, Stock.sku_id.in_([SKU]))
        .order_by(Stock.sku_id)
        .with_for_update()
    )

    session_a = SessionLocal()
    session_b = SessionLocal()
    try:
        session_a.execute(stmt).all()
        print("  A: stock 行を FOR UPDATE でロックしました（保持したまま）")

        # 待たされることを確認したいので、待ち時間の上限を3秒に縮める
        session_b.execute(text("SET SESSION innodb_lock_wait_timeout = 3"))
        started = time.monotonic()
        try:
            session_b.execute(stmt).all()
            elapsed = time.monotonic() - started
            print(f"  B: {elapsed:.2f}秒で取得できてしまいました")
            print("  ✘ ロックが効いていません。これが不合格の原因です。")
        except Exception as exc:  # noqa: BLE001
            elapsed = time.monotonic() - started
            name = type(exc).__name__
            print(f"  B: {elapsed:.2f}秒 待たされました（{name}）")
            print("  ✔ ロックは正しく効いています。")
    finally:
        session_a.rollback()
        session_b.rollback()
        session_a.close()
        session_b.close()


def probe_4_visibility() -> None:
    """ロック解放後に、他の接続が入れたデータが見えるか。"""
    line("4. 他の接続がコミットした引当が見えるか")

    session_a = SessionLocal()
    session_b = SessionLocal()
    try:
        # 前提を揃える
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM reservation WHERE sku_id = :s"), {"s": SKU}
            )

        # B が先にトランザクションを開始し、テーブルを1回読む。
        # REPEATABLE READ なら、この時点のスナップショットが固定される。
        before = session_b.execute(
            select(Reservation).where(Reservation.sku_id == SKU)
        ).scalars().all()
        print(f"  B: トランザクション開始。引当 {len(before)} 件")

        # A が引当を入れてコミットする
        now = session_a.execute(text("SELECT NOW()")).scalar_one()
        session_a.add(
            Reservation(
                sku_id=SKU,
                location_id=LOC,
                quantity=1,
                status="ACTIVE",
                expires_at=now + dt.timedelta(minutes=60),
            )
        )
        session_a.commit()
        print("  A: 引当を1件 INSERT してコミットしました")

        # B が同じトランザクションのまま読み直す
        after = session_b.execute(
            select(Reservation).where(Reservation.sku_id == SKU)
        ).scalars().all()
        print(f"  B: 同じトランザクションのまま読み直し → 引当 {len(after)} 件")

        if len(after) == 1:
            print("  ✔ 見えています。分離レベルは想定どおりです。")
        else:
            print("  ✘ 見えていません。古いスナップショットを読んでいます。")
    finally:
        session_a.rollback()
        session_b.rollback()
        session_a.close()
        session_b.close()
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM reservation WHERE sku_id = :s"), {"s": SKU})


def main() -> None:
    probe_1_environment()
    probe_2_sql()
    probe_3_lock()
    probe_4_visibility()
    print()


if __name__ == "__main__":
    main()
