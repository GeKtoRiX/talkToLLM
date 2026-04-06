export const sessionStates = [
  "idle",
  "listening",
  "capturing_speech",
  "transcribing",
  "thinking",
  "synthesizing",
  "speaking",
  "interrupted",
  "error",
] as const;

export type SessionState = (typeof sessionStates)[number];

export const clientEventTypes = [
  "session.start",
  "audio.chunk",
  "speech.start",
  "speech.end",
  "playback.interrupt",
  "session.stop",
] as const;

export type ClientEventType = (typeof clientEventTypes)[number];

export const serverEventTypes = [
  "session.started",
  "transcript.partial",
  "transcript.final",
  "llm.thinking",
  "response.text.delta",
  "response.text.final",
  "tts.chunk",
  "playback.stop",
  "error",
] as const;

export type ServerEventType = (typeof serverEventTypes)[number];

export interface VoiceEventEnvelope<TPayload = unknown, TType extends string = string> {
  type: TType;
  sessionId: string | null;
  turnId: string | null;
  seq: number;
  timestamp: string;
  payload: TPayload;
}

export interface SessionStartPayload {
  sampleRate: number;
  format: "pcm_s16le";
  language: "en";
}

export interface SpeechBoundaryPayload {
  reason?: string;
}

export interface TranscriptPayload {
  text: string;
  isFinal: boolean;
}

export interface ThinkingPayload {
  state: "thinking";
}

export interface ResponseTextPayload {
  text: string;
}

export interface TtsChunkPayload {
  audioBase64: string;
  mimeType: "audio/wav";
  chunkIndex: number;
  text: string;
}

export interface ErrorPayload {
  code: string;
  message: string;
}

export type ClientEnvelope =
  | VoiceEventEnvelope<SessionStartPayload, "session.start">
  | VoiceEventEnvelope<SpeechBoundaryPayload, "speech.start">
  | VoiceEventEnvelope<SpeechBoundaryPayload, "speech.end">
  | VoiceEventEnvelope<Record<string, never>, "playback.interrupt">
  | VoiceEventEnvelope<Record<string, never>, "session.stop">;

export type ServerEnvelope =
  | VoiceEventEnvelope<SessionStartPayload, "session.started">
  | VoiceEventEnvelope<TranscriptPayload, "transcript.partial">
  | VoiceEventEnvelope<TranscriptPayload, "transcript.final">
  | VoiceEventEnvelope<ThinkingPayload, "llm.thinking">
  | VoiceEventEnvelope<ResponseTextPayload, "response.text.delta">
  | VoiceEventEnvelope<ResponseTextPayload, "response.text.final">
  | VoiceEventEnvelope<TtsChunkPayload, "tts.chunk">
  | VoiceEventEnvelope<Record<string, never>, "playback.stop">
  | VoiceEventEnvelope<ErrorPayload, "error">;

export function createEnvelope<TPayload, TType extends string>(
  type: TType,
  payload: TPayload,
  options?: Partial<Pick<VoiceEventEnvelope<TPayload, TType>, "sessionId" | "turnId" | "seq" | "timestamp">>,
): VoiceEventEnvelope<TPayload, TType> {
  return {
    type,
    payload,
    sessionId: options?.sessionId ?? null,
    turnId: options?.turnId ?? null,
    seq: options?.seq ?? 0,
    timestamp: options?.timestamp ?? new Date().toISOString(),
  };
}

