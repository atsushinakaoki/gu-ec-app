"""画面を通した購入の流れ（テスト仕様書 6章 ユーザーテストの自動化）。

本物のブラウザ（Chromium）を動かし、利用者と同じ操作で購入を最後まで行う。

  TC-UAT-N2  すそ上げを指定した購入
  TC-UAT-N3  未ログインでカートに入れた後のログイン（カートの引き継ぎ）
  TC-UAT-E3  選択できない支払方法（置き配 × 後払い・代引）と、その理由の表示

事前準備（初回のみ）:
    pip install playwright
    python -m playwright install chromium

実行（Backend と Frontend を起動した状態で）:
    python frontend/e2e/purchase_flow.py

注意：会員1（test1@example.com）で実際に注文する。在庫が1点減る。
"""

from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

BASE = "http://localhost:3000"
PASSWORD = "Passw0rd!"
PRODUCT = "360400"  # ワイドストレートスラックス。すそ上げ可、BLACK-XL は在庫0

results: list[tuple[str, bool]] = []


def check(test_id: str, label: str, ok: bool, detail: object = "") -> None:
    results.append((test_id, ok))
    print(f"  {'✔' if ok else '✘'} {test_id} {label}" + ("" if ok else f"\n      → {detail}"))


def main() -> None:
    console_errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900}, locale="ja-JP")
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append(str(e)))

        print("\n商品詳細：選択肢の依存関係")
        page.goto(f"{BASE}/products/{PRODUCT}")
        page.wait_for_selector(".swatch")
        button = page.locator("button.btn-block")
        check("FR-531", "カラー未選択ならボタンに理由が出る", button.inner_text() == "カラーを選択してください", button.inner_text())
        page.locator('.swatch[aria-label="BLACK"]').click()
        check("FR-531", "サイズ未選択ならボタンに理由が出る", button.inner_text() == "サイズを選択してください", button.inner_text())
        check("5.3", "在庫切れのサイズ（XL）は選べない", page.locator(".size", has_text="XL").is_disabled())
        page.locator(".size", has_text="L").first.click()
        check("FR-564-02", "加工方法を選ぶまで丈は選べない", page.locator(".alteration select").is_disabled())
        page.get_by_label("シングル", exact=False).check()
        check("FR-564-02", "加工方法を選ぶと丈が選べる", not page.locator(".alteration select").is_disabled())
        check("FR-564-05", "返品不可をその場で示す", page.locator("text=交換・返品ができません").count() == 1)
        page.locator(".alteration select").select_option("700")

        print("\nTC-UAT-N3：未ログインでカートに入れ、ログインで引き継ぐ")
        button.click()
        page.wait_for_selector(".notice-ok")
        check("TC-UAT-N2", "未ログインでもカートに入る", "カートに追加しました" in page.locator(".notice-ok").inner_text())
        page.goto(f"{BASE}/cart")
        page.wait_for_selector(".line")
        page.get_by_role("button", name="購入手続きへ").click()
        page.wait_for_url("**/login**")
        page.fill("#email", "test1@example.com")
        page.fill("#password", PASSWORD)
        page.get_by_role("button", name="ログイン").click()
        page.wait_for_url("**/checkout")
        check("TC-UAT-N3", "ログイン後、購入手続きに戻る", page.url.endswith("/checkout"), page.url)

        print("\nTC-UAT-E3：選択できない支払方法と、その理由")
        page.get_by_role("button", name="お支払い方法を選ぶ").click()
        page.wait_for_selector(".choice.unavailable")
        unavailable = page.locator(".choice.unavailable .choice-main").all_inner_texts()
        check("TC-UAT-E3", "置き配（初期値）では後払い・代引が選べない", len(unavailable) == 2, unavailable)
        check("FR-5A-02", "理由に原因（置き配）を示す", all("置き配" in t for t in unavailable), unavailable)
        page.locator(".choice.unavailable .btn-link").first.click()
        page.select_option("#placement", "NONE")
        page.wait_for_function("document.querySelectorAll('.choice.unavailable').length === 0")
        check("TC-UAT-E3", "置き配をやめると選べるようになる", page.locator(".choice.unavailable").count() == 0)

        print("\nTC-UAT-N2：確認と注文確定")
        page.get_by_label("クレジットカード").check()
        page.get_by_role("button", name="確認画面へ進む").click()
        page.wait_for_url("**/checkout/confirm")
        page.wait_for_selector(".amount-total")
        notices = page.locator(".notice-warn").all_inner_texts()
        check("DS-625", "確認画面で返品不可を示す", any("返品" in n for n in notices), notices)
        check("FR-564", "すそ上げの内容が確認画面に出る", page.locator("text=すそ上げ：シングル 70.0cm").count() == 1)
        page.get_by_role("button", name="注文を確定する").click()
        page.wait_for_url("**/orders/**")
        page.wait_for_selector("h1")
        check("TC-UAT-N2", "注文が完了する", page.locator("h1").inner_text() == "ご注文ありがとうございました", page.locator("h1").inner_text())
        check("TC-UAT-N2", "カートが空になる", page.locator(".badge").inner_text() == "0", page.locator(".badge").inner_text())

        browser.close()

    check("品質", "ブラウザのコンソールにエラーが出ない", not console_errors, console_errors)

    passed = sum(ok for _, ok in results)
    print(f"\n{passed}/{len(results)} 件合格")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
