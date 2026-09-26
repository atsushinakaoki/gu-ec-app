/**
 * BFF（Backend For Frontend）。設計仕様書 5.2 に対応する。
 *
 * ブラウザは FastAPI に直接つながらず、必ずここを経由する。
 *
 *   ブラウザ ──/api/*──> Next.js（このファイル）──> FastAPI
 *
 * --- BFF を置く理由 ---
 *
 * ログインのトークン（JWT）を HttpOnly Cookie に入れ、JavaScript から読めなくするため。
 * localStorage に置くと、XSS が1つあればトークンを持ち出される。
 * Cookie は同じオリジン（ここでは localhost:3000）にしか送られないので、
 * ブラウザから見て API が同じ場所にある必要がある。それを作るのが BFF である。
 *
 * --- ここでやらないこと（DS-614） ---
 *
 * 業務の判断をしない。価格の計算も、在庫の判定も、支払方法の可否も、すべて FastAPI が行う。
 * BFF で判断を始めると、同じ規則が2か所に分かれ、いつか食い違う。
 * BFF の仕事は、Cookie の受け渡しと中継と、下の CSRF の確認だけである。
 */

import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

// FastAPI へ転送するヘッダ。それ以外（Host など）は送らない
const FORWARD_HEADERS = ["content-type", "cookie", "idempotency-key"];

const SAFE_METHODS = new Set(["GET", "HEAD"]);

async function proxy(
  req: NextRequest,
  ctx: { params: Promise<{ path: string[] }> },
): Promise<NextResponse> {
  const { path } = await ctx.params;

  // --- CSRF の確認 ---
  // Cookie はブラウザが自動で付けるため、別サイトのページから
  // 「注文を確定する」POST を送らせる攻撃が成り立ちうる（CSRF）。
  // SameSite=Lax の Cookie はそれを大部分防ぐが、それだけに頼らず、
  // 状態を変える要求は自分のオリジンから来たものに限る。
  //
  // Origin ヘッダが無い要求も拒否する（Gemini の指摘）。当初は
  // 「Origin があって、かつ違う場合」だけを拒否しており、Origin の無い要求は素通りしていた。
  // 現在のブラウザは、同じオリジンからの fetch による POST にも Origin を付けるので、
  // 正当な利用者の操作はこれで妨げられない。
  if (!SAFE_METHODS.has(req.method)) {
    const origin = req.headers.get("origin");
    const host = req.headers.get("host");
    let sameOrigin = false;
    try {
      sameOrigin = !!origin && !!host && new URL(origin).host === host;
    } catch {
      sameOrigin = false; // Origin が URL として読めない
    }
    if (!sameOrigin) {
      return NextResponse.json(
        { error: { code: "CSRF_REJECTED", message: "不正な要求です", details: null } },
        { status: 403 },
      );
    }
  }

  const url = `${BACKEND_URL}/api/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;

  const headers = new Headers();
  for (const name of FORWARD_HEADERS) {
    const value = req.headers.get(name);
    if (value) headers.set(name, value);
  }

  let upstream: Response;
  try {
    upstream = await fetch(url, {
      method: req.method,
      headers,
      body: SAFE_METHODS.has(req.method) ? undefined : await req.text(),
      redirect: "manual",
      cache: "no-store",
    });
  } catch {
    // FastAPI が起動していない、または DB に届かない
    return NextResponse.json(
      {
        error: {
          code: "BACKEND_UNAVAILABLE",
          message: "サーバーに接続できません。しばらくしてからお試しください",
          details: null,
        },
      },
      { status: 502 },
    );
  }

  const body = upstream.status === 204 ? null : await upstream.arrayBuffer();
  const res = new NextResponse(body, { status: upstream.status });

  const contentType = upstream.headers.get("content-type");
  if (contentType) res.headers.set("content-type", contentType);

  // FastAPI が発行した Cookie（ログインのトークン、カートの識別子）を、そのままブラウザへ渡す。
  // HttpOnly・SameSite の属性も FastAPI が付けたものを維持する
  for (const cookie of upstream.headers.getSetCookie()) {
    res.headers.append("set-cookie", cookie);
  }
  return res;
}

export { proxy as GET, proxy as POST, proxy as PATCH, proxy as DELETE };
