import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./lib/audioCapture", () => ({
  AudioCaptureController: class {
    async start(): Promise<void> {
      return Promise.resolve();
    }

    stop(): void {
      return;
    }
  },
}));

vi.mock("./lib/playbackController", () => ({
  PlaybackController: class {
    async enqueueWavBase64(): Promise<void> {
      return Promise.resolve();
    }

    stop(): void {
      return;
    }
  },
}));

import App from "./App";

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
  onclose: ((event: Event) => void) | null = null;
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
    this.onclose?.(new Event("close"));
  }
}

function createImageFile(name = "shot.png", type = "image/png") {
  const bytes = new Uint8Array([137, 80, 78, 71]);
  const file = new File([bytes], name, { type });
  Object.defineProperty(file, "arrayBuffer", {
    configurable: true,
    value: async () => bytes.buffer,
  });
  return file;
}

function dispatchPasteImage(file: File) {
  const pasteEvent = new Event("paste") as ClipboardEvent;
  Object.defineProperty(pasteEvent, "clipboardData", {
    value: {
      items: [
        {
          type: file.type,
          getAsFile: () => file,
        },
      ],
    },
  });
  window.dispatchEvent(pasteEvent);
}

function getLastSocket(): MockWebSocket {
  const socket = MockWebSocket.instances[MockWebSocket.instances.length - 1];
  if (!socket) {
    throw new Error("WebSocket instance was not created.");
  }
  return socket;
}

function findSentMessage(type: string): Record<string, unknown> {
  const socket = getLastSocket();
  for (const message of socket.sent) {
    if (typeof message !== "string") {
      continue;
    }

    const parsed = JSON.parse(message) as Record<string, unknown>;
    if (parsed.type === type) {
      return parsed;
    }
  }

  throw new Error(`Message '${type}' was not sent.`);
}

describe("App multimodal screenshot flow", () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    vi.stubGlobal("WebSocket", MockWebSocket);
    vi.stubGlobal("Image", class {
      width = 1280;
      height = 720;
      naturalWidth = 1280;
      naturalHeight = 720;
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;

      set src(_value: string) {
        setTimeout(() => {
          this.onload?.();
        }, 0);
      }
    });
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      writable: true,
      value: vi.fn(() => "blob:mock-screenshot"),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      writable: true,
      value: vi.fn(() => {}),
    });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("creates an active preview when an image is pasted", async () => {
    render(<App />);

    dispatchPasteImage(createImageFile());

    await waitFor(() => {
      expect(screen.getByAltText("Active screenshot preview")).toBeInTheDocument();
    });
    expect(screen.getByText("Screenshot active for next turns")).toBeInTheDocument();
  });

  it("uploads and clears the active screenshot", async () => {
    render(<App />);

    const input = screen.getByLabelText("Upload screenshot") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [createImageFile("task.png")] } });

    await waitFor(() => {
      expect(screen.getByAltText("Active screenshot preview")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Clear Screenshot" }));
    expect(screen.queryByAltText("Active screenshot preview")).not.toBeInTheDocument();
  });

  it("keeps text submit disabled until connected and the question is non-empty", async () => {
    render(<App />);

    const sendButton = screen.getByRole("button", { name: "Send Text" });
    const input = screen.getByLabelText("Type a question");
    expect(sendButton).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Start Conversation" }));
    fireEvent.change(input, { target: { value: "Explain the screenshot" } });

    await waitFor(() => {
      expect(sendButton).toBeEnabled();
    });
  });

  it("sends typed multimodal turns with the active screenshot attached", async () => {
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "Start Conversation" }));
    const input = screen.getByLabelText("Upload screenshot") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [createImageFile("worksheet.png")] } });

    await waitFor(() => {
      expect(screen.getByAltText("Active screenshot preview")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText("Type a question"), { target: { value: "Help me solve this." } });
    fireEvent.click(screen.getByRole("button", { name: "Send Text" }));

    await waitFor(() => {
      const payload = findSentMessage("text.submit");
      const payloadBody = payload.payload as { text: string; attachments: Array<{ mimeType: string }> };
      expect(payloadBody.text).toBe("Help me solve this.");
      expect(payloadBody.attachments[0].mimeType).toBe("image/png");
    });
  });

  it("binds Q hold-to-talk to speech.start with the active screenshot", async () => {
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "Start Conversation" }));
    const input = screen.getByLabelText("Upload screenshot") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [createImageFile()] } });

    await waitFor(() => {
      expect(screen.getByAltText("Active screenshot preview")).toBeInTheDocument();
    });

    fireEvent.keyDown(window, { key: "q" });
    fireEvent.keyUp(window, { key: "q" });

    await waitFor(() => {
      const payload = findSentMessage("speech.start");
      const payloadBody = payload.payload as { attachments: Array<{ mimeType: string }> };
      expect(payloadBody.attachments[0].mimeType).toBe("image/png");
    });

    expect(findSentMessage("speech.end").type).toBe("speech.end");
  });
});
