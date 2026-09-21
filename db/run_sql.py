"""
SQL ファイルを MySQL に対して実行する。

使い方:
    python db/run_sql.py db/schema.sql
    python db/run_sql.py db/seed.sql

接続情報は、同じディレクトリまたは親ディレクトリの .env から読み込む。
"""
import os
import re
import sys
from pathlib import Path

try:
    import pymysql
except ImportError:
    sys.exit(
        "pymysql が見つかりません。次のコマンドでインストールしてください。\n"
        "    pip install pymysql python-dotenv"
    )

try:
    from dotenv import load_dotenv
except ImportError:
    sys.exit(
        "python-dotenv が見つかりません。次のコマンドでインストールしてください。\n"
        "    pip install pymysql python-dotenv"
    )


def load_config() -> dict:
    """カレントディレクトリから上へ .env を探して読み込む。"""
    here = Path(__file__).resolve()
    for folder in [Path.cwd(), *here.parents]:
        candidate = folder / ".env"
        if candidate.exists():
            load_dotenv(candidate)
            print(f"[設定] {candidate} を読み込みました")
            break
    else:
        sys.exit(
            ".env が見つかりません。プロジェクト直下に .env を作成してください。\n"
            "（db/.env.example を参考にしてください）"
        )

    missing = [k for k in ("DB_HOST", "DB_USER", "DB_PASSWORD") if not os.getenv(k)]
    if missing:
        sys.exit(f".env に次の項目がありません: {', '.join(missing)}")

    return {
        "host": os.getenv("DB_HOST"),
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
        "port": int(os.getenv("DB_PORT", "3306")),
        "charset": "utf8mb4",
        "autocommit": True,
        # Azure Database for MySQL は SSL 接続を要求する。
        # DB_SSL=off とした場合のみ無効化する。
        "ssl": None if os.getenv("DB_SSL", "on").lower() == "off" else {"ssl": {}},
    }


def split_statements(sql: str) -> list[str]:
    """SQL ファイルを文単位に分割する。行コメントは除去する。"""
    lines = [re.sub(r"--.*$", "", line) for line in sql.splitlines()]
    body = "\n".join(lines)
    return [s.strip() for s in body.split(";") if s.strip()]


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("使い方: python db/run_sql.py <SQLファイル>")

    sql_path = Path(sys.argv[1])
    if not sql_path.exists():
        sys.exit(f"ファイルが見つかりません: {sql_path}")

    statements = split_statements(sql_path.read_text(encoding="utf-8"))
    print(f"[読込] {sql_path} — {len(statements)} 文")

    config = load_config()
    print(f"[接続] {config['user']}@{config['host']}:{config['port']}")

    conn = pymysql.connect(**config)
    try:
        with conn.cursor() as cur:
            for i, stmt in enumerate(statements, start=1):
                head = " ".join(stmt.split())[:70]
                try:
                    cur.execute(stmt)
                    print(f"  [{i:3d}/{len(statements)}] OK   {head}")
                except Exception as e:
                    print(f"  [{i:3d}/{len(statements)}] NG   {head}")
                    print(f"        → {e}")
                    raise
    finally:
        conn.close()

    print("[完了] すべての文を実行しました")


if __name__ == "__main__":
    main()
