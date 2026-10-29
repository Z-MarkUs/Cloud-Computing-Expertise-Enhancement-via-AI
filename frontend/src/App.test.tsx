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

  it("opens and dismisses citations repeatedly, then starts a clean trace", async () => {
    const user = userEvent.setup();
    const fetchMock = installFetchMock();
    render(<App />);

    await user.click(screen.getByRole("button", { name: /availability zones improve resilience/i }));
    await screen.findByTestId("assistant-message");

    for (let attempt = 0; attempt < 2; attempt += 1) {
      await user.click(screen.getByRole("button", { name: /resilience and availability zones/i }));
      expect(screen.getByText(chatResponse.citations[0].excerpt)).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: /back to trace/i }));
      expect(screen.queryByText(chatResponse.citations[0].excerpt)).not.toBeInTheDocument();
      expect(screen.getByText(/availability zones resilience/i)).toBeInTheDocument();
    }

    await user.click(screen.getByRole("button", { name: /new trace/i }));
    expect(screen.getByRole("heading", { name: /cloud answers/i })).toBeInTheDocument();
    expect(screen.queryByTestId("assistant-message")).not.toBeInTheDocument();
    expect(screen.getByText(/evidence will appear here/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /horizontal and vertical scaling/i }));
    await screen.findByTestId("assistant-message");
    const chatCalls = fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/api/chat"));
    expect(chatCalls).toHaveLength(2);
    expect(JSON.parse(String(chatCalls[1][1]?.body))).toMatchObject({ history: [] });
    expect(screen.getAllByTestId("user-message")).toHaveLength(1);
  });

  it("aborts an in-flight request on reset and accepts a new question", async () => {
    const user = userEvent.setup();
    const fetchMock = installFetchMock();
    const originalFetch = fetchMock.getMockImplementation()!;
    let delayedSignal: AbortSignal | null | undefined;
    fetchMock.mockImplementation((input, init) => {
      if (String(input).endsWith("/api/chat") && !delayedSignal) {
        delayedSignal = init?.signal;
        return new Promise<Response>((_resolve, reject) => {
          delayedSignal?.addEventListener("abort", () => {
            reject(new DOMException("Request aborted", "AbortError"));
          }, { once: true });
        });
      }
      return originalFetch(input, init);
    });
    render(<App />);

    await user.click(screen.getByRole("button", { name: /availability zones improve resilience/i }));
    expect(screen.getByRole("textbox", { name: /cloud computing question/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /send question/i })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: /new trace/i }));
    expect(delayedSignal?.aborted).toBe(true);
    expect(screen.queryByLabelText(/retrieving evidence/i)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /horizontal and vertical scaling/i }));
    await screen.findByTestId("assistant-message");
    expect(screen.getAllByTestId("user-message")).toHaveLength(1);
    expect(screen.getByTestId("user-message")).toHaveTextContent(/horizontal and vertical scaling/i);
    expect(screen.getAllByTestId("assistant-message")).toHaveLength(1);
  });
});
