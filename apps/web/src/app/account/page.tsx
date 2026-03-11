"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getCurrentUser, logout, type User } from "@/lib/auth";

export default function AccountPage() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [theme, setTheme] = useState("dark");
  const router = useRouter();

  useEffect(() => {
    // 1. Check Auth Status (Route Protection)
    const currentUser = getCurrentUser();
    if (!currentUser) {
      router.push("/login"); // Not logged in, redirect
    } else {
      setUser(currentUser);
      
      // 2. Load Theme Preference
      const savedTheme = localStorage.getItem("triphony_theme") || "dark";
      setTheme(savedTheme);
      document.documentElement.setAttribute('data-theme', savedTheme);
      
      setLoading(false);
    }
  }, [router]);

  function handleLogout() {
    logout();
    router.push("/");
  }

  function toggleTheme() {
    const newTheme = theme === "dark" ? "light" : "dark";
    setTheme(newTheme);
    localStorage.setItem("triphony_theme", newTheme);
    document.documentElement.setAttribute('data-theme', newTheme);
  }

  if (loading) return null; // Prevent flash of content before redirect

  return (
    <section className="shell">
      <div className="rowBetween" style={{ marginBottom: "20px" }}>
        <div>
          <h1 className="h1">Account Settings</h1>
          <p className="p">Manage your profile, preferences, and billing.</p>
        </div>
        <button className="btn btnDanger" onClick={handleLogout}>Log Out</button>
      </div>

      <div className="accountGrid">
        {/* Profile Section */}
        <div className="cardFrame">
          <h2 className="panelTitle">Profile Information</h2>
          <div className="list" style={{ marginTop: "15px" }}>
            <div className="listRow">
              <span className="listTitle">Name</span>
              <span className="p">{user?.name}</span>
            </div>
            <div className="listRow">
              <span className="listTitle">Email</span>
              <span className="p">{user?.email}</span>
            </div>
            <div className="listRow">
              <span className="listTitle">Account ID</span>
              <span className="listMeta">{user?.id}</span>
            </div>
          </div>
        </div>

        {/* Preferences Section */}
        <div className="cardFrame">
          <h2 className="panelTitle">Preferences</h2>
          <div className="list" style={{ marginTop: "15px" }}>
            <div className="listRow" style={{ alignItems: "center" }}>
              <div>
                <div className="listTitle">Application Theme</div>
                <div className="listMeta">Switch between Light and Dark mode.</div>
              </div>
              <button className="btn" onClick={toggleTheme} style={{ minWidth: "120px" }}>
                {theme === "dark" ? "☀️ Light Mode" : "🌙 Dark Mode"}
              </button>
            </div>
          </div>
        </div>

        {/* License & Billing Section (MOCK DATA) */}
        <div className="cardFrame" style={{ gridColumn: "1 / -1" }}>
          <h2 className="panelTitle">License & Billing History</h2>
          <p className="p" style={{ marginBottom: "15px", fontSize: "14px" }}>
            View your active subscriptions and past transactions.
          </p>

          <div className="list">
            <div className="listRow">
              <div>
                <div className="listTitle cyanText">Pro Creator Tier (Active)</div>
                <div className="listMeta">Billed Monthly • Next charge: Oct 1, 2026</div>
              </div>
              <div className="row">
                <span className="p">$29.00</span>
                <button className="btn">Manage</button>
              </div>
            </div>

            <div className="listRow" style={{ opacity: 0.7 }}>
              <div>
                <div className="listTitle">Starter Trial (Expired)</div>
                <div className="listMeta">Ended: Sep 1, 2026</div>
              </div>
              <div className="row">
                <span className="p">$0.00</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
