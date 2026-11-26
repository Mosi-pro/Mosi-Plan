import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, setCsrf, setUnauthorizedHandler } from "@/lib/api";
import type { User } from "@/lib/types";

interface AuthState { user: User | null; loading: boolean; login: (u: string, p: string) => Promise<void>; logout: () => Promise<void>; setUser: (u: User) => void }
const Ctx = createContext<AuthState>(null as unknown as AuthState);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const qc = useQueryClient();

  useEffect(() => {
    setUnauthorizedHandler(() => { setUser(null); qc.clear(); });
    api.get<{ user: User; csrf_token: string }>("/api/auth/me")
      .then((r) => { setCsrf(r.csrf_token); setUser(r.user); })
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, [qc]);

  const login = useCallback(async (username: string, password: string) => {
    const r = await api.post<{ user: User; csrf_token: string }>("/api/auth/login", { username, password });
    setCsrf(r.csrf_token);
    setUser(r.user);
  }, []);
  const logout = useCallback(async () => {
    try { await api.post("/api/auth/logout"); } finally { setUser(null); qc.clear(); }
  }, [qc]);

  return <Ctx.Provider value={{ user, loading, login, logout, setUser }}>{children}</Ctx.Provider>;
}
export const useAuth = () => useContext(Ctx);
