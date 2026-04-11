/**
 * E2E tests for screenshot insertion and LLM conversation features.
 *
 * Covers:
 *  - Screenshot: paste, upload, metadata display, replace, clear, status pill,
 *    non-image paste ignored, Hide/Show controls toggle.
 *  - LLM conversation: session lifecycle (start/stop), session.start message,
 *    text turn (no screenshot, with screenshot), full turn round-trip (transcript
 *    partial/final + response delta/final), streaming text display, conversation
 *    history accumulation, server error display, Interrupt Playback, Q hold-to-talk
 *    with/without screenshot, Q hotkey blocked inside input fields,
 *    window.blur releases talk hotkey, state transitions in StatusPill.
 *
 * Mock strategy:
 *  - AudioCaptureController + PlaybackController mocked at module level.
 *  - WebSocket replaced with MockWebSocket per test.
 *  - Image constructor stubbed so fileToImageAttachment resolves synchronously.
 *  - URL.createObjectURL / revokeObjectURL stubbed.
 *  - Server events injected via socket.onmessage() helpers.
 */

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Module-level mocks must come before App import.
vi.mock("../lib/audioCapture", () => ({
  AudioCaptureController: class {
    async start(): Promise<void> { return Promise.resolve(); }
    stop(): void { return; }
  },
}));

vi.mock("../lib/playbackController", () => ({
  PlaybackController: class {
    onQueueEmpty: (() => void) | null = null;
    async enqueueWavBase64(): Promise<void> { return Promise.resolve(); }
    stop(): void { return; }
  },
}));

import App from "../App";

// ============================================================
// MockWebSocket
// ============================================================

class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static instances: MockWebSocket[] = [];

  readonly sent: Array<string | ArrayBuffer> = [];
  readonly url: string;
  binaryType = "blob";
  readyState = MockWebSocket.CONNECTING;
  onopen: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
    setTimeout(() => {
      this.readyState = MockWebSocket.OPEN;
      this.onopen?.(new Event("open"));
    }, 0);
  }

  send(payload: string | ArrayBuffer): void {
    this.sent.push(payload);
  }

  close(): void {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.(new CloseEvent("close"));
  }
}

// ============================================================
// Helpers
// ============================================================

function getLastSocket(): MockWebSocket {
  const socket = MockWebSocket.instances[MockWebSocket.instances.length - 1];
  if (!socket) throw new Error("No WebSocket instance created.");
  return socket;
}

function findSentMessage(type: string): Record<string, unknown> {
  const socket = getLastSocket();
  for (const msg of socket.sent) {
    if (typeof msg !== "string") continue;
    const parsed = JSON.parse(msg) as Record<string, unknown>;
    if (parsed.type === type) return parsed;
  }
  throw new Error(`Message '${type}' was not sent. Sent: ${socket.sent.join(", ")}`);
}

/** Inject a server-to-client event on the active socket. */
function serverSend(type: string, payload: unknown = {}): void {
  const socket = getLastSocket();
  socket.onmessage?.(
    new MessageEvent("message", {
      data: JSON.stringify({
        type, payload,
        sessionId: "sess-1", turnId: "turn-1",
        seq: 1, timestamp: new Date().toISOString(),
      }),
    }),
  );
}

