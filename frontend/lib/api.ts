/**
 * API の呼び出しと型。型は Backend の schemas.py に対応する（設計仕様書 6章）。
 *
 * 画面から呼ぶのは必ず /api/*（BFF）であり、FastAPI の URL はここに書かない。
 */

export type ProductListItem = {
  productId: string;
  name: string;
  gender: string;
  regularPrice: number;
  memberPrice: number | null;
  appliedPrice: number;
  appliedPriceType: "REGULAR" | "MEMBER";
  regularPriceTaxIncluded: number;
  memberPriceTaxIncluded: number | null;
  appliedPriceTaxIncluded: number;
};

export type ProductListResponse = {
  items: ProductListItem[];
  total: number;
};

export type SkuAvailability = {
  skuId: string;
  colorCode: string;
  colorName: string;
  size: string;
  inStock: boolean;
};

export type AlterationOption = {
  type: "SINGLE_FOLD" | "DOUBLE_FOLD";
  fee: number;
  feeTaxIncluded: number;
  minLengthMm: number;
  maxLengthMm: number;
  stepMm: number;
};

export type ProductDetail = ProductListItem & {
  alterable: boolean;
  alterationOptions: AlterationOption[] | null;
  skus: SkuAvailability[];
};

export type CartItem = {
  cartItemId: number;
  skuId: string;
  productId: string;
  productName: string;
  colorName: string;
  size: string;
  quantity: number;
  unitPrice: number;
  unitPriceTaxIncluded: number;
  priceType: "REGULAR" | "MEMBER";
  alteration: { type: string; lengthMm: number; fee: number; feeTaxIncluded: number } | null;
  reserved: boolean;
  reservedUntil: string | null;
};

export type CartResponse = {
  cartId: number;
  items: CartItem[];
  amount: { subtotal: number; alterationFee: number };
};

export type Member = { member_id: number; name: string; email: string };

export type DeliveryMethodOption = {
  code: "HOME" | "STORE_PICKUP" | "NEKOPOSU";
  name: string;
  fee: number;
  feeTaxIncluded: number;
  available: boolean;
  unavailableReason: string | null;
};

export type PlacementTypeOption = { code: string; name: string; isDefault: boolean };

export type CheckoutOptions = {
  deliveryMethods: DeliveryMethodOption[];
  placementTypes: PlacementTypeOption[];
};

export type PaymentMethodOption = {
  code: string;
  name: string;
  fee: number;
  feeTaxIncluded: number;
  available: boolean;
  unavailableReason: { code: string; message: string; causedBy: string } | null;
};

export type Amounts = {
  subtotal: number;
  alterationFee: number;
  shippingFee: number;
  paymentFee: number;
  tax: number;
  total: number;
};

export type CheckoutSummary = {
  items: Array<{
    skuId: string;
    productName: string;
    colorName: string;
    size: string;
    unitPrice: number;
    priceType: string;
    quantity: number;
    subtotal: number;
    alteration: { typeName: string; lengthMm: number; fee: number } | null;
    isReturnable: boolean;
  }>;
  amounts: Amounts;
  delivery: {
    method: string;
    methodName: string;
    placementType: string | null;
    recipient: { name: string; postalCode: string; address: string; phone: string };
  };
  payment: { method: string; methodName: string };
  notices: Array<{ code: string; message: string }>;
  idempotencyKey: string;
};

export type OrderResponse = {
  orderNumber: string;
  orderedAt: string;
  status: "CONFIRMED" | "PENDING_PAYMENT" | "FAILED";
  amounts: Amounts;
  message?: string | null;
};

export type OrderDetail = OrderResponse & {
  items: Array<{
    skuId: string;
    productName: string;
    colorName: string;
    size: string;
    unitPrice: number;
    quantity: number;
    alterationType: string | null;
    alterationLengthMm: number | null;
    isReturnable: boolean;
  }>;
  deliveryMethod: string;
  paymentMethod: string;
};

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Array<Record<string, unknown>> | null = null,
  ) {
    super(message);
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init.headers ?? {}) },
    cache: "no-store",
  });
  if (res.status === 204) return undefined as T;

  const body = await res.json().catch(() => null);
  if (!res.ok) {
    // 業務エラーは { error: { code, message, details } }。
    // FastAPI の入力検証エラー（型違いなど）は { detail: [...] } で届く
    const err = body?.error;
    throw new ApiError(
      res.status,
      err?.code ?? "UNKNOWN",
      err?.message ?? (body?.detail ? "入力内容を確認してください" : "エラーが発生しました"),
      err?.details ?? null,
    );
  }
  return body as T;
}

export const post = <T>(path: string, data?: unknown, headers?: Record<string, string>) =>
  api<T>(path, { method: "POST", body: data === undefined ? undefined : JSON.stringify(data), headers });
