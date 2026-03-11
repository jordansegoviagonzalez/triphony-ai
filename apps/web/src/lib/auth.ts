// Mock Authentication Service
// Replace these functions with real API calls to your FastAPI backend later.

export interface User {
  id: string;
  email: string;
  name: string;
}

const AUTH_KEY = "triphony_auth_token";
const USER_KEY = "triphony_user";

export async function login(email: string, password: string): Promise<{ token: string; user: User }> {
  // Simulate network delay
  await new Promise((resolve) => setTimeout(resolve, 500));

  // Basic validation
  if (!email || !password) {
    throw new Error("Email and password are required.");
  }

  // MOCK LOGIN: Accept any email/password for the prototype
  const user: User = {
    id: "user_" + Math.random().toString(36).substring(2, 9),
    email,
    name: email.split("@")[0], // Simple mock name based on email
  };
  const token = "mock_jwt_token_" + Date.now();

  if (typeof window !== "undefined") {
    localStorage.setItem(AUTH_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
    // Dispatch an event so other components (like layout) know auth state changed
    window.dispatchEvent(new Event("auth-change"));
  }

  return { token, user };
}

export async function register(email: string, password: string, name: string): Promise<{ token: string; user: User }> {
  // Simulate network delay
  await new Promise((resolve) => setTimeout(resolve, 500));

  if (!email || !password || !name) {
    throw new Error("All fields are required.");
  }

  // MOCK REGISTER: Auto-login after registration
  const user: User = {
    id: "user_" + Math.random().toString(36).substring(2, 9),
    email,
    name,
  };
  const token = "mock_jwt_token_" + Date.now();

  if (typeof window !== "undefined") {
    localStorage.setItem(AUTH_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
    window.dispatchEvent(new Event("auth-change"));
  }

  return { token, user };
}

export function logout() {
  if (typeof window !== "undefined") {
    localStorage.removeItem(AUTH_KEY);
    localStorage.removeItem(USER_KEY);
    window.dispatchEvent(new Event("auth-change"));
  }
}

export function getCurrentUser(): User | null {
  if (typeof window === "undefined") return null; // Handle SSR
  
  const userJson = localStorage.getItem(USER_KEY);
  if (!userJson) return null;

  try {
    return JSON.parse(userJson) as User;
  } catch (e) {
    return null;
  }
}

export function isAuthenticated(): boolean {
  if (typeof window === "undefined") return false;
  return !!localStorage.getItem(AUTH_KEY);
}
