import "./globals.css";
import Link from "next/link";

export const metadata = {
  title: "AI Art Studio",
  description: "Cinematic scene workflow studio"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="topbar">
          <div className="topbarInner">
            <div className="brand">
              <img className="brandLogo" src="/branding/triphony_icon_transparent.png" alt="TRIPHONY logo" />
              <div className="brandText">AI Art Studio</div>
            </div>

            <nav className="nav">
              <Link href="/">Home</Link>
              <Link href="/studio">Studio</Link>
              <Link href="/library">Library</Link>
            </nav>
          </div>
        </header>

        <main className="main">{children}</main>
      </body>
    </html>
  );
}
