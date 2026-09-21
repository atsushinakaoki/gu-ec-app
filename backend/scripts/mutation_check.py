"""変異テスト（ミューテーションテスト）。

実装にわざと小さなバグを1つずつ仕込み、単体テストがそれを検出できるかを確かめる。
テストが合格していても、それはテストが正しいことの証明にはならない。
「バグがあれば落ちる」ことを確かめて初めて、テストが機能していると言える。

AI にテストを書かせると、実装が通る形のテストを書く傾向がある（講師の指摘）。
これはその対策として、テスト自体を検証するためのものである。

実行すると各ファイルを一時的に書き換え、終了時に必ず元に戻す。

    cd backend
    python scripts/mutation_check.py
"""

import os
import pathlib
import subprocess
import sys

# backend/ を基準に動かす
os.chdir(pathlib.Path(__file__).resolve().parents[1])

mutants = [
  ("app/services/stock.py", "return reservation.expires_at > now", "return reservation.expires_at >= now",
   "期限ちょうどを有効扱い（> を >= に）"),
  ("app/services/stock.py", "if reservation.status != STATUS_ACTIVE:\n        return False",
   "if reservation.status == STATUS_RELEASED:\n        return False\n    if reservation.status == STATUS_CONFIRMED:\n        return True",
   "CONFIRMED も減算する（二重減算）"),
  ("app/services/stock.py", "return requested_quantity <= available_quantity", "return requested_quantity < available_quantity",
   "最後の1点を買えない（<= を < に）"),
  ("app/services/pricing.py", "if subtotal_ex_tax >= FREE_SHIPPING_THRESHOLD_EX_TAX:", "if subtotal_ex_tax > FREE_SHIPPING_THRESHOLD_EX_TAX:",
   "送料無料の境界を5,001円からに"),
  ("app/services/pricing.py", "shipping_fee = resolve_shipping_fee(delivery_method, subtotal)", "shipping_fee = resolve_shipping_fee(delivery_method, subtotal + alteration_fee)",
   "送料判定に加工料を含める"),
  ("app/services/pricing.py", "rounding=ROUND_FLOOR", "rounding='ROUND_HALF_UP'",
   "消費税を四捨五入に"),
  ("app/services/pricing.py", "    tax = calc_tax(taxable)\n", "    tax = sum(calc_tax(i.goods_amount) for i in items) + calc_tax(taxable - subtotal)\n",
   "消費税を明細ごとに端数処理"),
  ("app/services/reservation.py", "        if self.status == STATUS_RELEASED:\n            return  # 何もしない。例外も投げない",
   "        if self.status == STATUS_RELEASED:\n            raise InvalidStateError('x')",
   "release() を冪等でなくする"),
  ("app/services/reservation.py", "        if self.status != STATUS_ACTIVE:\n            raise InvalidStateError(\n                f\"{self.status} の引当を確定することはできません\"\n            )\n        self.status = STATUS_CONFIRMED",
   "        self.status = STATUS_CONFIRMED",
   "confirm() の状態チェックを外す"),
  ("app/services/alteration.py", "if not spec.alterable:", "if False:",
   "加工不可の商品への指定を通す"),
  ("app/services/alteration.py", "if length_mm % ALTERATION_STEP_MM != 0:", "if False:",
   "5mm刻みの検証を外す"),
  ("app/services/payment_policy.py", "        if placement_type is not None:\n            return UnavailableReason(\n                caused_by=CAUSED_BY_PLACEMENT,\n                message=\"置き配を指定した場合、代金引換えは利用できません\",",
   "        if False:\n            return UnavailableReason(\n                caused_by=CAUSED_BY_PLACEMENT,\n                message=\"置き配を指定した場合、代金引換えは利用できません\",",
   "置き配×代引を通す"),
]
killed = 0
for path, old, new, label in mutants:
    p = pathlib.Path(path)
    orig = p.read_text(encoding="utf-8")
    assert old in orig, f"パターン不一致: {label}"
    p.write_text(orig.replace(old, new, 1), encoding="utf-8")
    try:
        # Windows では子プロセスの出力が既定で Shift-JIS になる。
        # 子プロセスに UTF-8 での出力を強制し、読む側も UTF-8 で揃える。
        # 読み取りに失敗した文字は置換し、判定（終了コード）には影響させない。
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "addopts="],
            capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
        )
        failed = [l.split("::")[-1].split(" ")[0] for l in (r.stdout or "").splitlines() if l.startswith("FAILED")]
        ok = r.returncode != 0
        killed += ok
        print(f"{'✔ 検出' if ok else '✘ 見逃し'}  {label}")
        for f in failed[:3]: print(f"      ← {f}")
    finally:
        p.write_text(orig, encoding="utf-8")
print(f"\n{killed}/{len(mutants)} 件の仕込みバグを検出")
