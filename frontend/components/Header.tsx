"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { post } from "@/lib/api";
import { useSession } from "./Session";

export function Header() {
  const { member, cartCount, loaded, refresh } = useSession();
  const router = useRouter();

  async function logout() {
    await post("/auth/logout");
    await refresh();
    router.push("/");
  }

  return (
    <header className="header">
      <div className="container header-inner">
        <Link href="/" className="brand">
          EC DEMO<small>GUオンラインストアの要件定義にもとづく学習用実装（非公式）</small>
        </Link>
        <nav className="nav">
          {loaded && member && <span className="muted">{member.name} さん</span>}
          {loaded && !member && <Link href="/login">ログイン</Link>}
          {loaded && member && (
            <button className="btn-link" onClick={logout}>
              ログアウト
            </button>
          )}
          <Link href="/cart">
            カート<span className="badge">{cartCount}</span>
          </Link>
        </nav>
      </div>
    </header>
  );
}
