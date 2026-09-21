"use client";

/**
 * 商品詳細。
 *
 * 要件定義書で重視した「選択肢の依存関係」が最も表れる画面である。
 *
 *   カラー → サイズ → 数量 → （すそ上げ：加工方法 → 丈） → カートに入れる
 *
 * 前の選択が決まらないと、次の選択肢は意味を持たない。
 * 選べない状態は、ただ無効にするのではなく「なぜ選べないか」を示す。
 *   - 在庫切れのサイズ：斜線を引いて選べなくする（GUの実画面の観察）
 *   - 丈：加工方法を選ぶまで無効（FR-564-02）
 *   - カートに入れるボタン：何が足りないかをボタン自体に書く
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Price } from "@/components/Price";
import { useSession } from "@/components/Session";
import { api, ApiError, post, type ProductDetail } from "@/lib/api";
import { ALTERATION_NAMES, cm, swatch, yen } from "@/lib/format";

type AddResult = { kind: "ok"; minutes: number } | { kind: "error"; message: string };

export default function ProductDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { refresh } = useSession();

  const [product, setProduct] = useState<ProductDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [color, setColor] = useState<string | null>(null);
  const [size, setSize] = useState<string | null>(null);
  const [quantity, setQuantity] = useState(1);
  const [alterationType, setAlterationType] = useState<string>("");
  const [lengthMm, setLengthMm] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<AddResult | null>(null);

  const load = () =>
    api<ProductDetail>(`/products/${id}`)
      .then(setProduct)
      .catch((e: ApiError) => setLoadError(e.message));

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // カラーごとに SKU をまとめる。全サイズ在庫切れのカラーも表示はする
  const colors = useMemo(() => {
    const map = new Map<string, { code: string; name: string; anyInStock: boolean }>();
    for (const s of product?.skus ?? []) {
      const c = map.get(s.colorCode) ?? { code: s.colorCode, name: s.colorName, anyInStock: false };
      c.anyInStock ||= s.inStock;
      map.set(s.colorCode, c);
    }
    return [...map.values()];
  }, [product]);

  const sizes = useMemo(
    () => (product?.skus ?? []).filter((s) => s.colorCode === color),
    [product, color],
  );
  const selectedSku = sizes.find((s) => s.size === size && s.inStock) ?? null;
  const alteration = product?.alterationOptions?.find((o) => o.type === alterationType) ?? null;

  const lengthChoices = useMemo(() => {
    const opt = product?.alterationOptions?.[0];
    if (!opt) return [];
    const list: number[] = [];
    for (let mm = opt.maxLengthMm; mm >= opt.minLengthMm; mm -= opt.stepMm) list.push(mm);
    return list;
  }, [product]);

  // カラーを変えたら、そのカラーに無いサイズの選択は外す
  function chooseColor(code: string) {
    setColor(code);
    setResult(null);
    const stillThere = product?.skus.find((s) => s.colorCode === code && s.size === size && s.inStock);
    if (!stillThere) setSize(null);
  }

  function chooseAlteration(type: string) {
    setAlterationType(type);
    if (!type) setLengthMm(""); // 加工なしに戻したら丈も外す（FR-564-02）
  }

  // ボタンに「何が足りないか」を書く
  const missing = !color
    ? "カラーを選択してください"
    : !selectedSku
      ? "サイズを選択してください"
      : alterationType && !lengthMm
        ? "仕上がりの丈を選択してください"
        : null;

  async function addToCart() {
    if (!selectedSku || missing) return;
    setSubmitting(true);
    setResult(null);
    try {
      const res = await post<{ reservation: { expiresAt: string } }>("/cart/items", {
        skuId: selectedSku.skuId,
        quantity,
        ...(alterationType ? { alteration: { type: alterationType, lengthMm: Number(lengthMm) } } : {}),
      });
      const minutes = Math.round((new Date(res.reservation.expiresAt).getTime() - Date.now()) / 60000);
      setResult({ kind: "ok", minutes });
      await refresh();
    } catch (e) {
      const err = e as ApiError;
      if (err.code === "STOCK_INSUFFICIENT") {
        // DS-622: 在庫不足のときだけ、引当可能数を示す。数量を減らして再試行できるように
        const available = Number(err.details?.[0]?.available ?? 0);
        setResult({
          kind: "error",
          message:
            available > 0
              ? `在庫が不足しています。この商品は、あと${available}点までカートに入れられます。`
              : "申し訳ありません。ちょうど在庫がなくなりました。",
        });
        void load(); // 在庫表示を最新にする
      } else {
        setResult({ kind: "error", message: err.message });
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (loadError) return <div className="notice notice-error">{loadError}</div>;
  if (!product) return <p className="muted">読み込み中…</p>;

  return (
    <div className="detail">
      {/* 商品画像は扱わない。選んだカラーを色見本で示す */}
      <div className="detail-img">
        <div className="garment" style={{ background: color ? swatch(color) : "#e4e4e0" }} />
        <span className="small">{color ? colors.find((c) => c.code === color)?.name : "カラーを選択してください"}</span>
      </div>

      <div>
        <p className="small">商品番号 {product.productId} ／ {product.gender}</p>
        <h1>{product.name}</h1>
        <Price {...product} large />

        {/* カラー */}
        <div className="option-label">
          カラー<span>{colors.find((c) => c.code === color)?.name ?? "未選択"}</span>
        </div>
        <div className="swatches">
          {colors.map((c) => (
            <button
              key={c.code}
              className={`swatch${c.anyInStock ? "" : " soldout"}`}
              style={{ background: swatch(c.code) }}
              aria-pressed={color === c.code}
              aria-label={`${c.name}${c.anyInStock ? "" : "（在庫なし）"}`}
              title={`${c.name}${c.anyInStock ? "" : "（在庫なし）"}`}
              onClick={() => chooseColor(c.code)}
            />
          ))}
        </div>

        {/* サイズ：カラーを選ぶまで出さない。カラーによって在庫が違うため */}
        <div className="option-label">
          サイズ<span>{color ? (size ?? "未選択") : "カラーを選ぶと、在庫のあるサイズが表示されます"}</span>
        </div>
        {color && (
          <div className="sizes">
            {sizes.map((s) => (
              <button
                key={s.skuId}
                className="size"
                disabled={!s.inStock}
                aria-pressed={size === s.size}
                title={s.inStock ? undefined : "在庫なし"}
                onClick={() => {
                  setSize(s.size);
                  setResult(null);
                }}
              >
                {s.size}
              </button>
            ))}
          </div>
        )}

        {/* 数量 */}
        <div className="option-label">数量</div>
        <select
          value={quantity}
          onChange={(e) => setQuantity(Number(e.target.value))}
          style={{ padding: "8px 12px", borderRadius: 6 }}
        >
          {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
        <span className="small" style={{ marginLeft: 8 }}>1回のご注文につき10点まで</span>

        {/* すそ上げ */}
        {product.alterable && product.alterationOptions && (
          <>
            <div className="option-label">すそ上げ</div>
            <div className="alteration">
              <div className="radio-row">
                <label>
                  <input type="radio" name="alt" checked={alterationType === ""} onChange={() => chooseAlteration("")} />
                  補正なし
                </label>
                {product.alterationOptions.map((o) => (
                  <label key={o.type}>
                    <input
                      type="radio"
                      name="alt"
                      checked={alterationType === o.type}
                      onChange={() => chooseAlteration(o.type)}
                    />
                    {ALTERATION_NAMES[o.type]}（{yen(o.feeTaxIncluded)}<span className="tax-note">税込</span>）
                  </label>
                ))}
              </div>

              <select
                value={lengthMm}
                disabled={!alterationType}
                onChange={(e) => setLengthMm(e.target.value)}
                style={{ width: "100%", padding: "8px 12px", borderRadius: 6 }}
              >
                <option value="">{alterationType ? "仕上がりの丈を選択" : "レングス未選択（加工方法を先に選んでください）"}</option>
                {lengthChoices.map((mm) => (
                  <option key={mm} value={mm}>
                    {cm(mm)}
                    {mm === lengthChoices[0] ? "（元の丈）" : ""}
                  </option>
                ))}
              </select>

              {alterationType && (
                // FR-564-04、05：選んだ時点で、リードタイムと返品不可を示す
                <div className="notice notice-warn" style={{ marginBottom: 0 }}>
                  すそ上げをご指定の場合、お届けまで通常より1〜3日多くかかります。
                  <br />
                  <strong>加工した商品は、交換・返品ができません。</strong>
                </div>
              )}
              {alteration && (
                <p className="small" style={{ margin: "8px 0 0" }}>
                  加工料 {yen(alteration.feeTaxIncluded)}（税込）× {quantity}点
                </p>
              )}
            </div>
          </>
        )}

        <div style={{ marginTop: 24 }}>
          <button className="btn btn-block" disabled={!!missing || submitting} onClick={addToCart}>
            {missing ?? (submitting ? "追加しています…" : "カートに入れる")}
          </button>
        </div>

        {result?.kind === "ok" && (
          <div className="notice notice-ok">
            カートに追加しました。在庫を{result.minutes}分間確保しています。
            <br />
            <Link href="/cart">カートを見る →</Link>
          </div>
        )}
        {result?.kind === "error" && <div className="notice notice-error">{result.message}</div>}
      </div>
    </div>
  );
}
