import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  acceptedImageMimeTypes,
  attachmentToDataUrl,
  fileToImageAttachment,
  getImageFileFromClipboard,
} from "./imageAttachments";

// ── Image dimension mock ──────────────────────────────────────────────────────

function stubImageLoad(width: number, height: number) {
  vi.stubGlobal(
    "URL",
    class {
      static createObjectURL = vi.fn().mockReturnValue("blob:mock");
      static revokeObjectURL = vi.fn();
    },
  );

  const MockImage = class {
    naturalWidth = width;
    naturalHeight = height;
    width = width;
    height = height;
    onload: (() => void) | null = null;
    onerror: ((e: unknown) => void) | null = null;
    set src(_url: string) {
      // schedule load on next microtask so Promise chains can wire up first
      queueMicrotask(() => this.onload?.());
    }
  };
  vi.stubGlobal("Image", MockImage);
}

function makeFile(bytes: Uint8Array, name: string, type: string): File {
  const file = new File([bytes as unknown as BlobPart], name, { type });
  // jsdom's File.arrayBuffer may be synchronous; replace with async version
  Object.defineProperty(file, "arrayBuffer", {
    configurable: true,
    value: async () => bytes.buffer.slice(0),
  });
  return file;
}

beforeEach(() => {
  vi.restoreAllMocks();
});

// ── fileToImageAttachment ─────────────────────────────────────────────────────

describe("fileToImageAttachment", () => {
  it("converts a PNG file into a valid ImageAttachment", async () => {
    stubImageLoad(800, 600);
    const file = makeFile(new Uint8Array([137, 80, 78, 71, 0, 1, 2, 3]), "shot.png", "image/png");

    const att = await fileToImageAttachment(file);

    expect(att.mimeType).toBe("image/png");
    expect(att.width).toBe(800);
    expect(att.height).toBe(600);
    expect(att.name).toBe("shot.png");
    expect(att.dataBase64.length).toBeGreaterThan(0);
  });

  it("converts a JPEG file", async () => {
    stubImageLoad(1280, 720);
    const file = makeFile(new Uint8Array([0xff, 0xd8, 0xff]), "photo.jpg", "image/jpeg");

    const att = await fileToImageAttachment(file);
    expect(att.mimeType).toBe("image/jpeg");
  });

  it("converts a WebP file", async () => {
    stubImageLoad(640, 480);
    const file = makeFile(new Uint8Array([82, 73, 70, 70]), "anim.webp", "image/webp");

    const att = await fileToImageAttachment(file);
    expect(att.mimeType).toBe("image/webp");
  });

  it("rejects unsupported MIME type with a descriptive error", async () => {
    const file = makeFile(new Uint8Array([0]), "anim.gif", "image/gif");
    await expect(fileToImageAttachment(file)).rejects.toThrow(/PNG, JPEG, and WebP/);
  });

  it("produces correct base64 encoding", async () => {
    stubImageLoad(1, 1);
    const bytes = new Uint8Array([1, 2, 3, 4]);
    const file = makeFile(bytes, "tiny.png", "image/png");

    const att = await fileToImageAttachment(file);
    expect(att.dataBase64).toBe(btoa(String.fromCharCode(1, 2, 3, 4)));
  });
});

// ── acceptedImageMimeTypes ────────────────────────────────────────────────────

describe("acceptedImageMimeTypes", () => {
  it("includes png, jpeg, webp", () => {
    expect(acceptedImageMimeTypes).toContain("image/png");
    expect(acceptedImageMimeTypes).toContain("image/jpeg");
    expect(acceptedImageMimeTypes).toContain("image/webp");
  });

  it("does not include gif", () => {
    expect(acceptedImageMimeTypes).not.toContain("image/gif");
  });
});

// ── attachmentToDataUrl ───────────────────────────────────────────────────────

describe("attachmentToDataUrl", () => {
  it("returns correct data URL format", () => {
    const url = attachmentToDataUrl({
      mimeType: "image/png",
      dataBase64: "abc123",
      width: 100,
      height: 100,
    });
    expect(url).toBe("data:image/png;base64,abc123");
  });

  it("works for jpeg", () => {
    const url = attachmentToDataUrl({
      mimeType: "image/jpeg",
      dataBase64: "xyz",
      width: 50,
      height: 50,
    });
    expect(url).toBe("data:image/jpeg;base64,xyz");
  });
});

// ── getImageFileFromClipboard ─────────────────────────────────────────────────

describe("getImageFileFromClipboard", () => {
  it("returns a File for an image clipboard item", () => {
    const file = new File([new Uint8Array([1])], "pasted.png", { type: "image/png" });
    const event = {
      clipboardData: {
        items: [{ type: "image/png", getAsFile: () => file }],
      },
    } as unknown as ClipboardEvent;

    expect(getImageFileFromClipboard(event)).toBe(file);
  });

  it("returns null when clipboard has no image items", () => {
    const event = {
      clipboardData: {
        items: [{ type: "text/plain", getAsFile: () => null }],
      },
    } as unknown as ClipboardEvent;

    expect(getImageFileFromClipboard(event)).toBeNull();
  });

  it("returns null when clipboardData is absent", () => {
    const event = { clipboardData: null } as unknown as ClipboardEvent;
    expect(getImageFileFromClipboard(event)).toBeNull();
  });
});
