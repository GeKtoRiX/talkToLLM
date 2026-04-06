import { useEffect, useRef, useState } from "react";
import type {
  ClientEnvelope,
  ErrorPayload,
  ResponseTextPayload,
  ServerEnvelope,
  TranscriptPayload,
  TtsChunkPayload,
} from "@talktollm/contracts";
import { createEnvelope } from "@talktollm/contracts";
import type { SessionState } from "@talktollm/contracts";
import { AudioCaptureController } from "../lib/audioCapture";
import { PlaybackController } from "../lib/playbackController";
import { transitionSessionState } from "../lib/sessionMachine";

const REALTIME_WS_URL = import.meta.env.VITE_REALTIME_WS_URL ?? "ws://localhost:8000/ws";

export function useVoiceSession() {
  const [sessionState, setSessionState] = useState<SessionState>("idle");
  const [transcript, setTranscript] = useState("");
  const [assistantText, setAssistantText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);

  const websocketRef = useRef<WebSocket | null>(null);
  const audioCaptureRef = useRef(new AudioCaptureController());
  const playbackRef = useRef(new PlaybackController());
  const sequenceRef = useRef(0);
  const sessionIdRef = useRef<string | null>(null);
  const turnIdRef = useRef<string | null>(null);

  useEffect(() => {
    return () => {
      websocketRef.current?.close();
      audioCaptureRef.current.stop();
      playbackRef.current.stop();
    };
  }, []);

  async function startSession() {
    if (websocketRef.current && websocketRef.current.readyState === WebSocket.OPEN) {
      return;
    }

    setError(null);
    setTranscript("");
    setAssistantText("");

    const socket = new WebSocket(REALTIME_WS_URL);
    socket.binaryType = "arraybuffer";

    socket.onopen = () => {
      websocketRef.current = socket;
      setConnected(true);
      setSessionState((current) => transitionSessionState(current, "session_started"));
      sendControl(
        createEnvelope("session.start", {
          sampleRate: 16000,
          format: "pcm_s16le",
          language: "en",
        }),
      );
    };

    socket.onmessage = async (message) => {
      const event = JSON.parse(message.data as string) as ServerEnvelope;
      sessionIdRef.current = event.sessionId;
      turnIdRef.current = event.turnId;

      switch (event.type) {
        case "session.started":
          setConnected(true);
          break;
        case "transcript.partial":
        case "transcript.final":
          setTranscript((event.payload as TranscriptPayload).text);
          if (event.type === "transcript.final") {
            setSessionState((current) => transitionSessionState(current, "transcript_finalized"));
          }
          break;
        case "llm.thinking":
          setSessionState((current) => transitionSessionState(current, "llm_thinking"));
          break;
        case "response.text.delta":
          setAssistantText((current) => current + (event.payload as ResponseTextPayload).text);
          break;
        case "response.text.final":
          setAssistantText((event.payload as ResponseTextPayload).text);
          break;
        case "tts.chunk":
          setSessionState((current) => transitionSessionState(current, "tts_started"));
          await playbackRef.current.enqueueWavBase64((event.payload as TtsChunkPayload).audioBase64, () => {
            setSessionState((current) => transitionSessionState(current, "playback_started"));
          });
          break;
        case "playback.stop":
          playbackRef.current.stop();
          setSessionState((current) => transitionSessionState(current, "playback_interrupted"));
          break;
        case "error":
          setError((event.payload as ErrorPayload).message);
          setSessionState((current) => transitionSessionState(current, "failed"));
          break;
        default:
          break;
      }
    };

    socket.onerror = () => {
      setError("Realtime connection failed.");
      setSessionState((current) => transitionSessionState(current, "failed"));
    };

    socket.onclose = () => {
      websocketRef.current = null;
      setConnected(false);
      setSessionState("idle");
    };
  }

  function stopSession() {
    sendControl(createEnvelope("session.stop", {}));
    audioCaptureRef.current.stop();
    playbackRef.current.stop();
    websocketRef.current?.close();
    websocketRef.current = null;
    setConnected(false);
    setSessionState("idle");
  }

  async function startTalking() {
    if (!websocketRef.current || websocketRef.current.readyState !== WebSocket.OPEN) {
      return;
    }

    if (sessionState === "speaking") {
      interrupt();
    }

    setAssistantText("");
    setSessionState((current) => transitionSessionState(current, "speech_started"));
    sendControl(createEnvelope("speech.start", {}));

    await audioCaptureRef.current.start({
      onChunk: (chunk) => {
        websocketRef.current?.send(chunk);
      },
    });
  }

  function stopTalking() {
    if (sessionState !== "capturing_speech") {
      return;
    }

    audioCaptureRef.current.stop();
    setSessionState((current) => transitionSessionState(current, "speech_ended"));
    sendControl(createEnvelope("speech.end", {}));
  }

  function interrupt() {
    playbackRef.current.stop();
    setSessionState((current) => transitionSessionState(current, "playback_interrupted"));
    sendControl(createEnvelope("playback.interrupt", {}));
  }

  function sendControl(event: ClientEnvelope) {
    if (!websocketRef.current || websocketRef.current.readyState !== WebSocket.OPEN) {
      return;
    }

    sequenceRef.current += 1;
    websocketRef.current.send(
      JSON.stringify({
        ...event,
        sessionId: sessionIdRef.current,
        turnId: turnIdRef.current,
        seq: sequenceRef.current,
        timestamp: new Date().toISOString(),
      }),
    );
  }

  return {
    sessionState,
    transcript,
    assistantText,
    error,
    connected,
    startSession,
    stopSession,
    startTalking,
    stopTalking,
    interrupt,
  };
}

