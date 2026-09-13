import { randomUUID } from "node:crypto";
import { readFile, realpath } from "node:fs/promises";
import { dirname, join } from "node:path";
import { pathToFileURL } from "node:url";

function sessionKey(request) {
  const requested = String(request.sessionId || "").trim();
  if (!requested || requested.startsWith("agent:")) {
    return requested || undefined;
  }
  const agentId = String(request.agentId || "main").trim() || "main";
  return `agent:${agentId}:${requested}`;
}

async function main() {
  const requestPath = process.argv[2];
  if (!requestPath) {
    throw new Error("A multimodal request file is required");
  }

  const request = JSON.parse(await readFile(requestPath, "utf8"));
  const executable = await realpath(request.openclawExecutable);
  const openclawRoot = dirname(executable);
  const runtimeUrl = pathToFileURL(
    join(openclawRoot, "dist/plugin-sdk/agent-runtime.js"),
  ).href;
  const runtimeEnvironmentUrl = pathToFileURL(
    join(openclawRoot, "dist/plugin-sdk/runtime-env.js"),
  ).href;
  const [{ agentCommand }, { routeLogsToStderr }] = await Promise.all([
    import(runtimeUrl),
    import(runtimeEnvironmentUrl),
  ]);
  routeLogsToStderr();
  const runtime = {
    log() {},
    error(...values) {
      process.stderr.write(`${values.map(String).join(" ")}\n`);
    },
    exit(code) {
      throw new Error(`OpenClaw requested exit ${code}`);
    },
  };

  const result = await agentCommand(
    {
      message: request.prompt,
      agentId: request.agentId || undefined,
      sessionKey: sessionKey(request),
      model: request.model || undefined,
      allowModelOverride: Boolean(request.model),
      senderIsOwner: true,
      thinking: request.thinking || "off",
      timeout: String(request.timeoutSeconds),
      images: request.images.map(({ data, mimeType }) => ({
        type: "image",
        data,
        mimeType,
      })),
      json: true,
      deliver: false,
      toolsAllow: [],
      runId: randomUUID(),
    },
    runtime,
  );
  await new Promise((resolve, reject) => {
    process.stdout.write(JSON.stringify(result), (error) => {
      if (error) {
        reject(error);
      } else {
        resolve();
      }
    });
  });
}

main().then(
  () => process.exit(0),
  (error) => {
    process.stderr.write(`${error?.stack || error}\n`, () => process.exit(1));
  },
);
