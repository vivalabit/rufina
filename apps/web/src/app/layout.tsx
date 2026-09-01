import type { Metadata } from "next";
import "./globals.css";

import { AppProviders } from "./providers";

export const metadata: Metadata = {
  title: "Rufina",
  description: "Personal AI career assistant dashboard.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body suppressHydrationWarning>
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
