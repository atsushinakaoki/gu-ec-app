"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useSession } from "@/components/Session";
import { api, ApiError, type CartResponse } from "@/lib/api";
import { ALTERATION_NAMES, cm, minutesLeft, yen } from "@/lib/format";

export default function CartPage() {
  const { member, refresh } = useSession();
  const router = useRouter();
  const [cart, setCart] = useState<CartResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());

  const load = () =>
    api<CartResponse>("/cart")
      .then(setCart)
      .catch((e: ApiError) => setError(e.message));

  useEffect(() => {
    void load();
    // 確保の残り時間を30秒ごとに更新する
    const timer = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(timer);
  }, []);

  async function remove(cartItemId: number) {
    try {
      await api(`/cart/items/${cartItemId}`, { method: "DELETE" });
      await load();
      await refresh();
    } catch (e) {
      setError((e as ApiError).message);
    }
  }

  function proceed() {
    // 注文にはログインが必要。未ログインでもカートまでは使える（設計仕様書 3.3.7）
    router.push(member ? "/checkout" : "/login?next=/checkout");
  }

  if (error) return <div className="notice notice-error">{error}</div>;
  if (!cart) return <p className="muted">読み込み中…</p>;

  if (cart.items.length === 0) {
    return (
      <>
        <h1>カート</h1>
        <p>カートに商品がありません。</p>
        <Link href="/" className="btn btn-secondary">
          買い物を続ける
        </Link>
      </>
    );
  }

  // 表示用の目安。1点ごとの税込単価を足し上げたもの
  const estimate = cart.items.reduce(
    (sum, i) => sum + (i.unitPriceTaxIncluded + (i.alteration?.feeTaxIncluded ?? 0)) * i.quantity,
    0,
  );

  return (
    <>
      <h1>カート</h1>
      <div className="layout-2col">
        <div className="lines">
          {cart.items.map((item) => {
            const left = minutesLeft(item.reservedUntil, now);
            return (
              <div key={item.cartItemId} className="line">
                <div className="line-img" style={{ background: "var(--bg-2)" }} />
                <div>
                  <div className="line-name">
                    <Link href={`/products/${item.productId}`}>{item.productName}</Link>
                  </div>
                  <div className="line-meta">
                    {item.colorName} ／ {item.size} ／ {item.quantity}点
                  </div>
                  {item.alteration && (
                    <div className="line-meta">
                      すそ上げ：{ALTERATION_NAMES[item.alteration.type]} {cm(item.alteration.lengthMm)}
                      （加工料 {yen(item.alteration.feeTaxIncluded)}×{item.quantity}）
                      <span style={{ color: "#8a4b00" }}> 返品不可</span>
                    </div>
                  )}
                  {/* 引当の状態。期限が切れていても注文時に在庫があれば買える（DS-453） */}
                  {left !== null ? (
                    <div className="small">在庫を確保しています（あと約{left}分）</div>
                  ) : (
                    <div className="small" style={{ color: "#8a4b00" }}>
                      在庫の確保期限が切れました。ご注文の時点で在庫を再確認します。
                    </div>
                  )}
                </div>
                <div className="line-right">
                  <div className={item.priceType === "MEMBER" ? "price price-member" : "price"}>
                    {yen(item.unitPriceTaxIncluded)}
                    <span className="tax-note">税込</span>
                  </div>
                  {item.priceType === "MEMBER" && <div className="small">会員価格</div>}
                  <button className="btn-link small" onClick={() => remove(item.cartItemId)}>
                    削除
                  </button>
                </div>
              </div>
            );
          })}
        </div>

        <aside className="summary-box">
          <div className="amount-row">
            <span>商品合計（税込）</span>
            <span>{yen(estimate)}</span>
          </div>
          <p className="small" style={{ margin: "8px 0 16px" }}>
            送料・手数料は、配送方法と支払方法を選んだ後に確定します。
            消費税は注文全体で計算するため、確認画面の金額と1円ほど異なる場合があります。
          </p>
          <button className="btn btn-block" onClick={proceed}>
            購入手続きへ
          </button>
          {!member && (
            <p className="small" style={{ marginTop: 8 }}>
              ご購入にはログインが必要です。カートの商品はログイン後も引き継がれます。
            </p>
          )}
        </aside>
      </div>
    </>
  );
}