/** Connect the session and wait for connected state. */
async function startSession(): Promise<void> {
  fireEvent.click(screen.getByRole("button", { name: "Start Conversation" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Stop Session" })).toBeInTheDocument(),
  );
}

function createImageFile(name = "shot.png", type = "image/png"): File {
  const bytes = new Uint8Array([137, 80, 78, 71]);
  const file = new File([bytes], name, { type });
  Object.defineProperty(file, "arrayBuffer", {
    configurable: true,
    value: async () => bytes.buffer,
  });
  return file;
}

function dispatchPasteImage(file: File): void {
  const pasteEvent = new Event("paste") as ClipboardEvent;
  Object.defineProperty(pasteEvent, "clipboardData", {
    value: {
      items: [{ type: file.type, getAsFile: () => file }],
    },
  });
  window.dispatchEvent(pasteEvent);
}

function dispatchNonImagePaste(): void {
  const pasteEvent = new Event("paste") as ClipboardEvent;
  Object.defineProperty(pasteEvent, "clipboardData", {
    value: { items: [{ type: "text/plain", getAsFile: () => null }] },
  });
  window.dispatchEvent(pasteEvent);
}

// ============================================================
// Setup / teardown
// ============================================================

beforeEach(() => {
  MockWebSocket.instances = [];
  vi.stubGlobal("WebSocket", MockWebSocket);

  vi.stubGlobal(
    "Image",
    class {
      width = 1280; height = 720;
      naturalWidth = 1280; naturalHeight = 720;
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      set src(_: string) { setTimeout(() => this.onload?.(), 0); }
    },
  );

  Object.defineProperty(URL, "createObjectURL", {
    configurable: true, writable: true,
    value: vi.fn(() => "blob:mock-screenshot"),
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    configurable: true, writable: true,
    value: vi.fn(),
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

// ============================================================
// 1. Screenshot — paste
// ============================================================

describe("Screenshot — paste", () => {
  it("shows preview after image paste", async () => {
    render(<App />);
    dispatchPasteImage(createImageFile());
    await waitFor(() =>
      expect(screen.getByAltText("Active screenshot preview")).toBeInTheDocument(),
    );
  });

  it("shows 'Screenshot active for next turns' status pill after paste", async () => {
    render(<App />);
    dispatchPasteImage(createImageFile());
    await waitFor(() =>
      expect(screen.getByText("Screenshot active for next turns")).toBeInTheDocument(),
    );
  });

  it("shows image filename in metadata panel", async () => {
    render(<App />);
    dispatchPasteImage(createImageFile("worksheet.png"));
    await waitFor(() => screen.getByAltText("Active screenshot preview"));
    // Pasted images without explicit File.name appear as "clipboard-screenshot"
    // For a named File the name should appear.
    expect(screen.getByText("worksheet.png")).toBeInTheDocument();
  });

  it("shows dimensions in metadata panel", async () => {
    render(<App />);
    dispatchPasteImage(createImageFile());
    await waitFor(() => screen.getByAltText("Active screenshot preview"));
    expect(screen.getByText("1280 x 720 px")).toBeInTheDocument();
  });

  it("shows mimeType in metadata panel", async () => {
    render(<App />);
    dispatchPasteImage(createImageFile("shot.png", "image/png"));
    await waitFor(() => screen.getByAltText("Active screenshot preview"));
    expect(screen.getByText("image/png")).toBeInTheDocument();
  });

  it("ignores non-image paste events", async () => {
    render(<App />);
    dispatchNonImagePaste();
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByAltText("Active screenshot preview")).toBeNull();
  });

  it("replaces previous screenshot on second paste", async () => {
    render(<App />);
    dispatchPasteImage(createImageFile("first.png"));
    await waitFor(() => screen.getByAltText("Active screenshot preview"));
    expect(screen.getByText("first.png")).toBeInTheDocument();

    dispatchPasteImage(createImageFile("second.png"));
    await waitFor(() => screen.getByText("second.png"));
    // Still only one preview
    expect(screen.getAllByAltText("Active screenshot preview")).toHaveLength(1);
  });
});

// ============================================================
// 2. Screenshot — upload via file input
// ============================================================

describe("Screenshot — file upload", () => {
  it("shows preview after file upload", async () => {
    render(<App />);
    const input = screen.getByLabelText("Upload screenshot") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [createImageFile("task.png")] } });
    await waitFor(() =>
      expect(screen.getByAltText("Active screenshot preview")).toBeInTheDocument(),
    );
  });

  it("shows Replace Screenshot button after upload", async () => {
    render(<App />);
    const input = screen.getByLabelText("Upload screenshot") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [createImageFile()] } });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Replace Screenshot" })).toBeInTheDocument(),
    );
  });

  it("clears screenshot when Clear Screenshot is clicked", async () => {
    render(<App />);
    const input = screen.getByLabelText("Upload screenshot") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [createImageFile()] } });
    await waitFor(() => screen.getByAltText("Active screenshot preview"));

    fireEvent.click(screen.getByRole("button", { name: "Clear Screenshot" }));
    expect(screen.queryByAltText("Active screenshot preview")).toBeNull();
    expect(screen.queryByText("Screenshot active for next turns")).toBeNull();
  });

  it("shows Upload Screenshot button when no screenshot is active", () => {
    render(<App />);
    expect(screen.getByRole("button", { name: "Upload Screenshot" })).toBeInTheDocument();
  });
});

