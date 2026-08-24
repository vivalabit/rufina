"use client";

import { useEffect, useState } from "react";

export function useHydrationSafeCurrentTime() {
  const [currentTime, setCurrentTime] = useState<Date | null>(null);

  useEffect(() => {
    setCurrentTime(new Date());
    const interval = window.setInterval(
      () => setCurrentTime(new Date()),
      60_000,
    );
    return () => window.clearInterval(interval);
  }, []);

  return currentTime;
}

export function DashboardGreeting({
  name,
  currentTime,
}: {
  name: string;
  currentTime: Date | null;
}) {
  const firstName = name.trim().split(/\s+/)[0] ?? "";
  const hour = currentTime?.getHours();
  const greeting =
    hour === undefined
      ? "Hello"
      : hour >= 5 && hour < 12
        ? "Good morning"
        : hour >= 12 && hour < 17
          ? "Good afternoon"
          : hour >= 17 && hour < 22
            ? "Good evening"
            : "Hello, night owl";

  return (
    <h1 className="hero-title text-[36px] leading-[1.08] sm:text-[44px] 2xl:text-[52px]">
      {greeting}
      {firstName ? `, ${firstName}` : ""}!
    </h1>
  );
}
