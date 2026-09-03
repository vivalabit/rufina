"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, Bell, LoaderCircle, Trash2, X } from "lucide-react";

import {
  deleteCriticalNotification,
  fetchCriticalNotifications,
  type CriticalNotification,
} from "@/features/notifications/api/client";
import { cn } from "@/lib/utils";

export type { CriticalNotification } from "@/features/notifications/api/client";

export function CriticalNotificationsBell() {
  const [notifications, setNotifications] = useState<CriticalNotification[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [deletingId, setDeletingId] = useState("");
  const [error, setError] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);
  const deletedIdsRef = useRef(new Set<string>());

  const loadNotifications = useCallback(async (signal?: AbortSignal) => {
    try {
      const notifications = await fetchCriticalNotifications(signal);
      setNotifications(
        notifications.filter(
          (notification) => !deletedIdsRef.current.has(notification.id),
        ),
      );
      setError("");
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Critical notifications could not be loaded",
      );
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void loadNotifications(controller.signal);
    const intervalId = window.setInterval(() => {
      void loadNotifications(controller.signal);
    }, 30_000);
    return () => {
      controller.abort();
      window.clearInterval(intervalId);
    };
  }, [loadNotifications]);

  useEffect(() => {
    if (!isOpen) return;

    function closeOnOutsideClick(event: MouseEvent) {
      if (
        event.target instanceof Node
        && !containerRef.current?.contains(event.target)
      ) {
        setIsOpen(false);
      }
    }

    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setIsOpen(false);
    }

    document.addEventListener("mousedown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [isOpen]);

  async function deleteNotification(notification: CriticalNotification) {
    setDeletingId(notification.id);
    setError("");
    try {
      await deleteCriticalNotification(notification.id);
      deletedIdsRef.current.add(notification.id);
      setNotifications((current) =>
        current.filter((item) => item.id !== notification.id),
      );
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Critical notification could not be deleted",
      );
    } finally {
      setDeletingId("");
    }
  }

  const count = notifications.length;
  const buttonLabel = count
    ? `Critical notifications (${count})`
    : "Critical notifications";

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        aria-label={buttonLabel}
        title={buttonLabel}
        aria-haspopup="dialog"
        aria-expanded={isOpen}
        onClick={() => {
          setIsOpen((current) => !current);
          void loadNotifications();
        }}
        className={cn(
          "relative grid h-10 w-10 place-items-center rounded-md border border-transparent text-muted transition hover:border-[#e3d6c5] hover:bg-white hover:text-foreground",
          count > 0 && "border-[#fa5d00]/30 bg-[#fff8f1] text-[#d9480f]",
        )}
      >
        <Bell className="h-[18px] w-[18px]" />
        {count > 0 ? (
          <span className="absolute -right-1 -top-1 grid min-h-5 min-w-5 place-items-center rounded-full bg-[#d9480f] px-1 text-[10px] font-black text-white shadow-sm">
            {count > 99 ? "99+" : count}
          </span>
        ) : null}
      </button>

      {isOpen ? (
        <section
          role="dialog"
          aria-label="Critical notifications"
          className="absolute right-0 top-12 z-50 flex max-h-[min(560px,calc(100vh-80px))] w-[min(420px,calc(100vw-24px))] flex-col overflow-hidden rounded-xl border border-[#e3d6c5] bg-white shadow-[0_24px_70px_rgba(80,52,24,0.22)]"
        >
          <header className="flex items-start justify-between gap-4 border-b border-border bg-[#fff8f1] px-4 py-3.5">
            <div>
              <div className="flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-[#d9480f]" />
                <h2 className="text-sm font-black text-foreground">
                  Critical notifications
                </h2>
              </div>
              <p className="mt-1 text-xs leading-5 text-muted">
                Parser failures stay here until you delete them.
              </p>
            </div>
            <button
              type="button"
              aria-label="Close critical notifications"
              onClick={() => setIsOpen(false)}
              className="grid h-8 w-8 shrink-0 place-items-center rounded-md text-muted hover:bg-white hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </button>
          </header>

          {error ? (
            <p role="alert" className="border-b border-[#d9480f]/20 bg-[#fff4ed] px-4 py-2.5 text-xs font-semibold leading-5 text-[#b9380a]">
              {error}
            </p>
          ) : null}

          <div className="job-scroll min-h-[160px] overflow-y-auto">
            {isLoading && count === 0 ? (
              <div className="grid min-h-[160px] place-items-center text-muted">
                <LoaderCircle className="h-5 w-5 animate-spin" />
              </div>
            ) : count === 0 ? (
              <div className="grid min-h-[160px] place-items-center px-5 text-center">
                <div>
                  <Bell className="mx-auto h-6 w-6 text-muted" />
                  <p className="mt-2 text-sm font-bold text-foreground">
                    No critical notifications
                  </p>
                  <p className="mt-1 text-xs leading-5 text-muted">
                    Parser failures will appear here after all retry attempts fail.
                  </p>
                </div>
              </div>
            ) : (
              notifications.map((notification) => (
                <article
                  key={notification.id}
                  className="border-b border-border px-4 py-3.5 last:border-0"
                >
                  <div className="flex items-start gap-3">
                    <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full bg-[#fff0e7] text-[#d9480f]">
                      <AlertTriangle className="h-4 w-4" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <h3 className="text-sm font-black leading-5 text-foreground">
                            {notification.title}
                          </h3>
                          <p className="mt-0.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-[#d9480f]">
                            Failed after {notification.attempts} attempts
                          </p>
                        </div>
                        <button
                          type="button"
                          aria-label={`Delete ${notification.title}`}
                          title="Delete notification"
                          disabled={deletingId === notification.id}
                          onClick={() => void deleteNotification(notification)}
                          className="grid h-8 w-8 shrink-0 place-items-center rounded-md text-muted transition hover:bg-[#fff0e7] hover:text-[#d9480f] disabled:opacity-50"
                        >
                          {deletingId === notification.id ? (
                            <LoaderCircle className="h-4 w-4 animate-spin" />
                          ) : (
                            <Trash2 className="h-4 w-4" />
                          )}
                        </button>
                      </div>
                      <p className="mt-2 whitespace-pre-wrap break-words font-mono text-xs leading-5 text-[#5f5550] [overflow-wrap:anywhere]">
                        {notification.description}
                      </p>
                      <p className="mt-2 text-[11px] text-muted">
                        {formatNotificationTimestamp(notification.createdAt)}
                      </p>
                    </div>
                  </div>
                </article>
              ))
            )}
          </div>
        </section>
      ) : null}
    </div>
  );
}

function formatNotificationTimestamp(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}
