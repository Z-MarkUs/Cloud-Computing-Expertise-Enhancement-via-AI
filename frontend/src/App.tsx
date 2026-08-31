import { FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowUp,
  BookOpenCheck,
  BrainCircuit,
  CheckCircle2,
  Cloud,
  Database,
  Gauge,
  Layers3,
  RefreshCcw,
  Search,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { askCloudTutor, fetchConfig } from "./api";
import type { AppConfig, ChatMessage, Citation, HistoryTurn, Trace } from "./types";

const SUGGESTED_PROMPTS = [
  "When should I choose serverless over containers?",
  "Explain the shared responsibility model with an example.",
  "How do availability zones improve resilience?",
  "Compare horizontal and vertical scaling.",
];

const INITIAL_CONFIG: AppConfig = {
  mode: "demo",
  app_name: "StratusGuide",
  version: "dev",
  model: "local grounded demo",
  retrieval_strategy: "bm25+concept-expansion",
};

function makeId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
}

function clampPercent(value: number): number {
  return Math.max(0, Math.min(100, Math.round(value <= 1 ? value * 100 : value)));
}

function formatLatency(value?: number): string {
  if (value === undefined || Number.isNaN(value)) return "—";
  return value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${Math.round(value)} ms`;
}

function Logo() {
  return (
    <div className="logo" aria-hidden="true">
      <Cloud size={22} strokeWidth={2.4} />
      <span className="logo-signal" />
    </div>
  );
}

function ModeBadge({ config }: { config: AppConfig }) {
  const azure = config.mode.toLowerCase() === "azure";
  return (
    <div className={`mode-badge ${azure ? "azure" : "demo"}`} title={`Runtime: ${config.mode}`}>
      <span className="status-dot" />
      {azure ? "Azure connected" : "Local demo"}
    </div>
  );
}

function Welcome({ onChoose }: { onChoose: (prompt: string) => void }) {
  return (
    <section className="welcome" aria-labelledby="welcome-title">
      <div className="eyebrow"><Sparkles size={14} /> Inspectable cloud intelligence</div>
      <h1 id="welcome-title">Cloud answers.<br /><span>Evidence included.</span></h1>
      <p>
        Explore architecture, security, reliability, and delivery practices with a tutor that shows
        what it retrieved—and how strongly the evidence matched.
      </p>
      <div className="suggestion-grid">
        {SUGGESTED_PROMPTS.map((prompt, index) => (
          <button key={prompt} type="button" className="suggestion" onClick={() => onChoose(prompt)}>
            <span>0{index + 1}</span>
            {prompt}
            <ArrowUp size={15} className="suggestion-arrow" />
          </button>
        ))}
      </div>
    </section>
  );
}

function CitationChips({ citations, onSelect }: { citations: Citation[]; onSelect: (item: Citation) => void }) {
  if (!citations.length) return null;
  return (
    <div className="citation-chips" aria-label="Answer sources">
      {citations.map((citation) => (
        <button key={citation.id} type="button" onClick={() => onSelect(citation)}>
          <BookOpenCheck size={13} />
          {citation.id} · {citation.title}
        </button>
      ))}
    </div>
  );
}

function MessageBubble({
  message,
  onSelectCitation,
}: {
  message: ChatMessage;
  onSelectCitation: (citation: Citation) => void;
}) {
  const assistant = message.role === "assistant";
  return (
    <article className={`message-row ${message.role}`} data-testid={`${message.role}-message`}>
      {assistant && <div className="message-avatar"><BrainCircuit size={17} /></div>}
      <div className={`message-bubble ${message.error ? "error" : ""}`}>
        {assistant ? (
          <div className="markdown-body">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
          </div>
        ) : (
          <p>{message.content}</p>
        )}
        {assistant && message.citations && (
          <CitationChips citations={message.citations} onSelect={onSelectCitation} />
        )}
        {assistant && message.trace && (
          <div className="answer-meta">
            <CheckCircle2 size={13} /> {message.citations?.length ? "Citations verified" : "Safely abstained"} · {formatLatency(message.trace.total_ms)}
          </div>
        )}
      </div>
    </article>
  );
}

function ThinkingRow() {
  return (
    <div className="message-row assistant" aria-live="polite" aria-label="Retrieving evidence">
      <div className="message-avatar"><BrainCircuit size={17} /></div>
      <div className="thinking-card">
        <div className="thinking-orbit"><span /><span /><span /></div>
        <div><strong>Tracing the answer</strong><small>Rewriting · retrieving · grounding</small></div>
      </div>
    </div>
  );
}

function Metric({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="metric">
      <span className="metric-icon">{icon}</span>
      <span><small>{label}</small><strong>{value}</strong></span>
    </div>
  );
}

function EvidencePanel({
  trace,
  citations,
  selectedCitation,
  onClearCitation,
}: {
  trace?: Trace;
  citations: Citation[];
  selectedCitation?: Citation;
  onClearCitation: () => void;
}) {
  const retrievalStrength = clampPercent(trace?.confidence ?? 0);
  const documents = trace?.retrieved_documents ?? [];
  const strategy = trace?.retrieval_strategy ?? "ranked retrieval";
  const usesVectors = /hybrid|vector|semantic/i.test(strategy);

  return (
    <aside className="evidence-panel" aria-label="Retrieval evidence">
      <div className="panel-heading">
        <div><span>Retrieval observatory</span><h2>Under the answer</h2></div>
        <div className="live-indicator"><span /> Live trace</div>
      </div>

      {selectedCitation ? (
        <section className="citation-detail">
          <button type="button" onClick={onClearCitation}>← Back to trace</button>
          <div className="source-number">SOURCE {selectedCitation.id}</div>
          <h3>{selectedCitation.title}</h3>
          {selectedCitation.section && <p className="source-section">{selectedCitation.section}</p>}
          <blockquote>{selectedCitation.excerpt}</blockquote>
          <div className="source-score">
            <span>Retrieval strength</span><strong>{clampPercent(selectedCitation.score)}%</strong>
          </div>
          <div className="score-track"><i style={{ width: `${clampPercent(selectedCitation.score)}%` }} /></div>
          {selectedCitation.uri && (
            <a href={selectedCitation.uri} target="_blank" rel="noreferrer">Open source ↗</a>
          )}
        </section>
      ) : trace ? (
        <>
          <section className="trace-summary">
            <div className="confidence-ring" style={{ "--confidence": `${retrievalStrength * 3.6}deg` } as React.CSSProperties}>
              <div><strong>{retrievalStrength}%</strong><small>retrieval strength</small></div>
            </div>
            <div className="query-block">
              <span>Planned query</span>
              <p>“{trace.query}”</p>
            </div>
          </section>

          <div className="metric-grid">
            <Metric icon={<Search size={16} />} label="Retrieval" value={formatLatency(trace.retrieval_ms)} />
            <Metric icon={<BrainCircuit size={16} />} label="Generation" value={formatLatency(trace.generation_ms)} />
            <Metric icon={<Gauge size={16} />} label="End to end" value={formatLatency(trace.total_ms)} />
            <Metric icon={<Layers3 size={16} />} label="Strategy" value={strategy} />
          </div>

          <section className="pipeline-card">
            <h3>Pipeline</h3>
            <ol>
              <li className="complete"><span>1</span><div><strong>Plan</strong><small>Conversation-aware query</small></div></li>
              <li className="complete"><span>2</span><div><strong>Retrieve</strong><small>{usesVectors ? "Keyword + vector signals" : "Lexical + concept signals"}</small></div></li>
              <li className="complete"><span>3</span><div><strong>Rank</strong><small>Scored evidence set</small></div></li>
              <li className="complete"><span>4</span><div><strong>Cite</strong><small>Verified source markers</small></div></li>
            </ol>
          </section>

          <section className="retrieved-card">
            <div className="section-title"><h3>Retrieved knowledge</h3><span>{documents.length || citations.length} {(documents.length || citations.length) === 1 ? "hit" : "hits"}</span></div>
            {(documents.length ? documents : citations).map((doc, index) => {
              const score = clampPercent(doc.score);
              return (
                <div className="retrieved-row" key={("id" in doc && doc.id) || `${doc.title}-${index}`}>
                  <span className="doc-rank">{String(index + 1).padStart(2, "0")}</span>
                  <div className="doc-main"><strong>{doc.title}</strong><div className="mini-track"><i style={{ width: `${score}%` }} /></div></div>
                  <span className="doc-score">{score}</span>
                </div>
              );
            })}
          </section>
        </>
      ) : (
        <div className="empty-trace">
          <div className="scan-graphic"><span /><span /><Search size={28} /></div>
          <h3>Evidence will appear here</h3>
          <p>Ask a question to inspect the planned query, ranked knowledge, retrieval strength, and latency.</p>
          <div className="principle-list">
            <span><ShieldCheck size={15} /> Source-grounded</span>
            <span><Database size={15} /> Inspectable retrieval</span>
            <span><Gauge size={15} /> Measured latency</span>
          </div>
        </div>
      )}
    </aside>
  );
}

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [config, setConfig] = useState<AppConfig>(INITIAL_CONFIG);
  const [loading, setLoading] = useState(false);
  const [selectedCitation, setSelectedCitation] = useState<Citation>();
  const abortRef = useRef<AbortController | undefined>(undefined);
  const conversationScrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const latestAssistant = useMemo(
    () => [...messages].reverse().find((message) => message.role === "assistant" && !message.error),
    [messages],
  );

  useEffect(() => {
    const controller = new AbortController();
    void fetchConfig(controller.signal).then(setConfig).catch(() => undefined);
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const scrollRegion = conversationScrollRef.current;
    if (scrollRegion) scrollRegion.scrollTop = scrollRegion.scrollHeight;
  }, [messages, loading]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const submit = async (raw?: string) => {
    const question = (raw ?? input).trim();
    if (!question || loading) return;

    const history: HistoryTurn[] = messages.slice(-8).map(({ role, content }) => ({ role, content }));
    const userMessage: ChatMessage = {
      id: makeId(),
      role: "user",
      content: question,
      createdAt: new Date(),
    };
    setMessages((current) => [...current, userMessage]);
    setInput("");
    setSelectedCitation(undefined);
    setLoading(true);

    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const result = await askCloudTutor(question, history, controller.signal);
      setMessages((current) => [
        ...current,
        {
          id: result.trace.request_id ?? makeId(),
          role: "assistant",
          content: result.answer,
          citations: result.citations,
          trace: result.trace,
          createdAt: new Date(),
        },
      ]);
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      const detail = error instanceof Error ? error.message : "The tutor could not answer that question.";
      setMessages((current) => [
        ...current,
        {
          id: makeId(),
          role: "assistant",
          content: `I couldn't complete that trace. ${detail}`,
          createdAt: new Date(),
          error: true,
        },
      ]);
    } finally {
      setLoading(false);
      abortRef.current = undefined;
      textareaRef.current?.focus();
    }
  };

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    void submit();
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void submit();
    }
  };

  const reset = () => {
    abortRef.current?.abort();
    setMessages([]);
    setInput("");
    setLoading(false);
    setSelectedCitation(undefined);
  };

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="StratusGuide home">
          <Logo />
          <div><strong>StratusGuide</strong><span>Cloud systems, clearly</span></div>
        </a>
        <div className="topbar-actions">
          <ModeBadge config={config} />
          {messages.length > 0 && (
            <button type="button" className="reset-button" onClick={reset}>
              <RefreshCcw size={14} /> New trace
            </button>
          )}
          <a className="github-link" href="https://github.com/Z-MarkUs/Cloud-Computing-Expertise-Enhancement-via-AI" target="_blank" rel="noreferrer">
            View source <span>↗</span>
          </a>
        </div>
      </header>

      <main className="workspace">
        <section className="conversation-panel">
          <div className="conversation-scroll" ref={conversationScrollRef}>
            {messages.length === 0 ? (
              <Welcome onChoose={(prompt) => void submit(prompt)} />
            ) : (
              <div className="message-list">
                {messages.map((message) => (
                  <MessageBubble key={message.id} message={message} onSelectCitation={setSelectedCitation} />
                ))}
                {loading && <ThinkingRow />}
              </div>
            )}
          </div>

          <div className="composer-wrap">
            <form className="composer" onSubmit={handleSubmit}>
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask about architecture, security, reliability…"
                aria-label="Cloud computing question"
                rows={1}
                maxLength={2000}
                disabled={loading}
              />
              <button type="submit" disabled={!input.trim() || loading} aria-label="Send question">
                <ArrowUp size={19} />
              </button>
            </form>
            <div className="composer-meta">
              <span><ShieldCheck size={12} /> Answers cite retrieved knowledge</span>
              <span>Enter to send · Shift + Enter for a new line</span>
            </div>
          </div>
        </section>

        <EvidencePanel
          trace={latestAssistant?.trace}
          citations={latestAssistant?.citations ?? []}
          selectedCitation={selectedCitation}
          onClearCitation={() => setSelectedCitation(undefined)}
        />
      </main>

      <footer>
        <span>Built for transparent RAG—not answer theater.</span>
        <span>{config.model ?? "local demo"} · v{config.version ?? "dev"}</span>
      </footer>
    </div>
  );
}
