import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { SettingsView } from "@/components/settings-view";
import { defaultAppSettings } from "@/features/settings/model/defaults";
import type { AppSettings } from "@/features/settings/model/types";

const configuredSettings: AppSettings = {
  ...defaultAppSettings,
  has_brightdata_api_key: true,
  brightdata_api_key_preview: "brig****-key",
  openai_api_key_configured: true,
  openai_api_key_preview: "sk-e****-key",
};

function renderSettingsView(
  overrides: Partial<React.ComponentProps<typeof SettingsView>> = {},
) {
  const props: React.ComponentProps<typeof SettingsView> = {
    settings: configuredSettings,
    showLogs: true,
    status: "idle",
    message: "",
    aiStatus: "idle",
    aiMessage: "",
    onConnectionDraftChange: vi.fn(),
    onSaveConnection: vi.fn().mockResolvedValue(undefined),
    onSaveAi: vi.fn(),
    onShowLogsChange: vi.fn(),
    ...overrides,
  };

  render(<SettingsView {...props} />);
  return props;
}

it("delegates logs and Bright Data settings through controlled props", () => {
  const props = renderSettingsView();

  expect(
    screen.getByRole("heading", { name: "Settings" }),
  ).toBeInTheDocument();
  const logsToggle = screen.getByRole("button", { name: "Show logs" });
  expect(logsToggle).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(logsToggle);
  expect(props.onShowLogsChange).toHaveBeenCalledWith(false);

  fireEvent.change(screen.getByLabelText(/Bright Data API key/), {
    target: { value: "rotated-key" },
  });
  expect(props.onConnectionDraftChange).toHaveBeenCalledOnce();

  fireEvent.click(screen.getByRole("button", { name: "Save settings" }));
  fireEvent.click(screen.getByRole("button", { name: "Clear key" }));
  expect(props.onSaveConnection).toHaveBeenNthCalledWith(1, "rotated-key");
  expect(props.onSaveConnection).toHaveBeenNthCalledWith(2, "");

  fireEvent.click(
    screen.getByRole("button", { name: "Delete saved OpenAI API key" }),
  );
  expect(props.onSaveAi).toHaveBeenCalledWith({
    ai_backend: "openclaw_codex",
    openai_api_key: "",
  });
});

it("keeps AI drafts local and emits one normalized settings update", () => {
  const onSaveAi = vi.fn();
  renderSettingsView({ onSaveAi });

  fireEvent.click(screen.getByRole("radio", { name: /OpenAI API/ }));
  fireEvent.change(screen.getByLabelText("OpenAI model"), {
    target: { value: "gpt-5.6-sol" },
  });
  fireEvent.change(
    screen.getByRole("combobox", { name: "OpenAI reasoning effort" }),
    { target: { value: "high" } },
  );
  fireEvent.change(screen.getByLabelText("Full AI Match model"), {
    target: { value: "openai/gpt-5.6-luna" },
  });
  fireEvent.change(
    screen.getByRole("spinbutton", { name: "Full AI Match batch size" }),
    { target: { value: "4" } },
  );
  fireEvent.click(screen.getByRole("switch", { name: "Auto AI Match" }));
  fireEvent.click(screen.getByRole("button", { name: "Save AI settings" }));

  expect(onSaveAi).toHaveBeenCalledWith(
    expect.objectContaining({
      ai_backend: "openai_api",
      openai_api_model: "gpt-5.6-sol",
      openai_api_reasoning_effort: "high",
      ai_match_model: "openai/gpt-5.6-luna",
      ai_match_batch_size: 4,
      auto_ai_match_enabled: true,
      job_screening_model: configuredSettings.job_screening_model,
    }),
  );
  expect(onSaveAi.mock.calls[0][0]).not.toHaveProperty("openai_api_key");
});

it("blocks OpenAI API mode until its draft is valid", () => {
  const props = renderSettingsView({
    settings: {
      ...configuredSettings,
      openai_api_key_configured: false,
      openai_api_key_preview: "",
    },
  });

  fireEvent.click(screen.getByRole("radio", { name: /OpenAI API/ }));
  const saveButton = screen.getByRole("button", {
    name: "Save AI settings",
  });
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Add an OpenAI API key before enabling this mode.",
  );
  expect(saveButton).toBeDisabled();

  fireEvent.change(screen.getByLabelText("OpenAI API key"), {
    target: { value: "  sk-test-key  " },
  });
  fireEvent.change(
    screen.getByRole("spinbutton", { name: "OpenAI timeout seconds" }),
    { target: { value: "5" } },
  );
  expect(screen.getByRole("alert")).toHaveTextContent(
    "OpenAI timeout must be between 10 and 600 seconds.",
  );
  expect(saveButton).toBeDisabled();

  fireEvent.change(
    screen.getByRole("spinbutton", { name: "OpenAI timeout seconds" }),
    { target: { value: "90" } },
  );
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  fireEvent.click(saveButton);
  expect(props.onSaveAi).toHaveBeenCalledWith(
    expect.objectContaining({
      ai_backend: "openai_api",
      openai_api_key: "sk-test-key",
      openai_api_timeout_seconds: 90,
    }),
  );
});
