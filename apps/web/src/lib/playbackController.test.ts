import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PlaybackController } from "./playbackController";

// ── AudioContext mock ─────────────────────────────────────────────────────────

function makeSourceMock() {
  const source = {
    buffer: null as AudioBuffer | null,
    connect: vi.fn(),
    start: vi.fn(),
    stop: vi.fn(),
    disconnect: vi.fn(),
    onended: null as (() => void) | null,
  };
  return source;
}

type SourceMock = ReturnType<typeof makeSourceMock>;

let latestSource: SourceMock;
const mockDecodeAudioData = vi.fn();
const mockResume = vi.fn().mockResolvedValue(undefined);

const mockContext = {
  state: "running" as AudioContextState,
  destination: {} as AudioDestinationNode,
  decodeAudioData: mockDecodeAudioData,
  createBufferSource: vi.fn(),
  resume: mockResume,
};

beforeEach(() => {
  latestSource = makeSourceMock();
  mockDecodeAudioData.mockResolvedValue({ duration: 0.5 } as AudioBuffer);
  mockContext.createBufferSource.mockReturnValue(latestSource);
  vi.stubGlobal("AudioContext", vi.fn().mockReturnValue(mockContext));
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ── Helper ────────────────────────────────────────────────────────────────────

function minimalBase64(): string {
  // 4 bytes → valid base64, not a real WAV but decodeAudioData is mocked
  return btoa(String.fromCharCode(0, 0, 0, 0));
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("PlaybackController", () => {
  it("decodes audio data on enqueue", async () => {
    const ctrl = new PlaybackController();
    await ctrl.enqueueWavBase64(minimalBase64());
    expect(mockDecodeAudioData).toHaveBeenCalledOnce();
  });

  it("starts playback after enqueue", async () => {
    const ctrl = new PlaybackController();
    await ctrl.enqueueWavBase64(minimalBase64());
    expect(latestSource.start).toHaveBeenCalledOnce();
  });

  it("connects source to destination before starting", async () => {
    const ctrl = new PlaybackController();
    await ctrl.enqueueWavBase64(minimalBase64());
    expect(latestSource.connect).toHaveBeenCalledWith(mockContext.destination);
  });

  it("invokes onPlaybackStarted callback", async () => {
    const onStarted = vi.fn();
    const ctrl = new PlaybackController();
    await ctrl.enqueueWavBase64(minimalBase64(), onStarted);
    expect(onStarted).toHaveBeenCalledOnce();
  });

  it("stop() calls stop and disconnect on current source", async () => {
    const ctrl = new PlaybackController();
    await ctrl.enqueueWavBase64(minimalBase64());
    ctrl.stop();
    expect(latestSource.stop).toHaveBeenCalled();
    expect(latestSource.disconnect).toHaveBeenCalled();
  });

  it("stop() nullifies onended to prevent spurious callbacks", async () => {
    const ctrl = new PlaybackController();
    await ctrl.enqueueWavBase64(minimalBase64());
    ctrl.stop();
    expect(latestSource.onended).toBeNull();
  });

  it("stop() before any enqueue does not throw", () => {
    const ctrl = new PlaybackController();
    expect(() => ctrl.stop()).not.toThrow();
  });

  it("calls onQueueEmpty when the queue drains naturally", async () => {
    const onQueueEmpty = vi.fn();
    const ctrl = new PlaybackController();
    ctrl.onQueueEmpty = onQueueEmpty;
    await ctrl.enqueueWavBase64(minimalBase64());
    // Simulate natural end of playback by triggering the onended callback
    latestSource.onended?.();
    expect(onQueueEmpty).toHaveBeenCalledOnce();
  });

  it("does not call onQueueEmpty when stop() is called", async () => {
    const onQueueEmpty = vi.fn();
    const ctrl = new PlaybackController();
    ctrl.onQueueEmpty = onQueueEmpty;
    await ctrl.enqueueWavBase64(minimalBase64());
    ctrl.stop();
    expect(onQueueEmpty).not.toHaveBeenCalled();
  });

  it("resumes suspended AudioContext before playback", async () => {
    mockContext.state = "suspended";
    const ctrl = new PlaybackController();
    await ctrl.enqueueWavBase64(minimalBase64());
    expect(mockResume).toHaveBeenCalled();
    mockContext.state = "running";
  });
});
