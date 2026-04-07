import type { SessionState } from "@talktollm/contracts";

export type SessionAction =
  | "session_started"
  | "speech_started"
  | "text_submitted"
  | "speech_ended"
  | "transcript_finalized"
  | "llm_thinking"
  | "tts_started"
  | "playback_started"
  | "playback_interrupted"
  | "session_stopped"
  | "failed";

const transitions: Record<SessionState, Partial<Record<SessionAction, SessionState>>> = {
  idle: {
    session_started: "listening",
    failed: "error",
  },
  listening: {
    speech_started: "capturing_speech",
    text_submitted: "thinking",
    session_stopped: "idle",
    failed: "error",
  },
  capturing_speech: {
    speech_ended: "transcribing",
    text_submitted: "thinking",
    playback_interrupted: "interrupted",
    failed: "error",
  },
  transcribing: {
    transcript_finalized: "thinking",
    text_submitted: "thinking",
    session_stopped: "idle",
    failed: "error",
  },
  thinking: {
    llm_thinking: "thinking",
    text_submitted: "thinking",
    tts_started: "synthesizing",
    session_stopped: "idle",
    failed: "error",
  },
  synthesizing: {
    text_submitted: "thinking",
    playback_started: "speaking",
    playback_interrupted: "interrupted",
    failed: "error",
  },
  speaking: {
    speech_started: "capturing_speech",
    text_submitted: "thinking",
    playback_interrupted: "interrupted",
    session_stopped: "idle",
    failed: "error",
  },
  interrupted: {
    speech_started: "capturing_speech",
    text_submitted: "thinking",
    session_stopped: "idle",
    failed: "error",
  },
  error: {
    session_stopped: "idle",
    session_started: "listening",
    speech_started: "capturing_speech",
    text_submitted: "thinking",
  },
};

export function transitionSessionState(current: SessionState, action: SessionAction): SessionState {
  return transitions[current][action] ?? current;
}
