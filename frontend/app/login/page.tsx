"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { useSession } from "@/components/Session";
import { ApiError, post } from "@/lib/api";
import { cm } from "@/lib/format";

type Discarded = { productName: string; colorName: string; size: string; alterationLengthMm: number | null };

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") ?? "/";
  const { refresh } = useSession();

  const [email, setEmail] = useState("test1@example.com");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [discarded, setDiscarded] = useState<Discarded[] | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await post("/auth/login", { email, password });
      // 未ログインで入れた商品を、会員のカートへ移す（設計仕様書 4.2.2）
      const merged = await post<{ discarded: Discarded[] }>("/cart/merge");
      await refresh();
      if (merged.discarded.length > 0) {
        // DS-425: 消えた商品があれば、黙って進まずに知らせる
        setDiscarded(merged.discarded);
      } else {
        router.push(next);
      }
    } catch (err) {
      setError((err as ApiError).message);
    } finally {
      setSubmitting(false);
    }
  }

  if (discarded) {
    return (
      <div style={{ maxWidth: 480 }}>
        <h1>ログインしました</h1>
        <div className="notice notice-warn">
          ログイン前にカートに入れた商品のうち、以下は会員のカートに同じ商品がすでにあったため、
          会員のカートの内容を残しました。
          <ul style={{ margin: "8px 0 0", paddingLeft: 20 }}>
            {discarded.map((d, i) => (
              <li key={i}>
                {d.productName}（{d.colorName}／{d.size}
                {d.alterationLengthMm ? `／丈 ${cm(d.alterationLengthMm)}` : ""}）
              </li>
            ))}
          </ul>
        </div>
        <button className="btn" onClick={() => router.push(next)}>
          続ける
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={submit} style={{ maxWidth: 400 }}>
      <h1>ログイン</h1>
      <div className="field">
        <label htmlFor="email">メールアドレス</label>
        <input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
      </div>
      <div className="field">
        <label htmlFor="password">パスワード</label>
        <input
          id="password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
      </div>
      {error && <div className="notice notice-error">{error}</div>}
      <button className="btn btn-block" disabled={submitting}>
        {submitting ? "ログインしています…" : "ログイン"}
      </button>
      <p className="small" style={{ marginTop: 16 }}>
        検証用アカウント：test1@example.com ／ test2@example.com（パスワードは README を参照）
      </p>
    </form>
  );
}

export default function LoginPage() {
  // useSearchParams を使う画面は Suspense で包む（Next.js の要件）
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
