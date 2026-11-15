/** Root layout: auth provider, service-worker registration (web), and the
 * route guard that keeps unauthenticated users on /login. */
import { useEffect } from "react";
import { Platform, Text, View } from "react-native";
import { Stack, useSegments, useRouter } from "expo-router";

import { AuthProvider, useAuth } from "@/auth/AuthContext";
import { colors } from "@/theme";

function RouteGuard() {
  const { status } = useAuth();
  const segments = useSegments();
  const router = useRouter();

  useEffect(() => {
    if (status === "loading") return;
    const inAuthArea = segments[0] === "login";
    if (status === "anon" && !inAuthArea) {
      router.replace("/login");
    } else if (status === "authed" && inAuthArea) {
      router.replace("/");
    }
  }, [status, segments, router]);

  return null;
}

function BootSplash() {
  return (
    <View style={{ flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.bg }}>
      <Text style={{ color: colors.muted }}>Tempo</Text>
    </View>
  );
}

function RootNavigator() {
  const { status } = useAuth();
  if (status === "loading") return <BootSplash />;

  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Screen name="login" />
      <Stack.Screen name="(tabs)" />
    </Stack>
  );
}

export default function RootLayout() {
  useEffect(() => {
    if (Platform.OS !== "web" || typeof document === "undefined") return;
    // PWA installability: the manifest link + title are injected at runtime
    // (a custom +html.tsx shell would drop the entry script tags).
    document.title = "Tempo";
    if (!document.querySelector('link[rel="manifest"]')) {
      const link = document.createElement("link");
      link.rel = "manifest";
      link.href = "/manifest.json";
      document.head.appendChild(link);
    }
    // Register the app-shell service worker.
    if (typeof navigator !== "undefined" && "serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => {
        // Service worker is an enhancement — never block the app.
      });
    }
  }, []);

  return (
    <AuthProvider>
      <RouteGuard />
      <RootNavigator />
    </AuthProvider>
  );
}
