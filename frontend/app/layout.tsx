export const metadata = {
  title: "BotGroup · Multi-bot group chat",
  description: "Configure multiple AI bots and let them discuss in groups.",
  icons: { icon: "/favicon.svg" },
};

import "./globals.css";
import type { ReactNode } from "react";
import { ToastProvider } from "@/components/ui";
import { SidebarProvider } from "@/components/SidebarContext";
import { I18nProvider } from "@/lib/i18n";
import { AuthGate } from "@/components/AuthGate";

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <I18nProvider>
          <ToastProvider>
            <SidebarProvider>
              <AuthGate>{children}</AuthGate>
            </SidebarProvider>
          </ToastProvider>
        </I18nProvider>
      </body>
    </html>
  );
}