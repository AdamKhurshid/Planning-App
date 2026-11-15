/** Auth state: token in AsyncStorage (localStorage on web), validated
 * against /api/auth/me/ at boot. Route guarding lives in app/_layout.tsx. */
import AsyncStorage from "@react-native-async-storage/async-storage";
import { createContext, useContext, useEffect, useMemo, useState } from "react";

import { setAuthToken } from "@/api/client";
import { endpoints, Profile, UserInfo } from "@/api/endpoints";

const TOKEN_KEY = "tempo/token";

type AuthStatus = "loading" | "anon" | "authed";

interface AuthState {
  status: AuthStatus;
  user: UserInfo | null;
  profile: Profile | null;
}

interface AuthContextValue extends AuthState {
  signIn: (password: string) => Promise<void>;
  signOut: () => Promise<void>;
  refreshProfile: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue>({
  status: "loading",
  user: null,
  profile: null,
  signIn: async () => {},
  signOut: async () => {},
  refreshProfile: async () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: "loading", user: null, profile: null });

  // Boot: restore token, validate it against the server.
  useEffect(() => {
    (async () => {
      const token = await AsyncStorage.getItem(TOKEN_KEY);
      if (!token) {
        setState({ status: "anon", user: null, profile: null });
        return;
      }
      setAuthToken(token);
      try {
        const me = await endpoints.me();
        setState({ status: "authed", user: me.user, profile: me.profile });
      } catch (error: unknown) {
        const status = (error as { status?: number }).status;
        if (status === 401) {
          // Token invalid/expired on the server: forget it.
          setAuthToken(null);
          await AsyncStorage.removeItem(TOKEN_KEY);
          setState({ status: "anon", user: null, profile: null });
        } else {
          // Server unreachable — keep the token (user stays signed in
          // locally; data screens will show connection errors).
          setState({ status: "authed", user: null, profile: null });
        }
      }
    })();
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      ...state,
      signIn: async (password: string) => {
        const { token } = await endpoints.login(password);
        setAuthToken(token);
        await AsyncStorage.setItem(TOKEN_KEY, token);
        try {
          const me = await endpoints.me();
          setState({ status: "authed", user: me.user, profile: me.profile });
        } catch {
          setState({ status: "authed", user: null, profile: null });
        }
      },
      signOut: async () => {
        try {
          await endpoints.logout();
        } catch {
          // Logging out offline: still clear the local session.
        }
        setAuthToken(null);
        await AsyncStorage.removeItem(TOKEN_KEY);
        setState({ status: "anon", user: null, profile: null });
      },
      refreshProfile: async () => {
        try {
          const me = await endpoints.me();
          setState((prev) => ({ ...prev, user: me.user, profile: me.profile }));
        } catch {
          // ignore transient errors
        }
      },
    }),
    [state],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  return useContext(AuthContext);
}