// ============================================================
// 3. Hide/Show controls toggle
// ============================================================

describe("App — Hide/Show controls toggle", () => {
  it("hides controls section when Hide controls is clicked", async () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Hide controls" }));
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Start Conversation" })).toBeNull(),
    );
  });

  it("shows controls again when Show controls is clicked", async () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Hide controls" }));
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Start Conversation" })).toBeNull(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Show controls" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Start Conversation" })).toBeInTheDocument(),
    );
  });
});

// ============================================================
// 4. Session lifecycle
// ============================================================

describe("LLM — session lifecycle", () => {
  it("shows Start Conversation button initially", () => {
    render(<App />);
    expect(screen.getByRole("button", { name: "Start Conversation" })).toBeInTheDocument();
  });

  it("shows Stop Session button after connecting", async () => {
    render(<App />);
    await startSession();
    expect(screen.getByRole("button", { name: "Stop Session" })).toBeInTheDocument();
  });

  it("shows Realtime connected status pill after connect", async () => {
    render(<App />);
    await startSession();
    expect(screen.getByText("Realtime connected")).toBeInTheDocument();
  });

  it("sends session.start event with audio config on connect", async () => {
    render(<App />);
    await startSession();
    const msg = findSentMessage("session.start");
    const payload = msg.payload as { sampleRate: number; format: string; language: string };
    expect(payload.sampleRate).toBe(16000);
    expect(payload.format).toBe("pcm_s16le");
    expect(payload.language).toBe("en");
  });

  it("returns to Start Conversation after Stop Session", async () => {
    render(<App />);
    await startSession();
    fireEvent.click(screen.getByRole("button", { name: "Stop Session" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Start Conversation" })).toBeInTheDocument(),
    );
  });

  it("sends session.stop message on Stop Session", async () => {
    render(<App />);
    await startSession();
    fireEvent.click(screen.getByRole("button", { name: "Stop Session" }));
    expect(findSentMessage("session.stop").type).toBe("session.stop");
  });

  it("shows Disconnected pill when not connected", () => {
    render(<App />);
    expect(screen.getByText("Disconnected")).toBeInTheDocument();
  });

  it("shows error in UI when server sends error event", async () => {
    render(<App />);
    await startSession();
    act(() => {
      serverSend("error", { code: "TURN_FAILED", message: "STT timed out" });
    });
    await waitFor(() =>
      expect(screen.getByText("STT timed out")).toBeInTheDocument(),
    );
  });

  it("shows session state in StatusPill", async () => {
    render(<App />);
    expect(screen.getByText(/State: idle/i)).toBeInTheDocument();
    await startSession();
    expect(screen.getByText(/State: listening/i)).toBeInTheDocument();
  });
});

// ============================================================
// 5. Text turn — submission
// ============================================================

describe("LLM — text turn submission", () => {
  it("Send Text button disabled when not connected", () => {
    render(<App />);
    expect(screen.getByRole("button", { name: "Send Text" })).toBeDisabled();
  });

  it("Send Text button disabled when input is empty even when connected", async () => {
    render(<App />);
    await startSession();
    expect(screen.getByRole("button", { name: "Send Text" })).toBeDisabled();
  });

  it("Send Text enabled after connecting and typing", async () => {
    render(<App />);
    await startSession();
    fireEvent.change(screen.getByLabelText("Type a question"), { target: { value: "Hello!" } });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Send Text" })).toBeEnabled(),
    );
  });

  it("sends text.submit message with typed text", async () => {
    render(<App />);
    await startSession();
    fireEvent.change(screen.getByLabelText("Type a question"), { target: { value: "Explain this." } });
    fireEvent.click(screen.getByRole("button", { name: "Send Text" }));
    const msg = findSentMessage("text.submit");
    expect((msg.payload as { text: string }).text).toBe("Explain this.");
  });

  it("clears the text input after submission", async () => {
    render(<App />);
    await startSession();
    const input = screen.getByLabelText("Type a question") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "Hello!" } });
    fireEvent.click(screen.getByRole("button", { name: "Send Text" }));
    await waitFor(() => expect(input.value).toBe(""));
  });

  it("sends text.submit without attachments when no screenshot is active", async () => {
    render(<App />);
    await startSession();
    fireEvent.change(screen.getByLabelText("Type a question"), { target: { value: "Hi" } });
    fireEvent.click(screen.getByRole("button", { name: "Send Text" }));
    const msg = findSentMessage("text.submit");
    const payload = msg.payload as { text: string; attachments?: unknown[] };
    expect(payload.attachments).toBeUndefined();
  });

  it("includes screenshot attachment in text.submit when screenshot is active", async () => {
    render(<App />);
    const fileInput = screen.getByLabelText("Upload screenshot") as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [createImageFile("chart.png")] } });
    await waitFor(() => screen.getByAltText("Active screenshot preview"));

    await startSession();
    fireEvent.change(screen.getByLabelText("Type a question"), { target: { value: "Explain chart" } });
    fireEvent.click(screen.getByRole("button", { name: "Send Text" }));

    await waitFor(() => {
      const msg = findSentMessage("text.submit");
      const payload = msg.payload as { attachments: Array<{ mimeType: string }> };
      expect(payload.attachments?.[0].mimeType).toBe("image/png");
    });
  });

  it("shows submitted text as streaming user message before transcript arrives", async () => {
    render(<App />);
    await startSession();
    fireEvent.change(screen.getByLabelText("Type a question"), { target: { value: "What is this?" } });
    fireEvent.click(screen.getByRole("button", { name: "Send Text" }));
    await waitFor(() =>
      expect(screen.getByText("What is this?")).toBeInTheDocument(),
    );
  });
});

