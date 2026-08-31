import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const chatResponse = {
  answer: "Use **availability zones** to isolate failures while keeping services close enough for low-latency replication.",
  citations: [
    {
      id: "resilience-az",
      title: "Resilience and availability zones",
      section: "Failure domains",
      excerpt: "Availability zones are separate failure domains within one region.",
      score: 0.94,
    },
  ],
  trace: {
    request_id: "req-test",
    mode: "demo",
    query: "availability zones resilience",
    confidence: 0.91,
    retrieval_ms: 8,
    generation_ms: 2,
    total_ms: 10,
    retrieval_strategy: "bm25+concept-expansion",
    retrieved_documents: [
      {
        id: "resilience-az",
        title: "Resilience and availability zones",
        score: 0.94,
        keyword_score: 0.9,
        vector_score: 0.88,
      },
    ],
  },
};

function installFetchMock(chatStatus = 200) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/api/config")) {
      return new Response(
        JSON.stringify({ mode: "demo", app_name: "StratusGuide", version: "1.0.0", model: "local demo" }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }
    if (url.endsWith("/api/chat")) {
      if (chatStatus !== 200) {
        return new Response(JSON.stringify({ error: { message: "Retrieval service unavailable" } }), {
          status: chatStatus,
          headers: { "Content-Type": "application/json" },
        });
      }
      expect(init?.method).toBe("POST");
      return new Response(JSON.stringify(chatResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    throw new Error(`Unexpected fetch: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("StratusGuide", () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("presents an accessible showcase landing state", async () => {
    installFetchMock();
    render(<App />);

    expect(screen.getByRole("heading", { name: /cloud answers/i })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: /cloud computing question/i })).toBeInTheDocument();
    expect(screen.getByText(/evidence will appear here/i)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/local demo/i)).toBeInTheDocument());
  });

  it("submits a suggested question and renders grounded evidence", async () => {
    const user = userEvent.setup();
    const fetchMock = installFetchMock();
    render(<App />);

    await user.click(screen.getByRole("button", { name: /availability zones improve resilience/i }));

    expect(await screen.findByTestId("assistant-message")).toHaveTextContent(/use availability zones/i);
    expect(screen.getByText(/availability zones resilience/i)).toBeInTheDocument();
    expect(screen.getByText("91%")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /resilience and availability zones/i })).toBeInTheDocument();

    const chatCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/api/chat"));
    const body = JSON.parse(String(chatCall?.[1]?.body)) as { message: string; history: unknown[]; top_k: number };
    expect(body.message).toMatch(/availability zones/i);
    expect(body.history).toEqual([]);
    expect(body.top_k).toBe(4);
  });

  it("surfaces a safe API error without losing the conversation", async () => {
    const user = userEvent.setup();
    installFetchMock(503);
    render(<App />);

    const input = screen.getByRole("textbox", { name: /cloud computing question/i });
    await user.type(input, "How should I design retries?");
    await user.click(screen.getByRole("button", { name: /send question/i }));

    expect(await screen.findByText(/retrieval service unavailable/i)).toBeInTheDocument();
    expect(screen.getByText("How should I design retries?")).toBeInTheDocument();
  });
});
