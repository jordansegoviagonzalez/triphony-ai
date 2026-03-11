"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { register } from "@/lib/auth";

export default function RegisterPage() {
  const [name, setName] = useState("");
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
      await register(email, password, name);
      router.push("/account"); // Redirect to account dashboard
    } catch (err: any) {
      setError(err.message || "Failed to register.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="shell authShell">
      <div className="cardFrame authCard">
        <h1 className="h1" style={{ textAlign: "center", marginBottom: "20px" }}>Create Account</h1>
        
        {error && <div className="errorBanner">{error}</div>}

        <form onSubmit={handleSubmit} className="authForm">
          <div className="formGroup">
            <label>Full Name</label>
            <input 
              type="text" 
              className="promptInput" 
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Jordan Segovia"
              required 
            />
          </div>

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
              minLength={6}
            />
          </div>

          <button type="submit" className="btn btnPrimary authBtn" disabled={loading}>
            {loading ? "Creating Account..." : "Sign Up"}
          </button>
        </form>

        <p className="p" style={{ textAlign: "center", marginTop: "20px" }}>
          Already have an account? <Link href="/login" className="cyanText">Log In</Link>
        </p>
      </div>
    </section>
  );
}
