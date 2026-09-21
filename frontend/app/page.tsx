"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Price } from "@/components/Price";
import { api, ApiError, type ProductListResponse } from "@/lib/api";

const FILTERS = [
  { code: "", label: "すべて" },
  { code: "WOMEN", label: "WOMEN" },
  { code: "MEN", label: "MEN" },
  { code: "KIDS", label: "KIDS" },
];

export default function ProductListPage() {
  const [gender, setGender] = useState("");
  const [data, setData] = useState<ProductListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    api<ProductListResponse>(`/products?limit=100${gender ? `&gender=${gender}` : ""}`)
      .then(setData)
      .catch((e: ApiError) => setError(e.message));
  }, [gender]);

  return (
    <>
      <h1>商品一覧</h1>
      <div className="filters">
        {FILTERS.map((f) => (
          <button
            key={f.code}
            className="chip"
            aria-pressed={gender === f.code}
            onClick={() => setGender(f.code)}
          >
            {f.label}
          </button>
        ))}
      </div>

      {error && <div className="notice notice-error">{error}</div>}
      {data && <p className="muted">{data.total}件</p>}

      <div className="grid">
        {data?.items.map((p) => (
          <Link key={p.productId} href={`/products/${p.productId}`} className="card">
            <div className="card-img">
              <span className="small">{p.gender}</span>
            </div>
            <div className="card-name">{p.name}</div>
            <Price {...p} />
          </Link>
        ))}
      </div>
    </>
  );
}
