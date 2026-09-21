"use client";

/**
 * 配送方法・支払方法の選択。
 *
 * 要件定義書で重視した「不可の理由を明示する設計」が最も表れる画面である。
 *
 * 置き配（初期値）を選んでいると、後払いと代金引換えは選べない。
 * GU の実画面では、置き配を選ぶ時点でこの帰結が示されていなかった
 * （要件定義書 5.6.2.2 の【整合上の論点】）。この実装では2か所で示す。
 *   1. 置き配を選ぶ欄に、支払方法への影響を書く（FR-562-13）
 *   2. 選べない支払方法に、原因となっている選択と、そこへ戻る導線を出す（FR-5A-61）
 *
 * 可否の判定は Backend が行う。画面は結果を表示するだけで、規則を持たない。
 */

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useSession } from "@/components/Session";
import {
  api,
  ApiError,
  post,
  type CheckoutOptions,
  type PaymentMethodOption,
} from "@/lib/api";
import { yen } from "@/lib/format";

type Recipient = { name: string; postalCode: string; address: string; phone: string };

export default function CheckoutPage() {
  const router = useRouter();
  const { member, loaded } = useSession();

  const [options, setOptions] = useState<CheckoutOptions | null>(null);
  const [delivery, setDelivery] = useState("HOME");
  const [placement, setPlacement] = useState("FRONT_DOOR");
  const [recipient, setRecipient] = useState<Recipient>({
    name: "",
    postalCode: "070-0031",
    address: "北海道旭川市一条通1丁目1-1",
    phone: "090-0000-0001",
  });
  const [payments, setPayments] = useState<PaymentMethodOption[] | null>(null);
  const [payment, setPayment] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const deliveryRef = useRef<HTMLDivElement>(null);
  const placementRef = useRef<HTMLSelectElement>(null);

  // 注文にはログインが必要
  useEffect(() => {
    if (loaded && !member) router.replace("/login?next=/checkout");
    if (member) setRecipient((r) => ({ ...r, name: r.name || member.name }));
  }, [loaded, member, router]);

  useEffect(() => {
    if (!member) return;
    api<CheckoutOptions>("/checkout/options")
      .then((o) => {
        setOptions(o);
        const def = o.placementTypes.find((p) => p.isDefault);
        if (def) setPlacement(def.code);
      })
      .catch((e: ApiError) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [member?.member_id]);

  async function submitDelivery(nextDelivery = delivery, nextPlacement = placement) {
    setBusy(true);
    setError(null);
    try {
      const res = await post<{ paymentMethods: PaymentMethodOption[] }>("/checkout/delivery", {
        deliveryMethod: nextDelivery,
        placementType: nextDelivery === "HOME" ? nextPlacement : null,
        recipient,
      });
      setPayments(res.paymentMethods);
      // 選び直した結果、選択中の支払方法が使えなくなっていたら外す
      setPayment((current) =>
        current && res.paymentMethods.find((p) => p.code === current)?.available ? current : null,
      );
    } catch (e) {
      setError((e as ApiError).message);
      setPayments(null);
    } finally {
      setBusy(false);
    }
  }

  // 支払方法を表示した後に配送方法や置き配を変えたら、すぐ判定し直す
  function changeDelivery(code: string) {
    setDelivery(code);
    if (payments) void submitDelivery(code, placement);
  }
  function changePlacement(code: string) {
    setPlacement(code);
    if (payments) void submitDelivery(delivery, code);
  }

  function goToCause(causedBy: string) {
    if (causedBy === "placementType") {
      placementRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
      placementRef.current?.focus();
    } else {
      deliveryRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }

  async function proceed() {
    if (!payment) return;
    setBusy(true);
    setError(null);
    try {
      await post("/checkout/payment", { paymentMethod: payment });
      router.push("/checkout/confirm");
    } catch (e) {
      setError((e as ApiError).message);
      setBusy(false);
    }
  }

  if (!member || !options) return <p className="muted">読み込み中…</p>;

  const placementName = options.placementTypes.find((p) => p.code === placement)?.name;

  return (
    <div style={{ maxWidth: 640 }}>
      <p className="step">STEP 1 / 2</p>
      <h1>お届け方法とお支払い方法</h1>

      {/* 配送方法 */}
      <div ref={deliveryRef}>
        <h2>お届け方法</h2>
        {options.deliveryMethods.map((d) => (
          <label key={d.code} className={`choice${delivery === d.code ? " selected" : ""}`}>
            <input
              type="radio"
              name="delivery"
              checked={delivery === d.code}
              onChange={() => changeDelivery(d.code)}
            />
            <span className="choice-main">{d.name}</span>
            <span className="choice-fee">
              送料 {d.feeTaxIncluded === 0 ? "無料" : `${yen(d.feeTaxIncluded)}（税込）`}
            </span>
          </label>
        ))}
        <p className="small">税抜5,000円以上のお買い上げで送料無料です。</p>
      </div>

      {/* 置き配 */}
      {delivery === "HOME" && (
        <div className="field">
          <label htmlFor="placement">置き配の指定</label>
          <select
            id="placement"
            ref={placementRef}
            value={placement}
            onChange={(e) => changePlacement(e.target.value)}
          >
            {options.placementTypes.map((p) => (
              <option key={p.code} value={p.code}>
                {p.name}
                {p.isDefault ? "（初期設定）" : ""}
              </option>
            ))}
          </select>
          {/* FR-562-11: 置き配を初期値とする理由 / FR-562-13: 支払方法への影響 */}
          <div className="notice" style={{ fontSize: 13 }}>
            再配達を減らし、配送スタッフの負担とCO2排出を抑えるため、置き配を初期設定にしています。
            {placement !== "NONE" && (
              <>
                <br />
                <strong>置き配を指定すると、後払いと代金引換えはお選びいただけません。</strong>
                <br />
                置き配をご利用の場合、置き配規約が適用されます。
              </>
            )}
          </div>
        </div>
      )}

      {/* 届け先 */}
      <h2>お届け先</h2>
      {(["name", "postalCode", "address", "phone"] as const).map((key) => (
        <div className="field" key={key}>
          <label htmlFor={key}>
            {{ name: "お名前", postalCode: "郵便番号", address: "住所", phone: "電話番号" }[key]}
          </label>
          <input
            id={key}
            value={recipient[key]}
            onChange={(e) => setRecipient({ ...recipient, [key]: e.target.value })}
          />
        </div>
      ))}

      {!payments && (
        <button className="btn btn-block" disabled={busy} onClick={() => submitDelivery()}>
          {busy ? "確認しています…" : "お支払い方法を選ぶ"}
        </button>
      )}

      {error && <div className="notice notice-error">{error}</div>}

      {/* 支払方法 */}
      {payments && (
        <>
          <h2>お支払い方法</h2>
          {payments.map((p) => (
            <label
              key={p.code}
              className={`choice${payment === p.code ? " selected" : ""}${p.available ? "" : " unavailable"}`}
            >
              <input
                type="radio"
                name="payment"
                disabled={!p.available || busy}
                checked={payment === p.code}
                onChange={() => setPayment(p.code)}
              />
              <span className="choice-main">
                {p.name}
                {p.unavailableReason && (
                  <span className="reason">
                    <br />
                    {p.unavailableReason.message}
                    {/* 原因となっている選択へ戻る導線（FR-5A-61） */}
                    <br />
                    <button
                      type="button"
                      className="btn-link"
                      onClick={(e) => {
                        e.preventDefault();
                        goToCause(p.unavailableReason!.causedBy);
                      }}
                    >
                      {p.unavailableReason.causedBy === "placementType"
                        ? `置き配の指定（現在：${placementName}）を変更する`
                        : "お届け方法を変更する"}
                    </button>
                  </span>
                )}
              </span>
              <span className="choice-fee">
                {p.feeTaxIncluded === 0 ? "手数料なし" : `手数料 ${yen(p.feeTaxIncluded)}（税込）`}
              </span>
            </label>
          ))}

          <button className="btn btn-block" style={{ marginTop: 16 }} disabled={!payment || busy} onClick={proceed}>
            {payment ? "確認画面へ進む" : "お支払い方法を選択してください"}
          </button>
        </>
      )}
    </div>
  );
}
