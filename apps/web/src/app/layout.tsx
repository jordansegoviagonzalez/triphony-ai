"use client";

import "./globals.css";
import Link from "next/link";
import { useEffect, useState } from "react";
import { isAuthenticated } from "@/lib/auth";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const [loggedIn, setLoggedIn] = useState(false);

  // Check auth state on mount and listen for changes
  useEffect(() => {
    setLoggedIn(isAuthenticated());

    const handleAuthChange = () => setLoggedIn(isAuthenticated());
    window.addEventListener("auth-change", handleAuthChange);

    return () => window.removeEventListener("auth-change", handleAuthChange);
  }, []);

  return (
    <html lang="en">
      <head>
        <title>AI Art Studio</title>
        <script
          dangerouslySetInnerHTML={{
            __html: `
              try {
                if (localStorage.getItem('triphony_theme') === 'light') {
                  document.documentElement.setAttribute('data-theme', 'light');
                } else {
                  document.documentElement.setAttribute('data-theme', 'dark');
                }
              } catch (_) {}
            `,
          }}
        />
      </head>
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
              {loggedIn ? (
                <Link href="/account" className="btn btnPrimary" style={{ padding: "6px 14px", borderRadius: "10px" }}>Account</Link>
              ) : (
                <Link href="/login" className="btn" style={{ padding: "6px 14px", borderRadius: "10px" }}>Log In</Link>
              )}
            </nav>
          </div>
        </header>

        <main className="main">{children}</main>
      </body>
    </html>
  );
}