// ============================================================
// 6. Full conversation round-trip (server → UI)
// ============================================================

describe("LLM — full conversation round-trip", () => {
  it("shows partial transcript as streaming message", async () => {
    render(<App />);
    await startSession();
    act(() => {
      serverSend("transcript.partial", { text: "Hello wor…", isFinal: false });
    });
    await waitFor(() =>
      expect(screen.getByText("Hello wor…")).toBeInTheDocument(),
    );
  });

  it("moves transcript to conversation history on transcript.final", async () => {
    render(<App />);
    await startSession();
    act(() => {
      serverSend("transcript.final", { text: "Hello world", isFinal: true });
    });
    await waitFor(() => {
      const msgs = screen.getAllByText("Hello world");
      expect(msgs.length).toBeGreaterThan(0);
    });
    // Label "You" should appear
    expect(screen.getByText("You")).toBeInTheDocument();
  });

  it("accumulates response.text.delta into streaming assistant text", async () => {
    render(<App />);
    await startSession();
    act(() => {
      serverSend("response.text.delta", { text: "Sure, " });
      serverSend("response.text.delta", { text: "here you go!" });
    });
    await waitFor(() =>
      expect(screen.getByText("Sure, here you go!")).toBeInTheDocument(),
    );
  });

  it("moves streaming text to history on response.text.final", async () => {
    render(<App />);
    await startSession();
    act(() => {
      serverSend("response.text.delta", { text: "The answer is 42." });
      serverSend("response.text.final", { text: "The answer is 42." });
    });
    await waitFor(() =>
      expect(screen.getByText("The answer is 42.")).toBeInTheDocument(),
    );
    expect(screen.getByText("Assistant")).toBeInTheDocument();
  });

  it("accumulates multiple turns in conversation history", async () => {
    render(<App />);
    await startSession();

    act(() => {
      serverSend("transcript.final", { text: "First question", isFinal: true });
      serverSend("response.text.final", { text: "First answer" });
      serverSend("transcript.final", { text: "Second question", isFinal: true });
      serverSend("response.text.final", { text: "Second answer" });
    });

    await waitFor(() => {
      expect(screen.getByText("First question")).toBeInTheDocument();
      expect(screen.getByText("First answer")).toBeInTheDocument();
      expect(screen.getByText("Second question")).toBeInTheDocument();
      expect(screen.getByText("Second answer")).toBeInTheDocument();
    });
  });

  it("shows empty conversation placeholder before any messages", async () => {
    render(<App />);
    expect(screen.getByText("Your conversation will appear here.")).toBeInTheDocument();
  });
});

