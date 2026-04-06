export class PlaybackController {
  private audioContext: AudioContext | null = null;

  private queue: AudioBuffer[] = [];

  private currentSource: AudioBufferSourceNode | null = null;

  private isPlaying = false;

  async enqueueWavBase64(audioBase64: string, onPlaybackStarted?: () => void): Promise<void> {
    const arrayBuffer = this.base64ToArrayBuffer(audioBase64);
    const context = await this.getContext();
    const decoded = await context.decodeAudioData(arrayBuffer.slice(0));
    this.queue.push(decoded);

    if (!this.isPlaying) {
      this.playNext(onPlaybackStarted);
    }
  }

  stop(): void {
    this.queue = [];
    if (this.currentSource) {
      this.currentSource.onended = null;
      this.currentSource.stop();
      this.currentSource.disconnect();
      this.currentSource = null;
    }
    this.isPlaying = false;
  }

  private async getContext(): Promise<AudioContext> {
    if (!this.audioContext) {
      this.audioContext = new AudioContext();
    }
    if (this.audioContext.state === "suspended") {
      await this.audioContext.resume();
    }
    return this.audioContext;
  }

  private playNext(onPlaybackStarted?: () => void): void {
    if (!this.audioContext) {
      return;
    }

    const nextBuffer = this.queue.shift();
    if (!nextBuffer) {
      this.isPlaying = false;
      return;
    }

    const source = this.audioContext.createBufferSource();
    source.buffer = nextBuffer;
    source.connect(this.audioContext.destination);
    source.onended = () => {
      this.currentSource = null;
      this.playNext(onPlaybackStarted);
    };
    this.currentSource = source;
    this.isPlaying = true;
    source.start();
    onPlaybackStarted?.();
  }

  private base64ToArrayBuffer(base64: string): ArrayBuffer {
    const binary = window.atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }
    return bytes.buffer;
  }
}

