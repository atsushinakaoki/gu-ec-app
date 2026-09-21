/**
 * 価格の表示。
 *
 * 税込価格を主として表示する（消費税法63条の総額表示義務）。
 * 税込の値は Backend が計算して返す。ここでは計算しない。
 *
 * 会員価格が期間中なら、未ログインでも会員価格を示す。
 * 適用されるかどうか（ログインしているか）とは別の情報として扱い、
 * 「ログインすればこの価格になる」ことが分かるようにする。
 */

import { yen } from "@/lib/format";
import type { ProductListItem } from "@/lib/api";

type Props = Pick<
  ProductListItem,
  "regularPriceTaxIncluded" | "memberPriceTaxIncluded" | "appliedPriceType"
> & { large?: boolean };

export function Price({ regularPriceTaxIncluded, memberPriceTaxIncluded, appliedPriceType, large }: Props) {
  const size = large ? { fontSize: 22 } : undefined;

  if (memberPriceTaxIncluded == null) {
    return (
      <div className="price" style={size}>
        {yen(regularPriceTaxIncluded)}
        <span className="tax-note">税込</span>
      </div>
    );
  }

  return (
    <div>
      <div className="price price-member" style={size}>
        <span className="member-tag">会員価格</span>
        {yen(memberPriceTaxIncluded)}
        <span className="tax-note">税込</span>
      </div>
      <div className="small">
        <span className="price-regular-struck">{yen(regularPriceTaxIncluded)}</span>
        {appliedPriceType === "MEMBER" ? "会員価格が適用されます" : "ログインすると会員価格で購入できます"}
      </div>
    </div>
  );
}
