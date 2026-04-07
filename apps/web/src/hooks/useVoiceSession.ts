import { useEffect, useRef, useState } from "react";
import type {
  ClientEnvelope,
  ErrorPayload,
  ImageAttachment,
  ResponseTextPayload,
  ServerEnvelope,
  SpeechStartPayload,
  TextSubmitPayload,
  TranscriptPayload,
  TtsChunkPayload,
} from "@talktollm/contracts";
import { createEnvelope } from "@talktollm/contracts";
import type { SessionState } from "@talktollm/contracts";
import { AudioCaptureController } from "../lib/audioCapture";
import { attachmentToDataUrl, fileToImageAttachment, getImageFileFromClipboard } from "../lib/imageAttachments";
import { PlaybackController } from "../lib/playbackController";
import { transitionSessionState } from "../lib/sessionMachine";

const REALTIME_WS_URL = import.meta.env.VITE_REALTIME_WS_URL ?? "ws://localhost:8000/ws";

export type ConversationMessage = { role: "user" | "assistant"; text: string };

export function useVoiceSession() {
  const [sessionState, setSessionState] = useState<SessionState>("idle");
  const [transcript, setTranscript] = useState("");
  const [assistantText, setAssistantText] = useState("");
  const [conversationHistory, setConversationHistory] = useState<ConversationMessage[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [textQuestion, setTextQuestion] = useState("");
  const [activeScreenshot, setActiveScreenshot] = useState<ImageAttachment | null>(null);

  const websocketRef = useRef<WebSocket | null>(null);
  const audioCaptureRef = useRef(new AudioCaptureController());
  const playbackRef = useRef(new PlaybackController());
  const sequenceRef = useRef(0);
  const sessionIdRef = useRef<string | null>(null);
  const turnIdRef = useRef<string | null>(null);
  const sessionStateRef = useRef<SessionState>("idle");
  const talkHotkeyPressedRef = useRef(false);
  const activeScreenshotRef = useRef<ImageAttachment | null>(null);

  useEffect(() => {
    sessionStateRef.current = sessionState;
  }, [sessionState]);

  useEffect(() => {
    playbackRef.current.onQueueEmpty = () => {
      setSessionState((current) => transitionSessionState(current, "playback_completed"));
    };
  }, []);

  useEffect(() => {
    activeScreenshotRef.current = activeScreenshot;
  }, [activeScreenshot]);

  useEffect(() => {
    function isEditableTarget(target: EventTarget | null): boolean {
      if (!(target instanceof HTMLElement)) {
        return false;
      }

      const tagName = target.tagName.toLowerCase();
      return target.isContentEditable || tagName === "input" || tagName === "textarea" || tagName === "select";
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.repeat || event.key.toLowerCase() !== "q" || event.altKey || event.ctrlKey || event.metaKey) {
        return;
      }

      if (isEditableTarget(event.target)) {
        return;
      }

      if (talkHotkeyPressedRef.current) {
        return;
      }

      talkHotkeyPressedRef.current = true;
      event.preventDefault();
      void startTalking();
    }

    function handlePaste(event: ClipboardEvent) {
      const imageFile = getImageFileFromClipboard(event);
      if (!imageFile) {
        return;
      }

      event.preventDefault();
      void replaceActiveScreenshotFromFile(imageFile);
    }

    function releaseTalkHotkey() {
      talkHotkeyPressedRef.current = false;
      stopTalking();
    }

    function handleKeyUp(event: KeyboardEvent) {
      if (event.key.toLowerCase() !== "q") {
        return;
      }

      if (!talkHotkeyPressedRef.current) {
        return;
      }

      event.preventDefault();
      releaseTalkHotkey();
    }

    function handleWindowBlur() {
      if (!talkHotkeyPressedRef.current) {
        return;
      }

      releaseTalkHotkey();
    }

    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("keyup", handleKeyUp);
    window.addEventListener("paste", handlePaste);
    window.addEventListener("blur", handleWindowBlur);

    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("keyup", handleKeyUp);
      window.removeEventListener("paste", handlePaste);
      window.removeEventListener("blur", handleWindowBlur);
      talkHotkeyPressedRef.current = false;
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
    setConversationHistory([]);

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
        case "transcript.final": {
          const transcriptText = (event.payload as TranscriptPayload).text;
          setTranscript(transcriptText);
          if (event.type === "transcript.final") {
            setConversationHistory((prev) => [...prev, { role: "user", text: transcriptText }]);
            setTranscript("");
            setSessionState((current) => transitionSessionState(current, "transcript_finalized"));
          }
          break;
        }
        case "llm.thinking":
          setSessionState((current) => transitionSessionState(current, "llm_thinking"));
          break;
        case "response.text.delta":
          setAssistantText((current) => current + (event.payload as ResponseTextPayload).text);
          break;
        case "response.text.final": {
          const finalText = (event.payload as ResponseTextPayload).text;
          setConversationHistory((prev) => [...prev, { role: "assistant", text: finalText }]);
          setAssistantText("");
          break;
        }
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
    talkHotkeyPressedRef.current = false;
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

    const currentState = sessionStateRef.current;
    if (currentState === "capturing_speech" || currentState === "transcribing") {
      return;
    }

    // Update ref immediately to block re-entry from duplicate events (e.g. onMouseDown + onTouchStart)
    // before the React re-render syncs sessionStateRef via useEffect.
    sessionStateRef.current = "capturing_speech";

    if (currentState === "speaking") {
      interrupt();
    }

    setAssistantText("");
    setSessionState((current) => transitionSessionState(current, "speech_started"));
    const screenshot = activeScreenshotRef.current;
    const payload: SpeechStartPayload = screenshot ? { attachments: [screenshot] } : {};
    sendControl(createEnvelope("speech.start", payload));

    await audioCaptureRef.current.start({
      onChunk: (chunk) => {
        websocketRef.current?.send(chunk);
      },
    });
  }

  function stopTalking() {
    if (sessionStateRef.current !== "capturing_speech") {
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

  async function replaceActiveScreenshotFromFile(file: Blob & { type: string; name?: string }) {
    try {
      setError(null);
      const attachment = await fileToImageAttachment(file);
      setActiveScreenshot(attachment);
    } catch (attachmentError) {
      setError(attachmentError instanceof Error ? attachmentError.message : "Failed to load the screenshot.");
    }
  }

  function clearActiveScreenshot() {
    setActiveScreenshot(null);
  }

  function submitTextTurn() {
    const text = textQuestion.trim();
    if (!text) {
      return;
    }

    if (!websocketRef.current || websocketRef.current.readyState !== WebSocket.OPEN) {
      return;
    }

    talkHotkeyPressedRef.current = false;
    audioCaptureRef.current.stop();
    if (sessionStateRef.current === "speaking") {
      interrupt();
    }

    setError(null);
    setAssistantText("");
    setTranscript("");
    setConversationHistory((prev) => [...prev, { role: "user", text }]);
    setTextQuestion("");
    setSessionState((current) => transitionSessionState(current, "text_submitted"));

    const payload: TextSubmitPayload = activeScreenshot ? { text, attachments: [activeScreenshot] } : { text };
    sendControl(createEnvelope("text.submit", payload));
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
    conversationHistory,
    error,
    connected,
    textQuestion,
    setTextQuestion,
    activeScreenshot,
    activeScreenshotPreviewUrl: activeScreenshot ? attachmentToDataUrl(activeScreenshot) : null,
    replaceActiveScreenshotFromFile,
    clearActiveScreenshot,
    startSession,
    stopSession,
    startTalking,
    stopTalking,
    submitTextTurn,
    interrupt,
  };
}