// ============================================================
// 7. Interrupt Playback
// ============================================================

describe("LLM — Interrupt Playback", () => {
  it("Interrupt Playback button is present after connecting", async () => {
    render(<App />);
    await startSession();
    expect(screen.getByRole("button", { name: "Interrupt Playback" })).toBeInTheDocument();
  });

  it("sends playback.interrupt on button click", async () => {
    render(<App />);
    await startSession();
    fireEvent.click(screen.getByRole("button", { name: "Interrupt Playback" }));
    expect(findSentMessage("playback.interrupt").type).toBe("playback.interrupt");
  });
});

// ============================================================
// 8. Hold-to-talk (Q key)
// ============================================================

describe("LLM — Hold-to-talk (Q key)", () => {
  it("Hold to Talk button visible after connecting", async () => {
    render(<App />);
    await startSession();
    expect(screen.getByRole("button", { name: /hold to talk/i })).toBeInTheDocument();
  });

  it("sends speech.start on Q keydown after connecting", async () => {
    render(<App />);
    await startSession();
    fireEvent.keyDown(window, { key: "q" });
    await waitFor(() => expect(findSentMessage("speech.start").type).toBe("speech.start"));
  });

  it("sends speech.end on Q keyup", async () => {
    render(<App />);
    await startSession();
    fireEvent.keyDown(window, { key: "q" });
    fireEvent.keyUp(window, { key: "q" });
    await waitFor(() => expect(findSentMessage("speech.end").type).toBe("speech.end"));
  });

  it("includes screenshot attachment in speech.start when screenshot is active", async () => {
    render(<App />);
    const fileInput = screen.getByLabelText("Upload screenshot") as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [createImageFile()] } });
    await waitFor(() => screen.getByAltText("Active screenshot preview"));

    await startSession();
    fireEvent.keyDown(window, { key: "q" });

    await waitFor(() => {
      const msg = findSentMessage("speech.start");
      const payload = msg.payload as { attachments?: Array<{ mimeType: string }> };
      expect(payload.attachments?.[0].mimeType).toBe("image/png");
    });
  });

  it("speech.start has no attachments when no screenshot is active", async () => {
    render(<App />);
    await startSession();
    fireEvent.keyDown(window, { key: "q" });
    await waitFor(() => {
      const msg = findSentMessage("speech.start");
      const payload = msg.payload as { attachments?: unknown[] };
      expect(payload.attachments).toBeUndefined();
    });
  });

  it("Q key ignored when focus is inside a text input", async () => {
    render(<App />);
    await startSession();
    const textInput = screen.getByLabelText("Type a question");
    fireEvent.keyDown(textInput, { key: "q", target: textInput });
    // speech.start should NOT be sent
    await new Promise((r) => setTimeout(r, 50));
    expect(() => findSentMessage("speech.start")).toThrow();
  });

  it("does not send Q duplicate on key repeat", async () => {
    render(<App />);
    await startSession();
    fireEvent.keyDown(window, { key: "q" });
    fireEvent.keyDown(window, { key: "q", repeat: true });
    fireEvent.keyDown(window, { key: "q", repeat: true });
    await waitFor(() => findSentMessage("speech.start"));
    const socket = getLastSocket();
    const speechStarts = socket.sent.filter(
      (m) => typeof m === "string" && (JSON.parse(m) as { type: string }).type === "speech.start",
    );
    expect(speechStarts).toHaveLength(1);
  });

  it("window.blur releases talk hotkey and sends speech.end", async () => {
    render(<App />);
    await startSession();
    fireEvent.keyDown(window, { key: "q" });
    await waitFor(() => findSentMessage("speech.start"));
    fireEvent(window, new Event("blur"));
    await waitFor(() => findSentMessage("speech.end"));
  });

  it("Hold to Talk button shows Recording… while Q is held", async () => {
    render(<App />);
    await startSession();
    fireEvent.keyDown(window, { key: "q" });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /recording/i })).toBeInTheDocument(),
    );
    fireEvent.keyUp(window, { key: "q" });
  });
});
