import { describe, expect, it } from "vitest";
import { transitionSessionState } from "./sessionMachine";

describe("sessionMachine", () => {
  it("moves from idle to listening when a session starts", () => {
    expect(transitionSessionState("idle", "session_started")).toBe("listening");
  });

  it("moves through the speaking path", () => {
    const afterTranscript = transitionSessionState("transcribing", "transcript_finalized");
    const afterTts = transitionSessionState(afterTranscript, "tts_started");
    const afterPlayback = transitionSessionState(afterTts, "playback_started");
    expect(afterPlayback).toBe("speaking");
  });

  it("preserves state for unsupported transitions", () => {
    expect(transitionSessionState("idle", "speech_started")).toBe("idle");
  });
});
