export type Role = "user" | "assistant";

export interface HistoryTurn {
  role: Role;
  content: string;
}

export interface Citation {
  id: string;
  title: string;
  section?: string;
  excerpt: string;
  score: number;
  uri?: string;
}

export interface RetrievedDocument {
  id?: string;
  title: string;
  score: number;
  keyword_score?: number;
  vector_score?: number;
}

export interface Trace {
  request_id?: string;
  mode: "demo" | "azure" | string;
  query: string;
  confidence: number;
  retrieval_ms: number;
  generation_ms: number;
  total_ms: number;
  retrieval_strategy?: string;
  retrieved_documents?: RetrievedDocument[];
}

export interface ChatResponse {
  answer: string;
  citations: Citation[];
  trace: Trace;
}

export interface AppConfig {
  mode: "demo" | "azure" | string;
  app_name?: string;
  version?: string;
  model?: string;
  retrieval_strategy?: string;
}

export interface ChatMessage {
  id: string;
  role: Role;
  content: string;
  citations?: Citation[];
  trace?: Trace;
  createdAt: Date;
  error?: boolean;
}
