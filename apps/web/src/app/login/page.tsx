"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { login } from "@/lib/auth";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      await login(email, password);
      router.push("/account"); // Redirect to account dashboard
    } catch (err: any) {
      setError(err.message || "Failed to log in.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="shell authShell">
      <div className="cardFrame authCard">
        <h1 className="h1" style={{ textAlign: "center", marginBottom: "20px" }}>Welcome Back</h1>
        
        {error && <div className="errorBanner">{error}</div>}

        <form onSubmit={handleSubmit} className="authForm">
          <div className="formGroup">
            <label>Email Address</label>
            <input 
              type="email" 
              className="promptInput" 
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              required 
            />
          </div>

          <div className="formGroup">
            <label>Password</label>
            <input 
              type="password" 
              className="promptInput" 
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              required 
            />
          </div>

          <button type="submit" className="btn btnPrimary authBtn" disabled={loading}>
            {loading ? "Logging in..." : "Log In"}
          </button>
        </form>

        <p className="p" style={{ textAlign: "center", marginTop: "20px" }}>
          Don't have an account? <Link href="/register" className="cyanText">Sign Up</Link>
        </p>
      </div>
    </section>
  );
}
