"use client";

/**
 * 注文の完了・状況。
 *
 * 決済の応答が得られなかった注文（PENDING_PAYMENT）は「失敗」ではなく「確認中」と表示する
 * （DS-451）。この画面を開き直すと Backend が決済代行に照会し、結果を確定させる（DS-449）。
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api, ApiError, type OrderDetail } from "@/lib/api";
import { cm, yen } from "@/lib/format";

export default function OrderPage() {
  const { orderNumber } = useParams<{ orderNumber: string }>();
  const [order, setOrder] = useState<OrderDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);

  const load = async () => {
    setChecking(true);
    try {
      setOrder(await api<OrderDetail>(`/orders/${orderNumber}`));
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setChecking(false);
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orderNumber]);

  if (error) return <div className="notice notice-error">{error}</div>;
  if (!order) return <p className="muted">読み込み中…</p>;

  return (
    <div style={{ maxWidth: 640 }}>
      {order.status === "CONFIRMED" && (
        <>
          <h1>ご注文ありがとうございました</h1>
          <div className="notice notice-ok">
            注文番号：<strong>{order.orderNumber}</strong>
          </div>
        </>
      )}

      {order.status === "PENDING_PAYMENT" && (
        <>
          <h1>お支払いを確認しています</h1>
          <div className="notice notice-warn">
            決済の確認に時間がかかっています。ご注文は受け付けており、商品も確保しています。
            確認が取れ次第、ご注文が確定します。
            <br />
            注文番号：<strong>{order.orderNumber}</strong>
          </div>
          <button className="btn btn-secondary" disabled={checking} onClick={load}>
            {checking ? "確認しています…" : "状況を確認する"}
          </button>
        </>
      )}

      {order.status === "FAILED" && (
        <>
          <h1>お支払いが完了しませんでした</h1>
          <div className="notice notice-error">
            ご注文は成立していません。カートの商品はそのまま残っています。
            <br />
            <Link href="/checkout">お支払い方法を変更して、もう一度お試しください →</Link>
          </div>
        </>
      )}

      <h2>ご注文内容</h2>
      <div className="lines">
        {order.items.map((item, i) => (
          <div key={i} className="line">
            <div className="line-img" style={{ background: "var(--bg-2)" }} />
            <div>
              <div className="line-name">{item.productName}</div>
              <div className="line-meta">
                {item.colorName} ／ {item.size} ／ {item.quantity}点
              </div>
              {item.alterationLengthMm && (
                <div className="line-meta">すそ上げ：{cm(item.alterationLengthMm)}（交換・返品不可）</div>
              )}
            </div>
            <div className="line-right">
              {yen(item.unitPrice * item.quantity)}
              <span className="tax-note">税抜</span>
            </div>
          </div>
        ))}
      </div>
      <div className="amount-row amount-total" style={{ maxWidth: 320, marginLeft: "auto" }}>
        <span>お支払い総額（税込）</span>
        <span>{yen(order.amounts.total)}</span>
      </div>

      <p style={{ marginTop: 32 }}>
        <Link href="/" className="btn btn-secondary">
          買い物を続ける
        </Link>
      </p>
    </div>
  );
}
