"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { api, User } from "@/lib/api";

/**
 * Client-side auth gate. The backend /api/auth/me tells us who's logged in;
 * if anonymous AND the path isn't /login, redirect to /login.
 *
 * We don't gate on the backend yet (other endpoints remain open) — that's
 * intentional, so the login UX is what stands between anonymous users and
 * the rest of the app. Operators wanting strict isolation should also
 * reverse-proxy /api/* through their own auth layer.
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<User | null | undefined>(undefined);

  useEffect(() => {
    // Reset to loading on every route change so we never act on a
    // user value from a previous page (e.g. the LoginPage's local
    // setUser doesn't propagate here, but a /login → / redirect would
    // otherwise briefly see `user=null` from the first fetch and bounce
    // straight back to /login).
    setUser(undefined);
    let cancelled = false;
    (async () => {
      try {
        const me = await api.me();
        if (!cancelled) setUser(me);
      } catch {
        if (!cancelled) setUser(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [pathname]);

  useEffect(() => {
    if (user === undefined) return; // still loading
    if (!user && pathname !== "/login") {
      router.replace("/login");
    }
  }, [user, pathname, router]);

  if (user === undefined) {
    // Loading state — show a tiny splash so the page doesn't flash content.
    return (
      <div
        style={{
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--fg-subtle)",
          fontSize: 14,
        }}
      >
        <span>⏳</span>
      </div>
    );
  }

  // /login is always allowed even when anonymous.
  if (pathname === "/login") return <>{children}</>;
  // If we have a user, render children (otherwise the redirect effect above
  // will swap to /login on the next render).
  if (user) return <>{children}</>;
  return null;
}