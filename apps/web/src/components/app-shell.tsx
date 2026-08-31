import type { ReactNode } from "react";

type AppShellProps = {
  sidebar: ReactNode;
  children: ReactNode;
};

export function AppShell({ sidebar, children }: AppShellProps) {
  return (
    <main className="h-screen overflow-hidden bg-background text-foreground">
      <div className="rufina-wash fixed inset-0" />
      <div className="relative flex h-full w-full flex-col overflow-hidden bg-background/95">
        {sidebar}
        {children}
      </div>
    </main>
  );
}
