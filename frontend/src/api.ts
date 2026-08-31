import type { AppConfig, ChatResponse, HistoryTurn } from "./types";

const DEFAULT_CONFIG: AppConfig = {
  mode: "demo",
  app_name: "StratusGuide",
  version: "dev",
  model: "deterministic local demo",
  retrieval_strategy: "bm25+concept-expansion",
};

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`;
    try {
      const body = (await response.json()) as {
        detail?: string | { message?: string };
        error?: { message?: string };
      };
      if (body.error?.message) detail = body.error.message;
      if (typeof body.detail === "string") detail = body.detail;
      if (typeof body.detail === "object" && body.detail?.message) detail = body.detail.message;
    } catch {
      // Preserve the status-based fallback when the response is not JSON.
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export async function fetchConfig(signal?: AbortSignal): Promise<AppConfig> {
  try {
    const response = await fetch("/api/config", { signal });
    return await readJson<AppConfig>(response);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    return DEFAULT_CONFIG;
  }
}

export async function askCloudTutor(
  message: string,
  history: HistoryTurn[],
  signal?: AbortSignal,
): Promise<ChatResponse> {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, history, top_k: 4 }),
    signal,
  });
  return readJson<ChatResponse>(response);
}
