export type AppLogLevel = "info" | "success" | "warning" | "error";

export type AppLogEntry = {
  id: string;
  timestamp: string;
  level: AppLogLevel;
  area: string;
  message: string;
  details?: string;
};
