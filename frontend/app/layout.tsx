import type { Metadata } from "next";
import { Header } from "@/components/Header";
import { SessionProvider } from "@/components/Session";
import "./globals.css";

export const metadata: Metadata = {
  title: "EC DEMO（学習用）",
  description: "tech0 Step4 Lv3 個人課題。GUオンラインストアの要件定義にもとづく学習用の実装（非公式）",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ja">
      <body>
        <SessionProvider>
          <Header />
          <main className="container">{children}</main>
        </SessionProvider>
      </body>
    </html>
  );
}
