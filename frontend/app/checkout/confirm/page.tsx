"use client";

/**
 * 注文内容の確認と確定。
 *
 * --- 二重注文の防止 ---
 * ボタンを押したら無効にする。ただしそれだけには頼らない（設計仕様書 4.4.8）。
 * 通信の再送は画面の制御の外で起こる。確認画面を開いた時点で Backend から
 * 冪等キーを受け取り、確定の要求に必ず付ける。同じキーの2回目は、
 * Backend が最初の結果を返す。
 *
 * --- 金額の照合 ---
 * 画面に出している総額を要求に含め、Backend が計算し直した額と照合する（DS-628）。
 * 画面の値を信用して請求するのではなく、画面と Backend が食い違ったら止める。
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useSession } from "@/components/Session";
import { api, ApiError, post, type CheckoutSummary, type OrderResponse } from "@/lib/api";
import { cm, postal, yen } from "@/lib/format";

export default function ConfirmPage() {
  const router = useRouter();
  const { member, loaded, refresh } = useSession();
  const [summary, setSummary] = useState<CheckoutSummary | null>(null);
  const [error, setError] = useState<{ message: string; action?: "checkout" | "cart" } | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const load = async () => {
    try {
      setSummary(await api<CheckoutSummary>("/checkout/summary"));
    } catch (e) {
      const err = e as ApiError;
      setError({ message: err.message, action: "checkout" });
    }
  };

  useEffect(() => {
    if (loaded && !member) router.replace("/login?next=/checkout");
    if (member) void load();
    // 会員情報の再取得（カート件数の更新など）では読み直さない。会員が変わったときだけ
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaded, member?.member_id]);

  async function placeOrder() {
    if (!summary || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await post<OrderResponse>(
        "/orders",
        { expectedTotal: summary.amounts.total },
        { "Idempotency-Key": summary.idempotencyKey },
      );
      await refresh();
      router.push(`/orders/${res.orderNumber}`);
    } catch (e) {
      const err = e as ApiError;
      switch (err.code) {
        case "PAYMENT_DECLINED":
          // DS-447: カートは残っているので、支払方法を変えて再試行できる
          setError({ message: err.message, action: "checkout" });
          break;
        case "STOCK_INSUFFICIENT": {
          // DS-454: どの商品が足りないかを示す
          const skus = (err.details ?? []).map((d) => String(d.skuId));
          const names = summary.items.filter((i) => skus.includes(i.skuId)).map((i) => `${i.productName}（${i.colorName}／${i.size}）`);
          setError({
            message: `申し訳ありません。在庫が確保できなかった商品があります：${names.join("、")}`,
            action: "cart",
          });
          break;
        }
        case "AMOUNT_MISMATCH":
        case "IDEMPOTENCY_CONFLICT":
          // 別のタブでカートを変えた、会員価格の期間が切れた、など。
          // 最新の内容を取り直し、もう一度確認してもらう。正しい金額は Backend から来ない（DS-629）
          await load();
          setError({ message: "ご注文の内容が更新されました。内容をご確認のうえ、もう一度確定してください。" });
          break;
        default:
          setError({ message: err.message, action: err.code === "CHECKOUT_INCOMPLETE" ? "checkout" : undefined });
      }
      setSubmitting(false);
    }
  }

  if (!summary && !error) return <p className="muted">読み込み中…</p>;

  return (
    <>
      <p className="step">STEP 2 / 2</p>
      <h1>ご注文内容の確認</h1>

      {error && (
        <div className="notice notice-error">
          {error.message}
          {error.action === "checkout" && (
            <>
              <br />
              <Link href="/checkout">お届け方法・お支払い方法を選び直す →</Link>
            </>
          )}
          {error.action === "cart" && (
            <>
              <br />
              <Link href="/cart">カートを確認する →</Link>
            </>
          )}
        </div>
      )}

      {summary && (
        <div className="layout-2col">
          <div>
            {/* 表示義務（DS-625、DS-626）。何を出すかは Backend が判定する */}
            {summary.notices.map((n) => (
              <div key={n.code} className="notice notice-warn">
                {n.message}
              </div>
            ))}

            <h2>ご注文商品</h2>
            <div className="lines">
              {summary.items.map((item, i) => (
                <div key={i} className="line">
                  <div className="line-img" style={{ background: "var(--bg-2)" }} />
                  <div>
                    <div className="line-name">{item.productName}</div>
                    <div className="line-meta">
                      {item.colorName} ／ {item.size} ／ {item.quantity}点
                      {item.priceType === "MEMBER" && "（会員価格）"}
                    </div>
                    {item.alteration && (
                      <div className="line-meta">
                        すそ上げ：{item.alteration.typeName} {cm(item.alteration.lengthMm)}
                      </div>
                    )}
                    {!item.isReturnable && <div className="small" style={{ color: "#8a4b00" }}>交換・返品不可</div>}
                  </div>
                  <div className="line-right">
                    {yen(item.subtotal)}
                    <span className="tax-note">税抜</span>
                  </div>
                </div>
              ))}
            </div>

            <h2>お届け</h2>
            <p style={{ margin: 0 }}>
              {summary.delivery.methodName}
              {summary.delivery.placementType ? "（置き配）" : ""}
            </p>
            <p className="muted" style={{ margin: 0 }}>
              {summary.delivery.recipient.name} 様 ／ 〒{postal(summary.delivery.recipient.postalCode)}{" "}
              {summary.delivery.recipient.address} ／ {summary.delivery.recipient.phone}
            </p>

            <h2>お支払い</h2>
            <p style={{ margin: 0 }}>{summary.payment.methodName}</p>
            <p className="small">
              <Link href="/checkout">お届け方法・お支払い方法を変更する</Link>
            </p>
          </div>

          <aside className="summary-box">
            {/* DS-624: 総額だけでなく内訳を示す */}
            <div className="amount-row"><span>商品合計（税抜）</span><span>{yen(summary.amounts.subtotal)}</span></div>
            {summary.amounts.alterationFee > 0 && (
              <div className="amount-row"><span>すそ上げ加工料（税抜）</span><span>{yen(summary.amounts.alterationFee)}</span></div>
            )}
            <div className="amount-row"><span>送料（税抜）</span><span>{summary.amounts.shippingFee === 0 ? "無料" : yen(summary.amounts.shippingFee)}</span></div>
            <div className="amount-row"><span>支払手数料（税抜）</span><span>{yen(summary.amounts.paymentFee)}</span></div>
            <div className="amount-row"><span>消費税（10%）</span><span>{yen(summary.amounts.tax)}</span></div>
            <div className="amount-row amount-total"><span>お支払い総額（税込）</span><span>{yen(summary.amounts.total)}</span></div>

            <button className="btn btn-block" style={{ marginTop: 16 }} disabled={submitting} onClick={placeOrder}>
              {submitting ? "処理しています…" : "注文を確定する"}
            </button>
            <p className="small" style={{ marginTop: 8 }}>
              「注文を確定する」を押すと、ご注文が確定し、お支払いの手続きが行われます。
            </p>
          </aside>
        </div>
      )}
    </>
  );
}
