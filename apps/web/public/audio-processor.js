class Pcm16WorkletProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.targetSampleRate = options.processorOptions?.targetSampleRate ?? 16000;
    this.sourceSampleRate = sampleRate;
    this.chunkDurationMs = options.processorOptions?.chunkDurationMs ?? 40;
    this.targetChunkSamples = Math.floor((this.targetSampleRate * this.chunkDurationMs) / 1000);
    this.buffer = [];
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0]) {
      return true;
    }

    const channel = input[0];
    const monoSamples = Array.from(channel);
    const resampled = this.resample(monoSamples, this.sourceSampleRate, this.targetSampleRate);

    for (const sample of resampled) {
      this.buffer.push(sample);
      if (this.buffer.length >= this.targetChunkSamples) {
        const chunk = this.buffer.splice(0, this.targetChunkSamples);
        const pcm16 = new Int16Array(chunk.length);
        for (let i = 0; i < chunk.length; i += 1) {
          const clamped = Math.max(-1, Math.min(1, chunk[i]));
          pcm16[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
        }

        this.port.postMessage(pcm16.buffer, [pcm16.buffer]);
      }
    }

    return true;
  }

  resample(samples, inputRate, outputRate) {
    if (inputRate === outputRate) {
      return samples;
    }

    const ratio = inputRate / outputRate;
    const outputLength = Math.floor(samples.length / ratio);
    const output = new Array(outputLength);

    for (let index = 0; index < outputLength; index += 1) {
      const sourceIndex = index * ratio;
      const before = Math.floor(sourceIndex);
      const after = Math.min(before + 1, samples.length - 1);
      const weight = sourceIndex - before;
      output[index] = samples[before] * (1 - weight) + samples[after] * weight;
    }

    return output;
  }
}

registerProcessor("pcm16-worklet", Pcm16WorkletProcessor);

