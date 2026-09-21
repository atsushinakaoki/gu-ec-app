"use client";

/**
 * ログイン状態とカートの点数を、画面全体で共有する。
 *
 * ログインの有無は、トークンの中身をブラウザで読んで判断するのではなく、
 * 毎回 /api/auth/session に問い合わせて判断する。トークンは HttpOnly なので
 * そもそも JavaScript からは読めない（読めないことが目的である）。
 */

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, type CartResponse, type Member } from "@/lib/api";

type SessionValue = {
  member: Member | null;
  cartCount: number;
  loaded: boolean;
  refresh: () => Promise<void>;
};

const SessionContext = createContext<SessionValue>({
  member: null,
  cartCount: 0,
  loaded: false,
  refresh: async () => {},
});

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [member, setMember] = useState<Member | null>(null);
  const [cartCount, setCartCount] = useState(0);
  const [loaded, setLoaded] = useState(false);

  const refresh = useCallback(async () => {
    const [me, cart] = await Promise.allSettled([
      api<{ member: Member | null }>("/auth/session"),
      api<CartResponse>("/cart"),
    ]);
    setMember(me.status === "fulfilled" ? me.value.member : null);
    setCartCount(
      cart.status === "fulfilled" ? cart.value.items.reduce((n, i) => n + i.quantity, 0) : 0,
    );
    setLoaded(true);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <SessionContext.Provider value={{ member, cartCount, loaded, refresh }}>
      {children}
    </SessionContext.Provider>
  );
}

export const useSession = () => useContext(SessionContext);
