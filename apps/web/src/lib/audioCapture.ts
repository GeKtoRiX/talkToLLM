type AudioCaptureOptions = {
  onChunk: (chunk: ArrayBuffer) => void;
};

export class AudioCaptureController {
  private stream: MediaStream | null = null;

  private audioContext: AudioContext | null = null;

  private sourceNode: MediaStreamAudioSourceNode | null = null;

  private workletNode: AudioWorkletNode | null = null;

  private sinkNode: GainNode | null = null;

  private isRunning = false;

  async start(options: AudioCaptureOptions): Promise<void> {
    if (this.isRunning) {
      return;
    }

    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });

    this.audioContext = new AudioContext();
    await this.audioContext.audioWorklet.addModule("/audio-processor.js");
    this.sourceNode = this.audioContext.createMediaStreamSource(this.stream);
    this.workletNode = new AudioWorkletNode(this.audioContext, "pcm16-worklet", {
      processorOptions: {
        targetSampleRate: 16000,
        chunkDurationMs: 40,
      },
    });
    this.sinkNode = this.audioContext.createGain();
    this.sinkNode.gain.value = 0;

    this.workletNode.port.onmessage = (event) => {
      options.onChunk(event.data as ArrayBuffer);
    };

    this.sourceNode.connect(this.workletNode);
    this.workletNode.connect(this.sinkNode);
    this.sinkNode.connect(this.audioContext.destination);
    this.isRunning = true;
  }

  stop(): void {
    this.workletNode?.disconnect();
    this.sourceNode?.disconnect();
    this.sinkNode?.disconnect();
    this.stream?.getTracks().forEach((track) => track.stop());
    this.audioContext?.close();
    this.workletNode = null;
    this.sourceNode = null;
    this.sinkNode = null;
    this.stream = null;
    this.audioContext = null;
    this.isRunning = false;
  }
}
