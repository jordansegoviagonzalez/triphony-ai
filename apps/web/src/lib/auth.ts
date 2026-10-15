import { request } from "@/lib/api";

export interface User {
  id: string;
  email: string;
  name: string;
  created_at?: string;
}

type AuthResponse = { user: User };

export async function login(email: string, password: string): Promise<AuthResponse> {
  if (!email || !password) {
    throw new Error("Email and password are required.");
  }

  const body = new URLSearchParams({ username: email, password });
  const result = await request<AuthResponse>("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: body.toString()
  });
  notifyAuthChange();
  return result;
}

export async function register(email: string, password: string, name: string): Promise<AuthResponse> {
  if (!email || !password || !name) {
    throw new Error("All fields are required.");
  }

  const result = await request<AuthResponse>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password, name })
  });
  notifyAuthChange();
  return result;
}

export async function logout(): Promise<void> {
  await request<{ ok: boolean }>("/auth/logout", { method: "POST" });
  notifyAuthChange();
}

export async function getCurrentUser(): Promise<User | null> {
  try {
    return await request<User>("/auth/me");
  } catch {
    return null;
  }
}

export async function isAuthenticated(): Promise<boolean> {
  return (await getCurrentUser()) !== null;
}

function notifyAuthChange() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event("auth-change"));
  }
}
