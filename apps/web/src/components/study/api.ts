/**
 * API client for the /api/training/* endpoints.
 * Mirrors the pattern established in StudyPanel.tsx.
 */
import type {
  AnswerResult,
  CreateSessionRequest,
  ExtendedStudyItem,
  ItemProgress,
  SessionQuestion,
  SessionResults,
  TrainingSession,
  UserStats,
} from "./types";

const BASE =
  (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000") +
  "/api/training";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (res.status === 204) return undefined as unknown as T;
  const json = await res.json();
  if (!res.ok) {
    const detail = typeof json?.detail === "string" ? json.detail : res.statusText;
    throw new Error(detail);
  }
  return json as T;
}

export type CreateSessionResponse = {
  session: TrainingSession;
  question: SessionQuestion | null;
};

export const trainingApi = {
  createSession: (req: CreateSessionRequest): Promise<CreateSessionResponse> =>
    apiFetch("/sessions", {
      method: "POST",
      body: JSON.stringify(req),
    }),

  getSession: (
    sessionId: number
  ): Promise<{
    session: TrainingSession;
    current_question: SessionQuestion | null;
    questions_remaining: number;
  }> => apiFetch(`/sessions/${sessionId}`),

  submitAnswer: (
    sessionId: number,
    questionId: number,
    answerGiven: string
  ): Promise<AnswerResult> =>
    apiFetch(`/sessions/${sessionId}/answer`, {
      method: "POST",
      body: JSON.stringify({ question_id: questionId, answer_given: answerGiven }),
    }),

  completeSession: (sessionId: number): Promise<SessionResults> =>
    apiFetch(`/sessions/${sessionId}/complete`, { method: "POST", body: "{}" }),

  getSessionResults: (sessionId: number): Promise<SessionResults> =>
    apiFetch(`/sessions/${sessionId}/results`),

  getItemProgress: (itemId: number): Promise<ItemProgress> =>
    apiFetch(`/progress/${itemId}`),

  getUserStats: (): Promise<UserStats> => apiFetch("/stats/user"),

  getItems: (params?: Record<string, string | number | undefined>): Promise<ExtendedStudyItem[]> => {
    const qs = params
      ? "?" +
        Object.entries(params)
          .filter(([, v]) => v !== undefined && v !== null && v !== "")
          .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
          .join("&")
      : "";
    return apiFetch(`/items${qs}`);
  },
};
