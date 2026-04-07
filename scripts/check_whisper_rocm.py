from __future__ import annotations

import argparse
import asyncio
import io

import numpy as np
import soundfile as sf
import torch


def build_settings():
    from app.core.config import AppSettings

    return AppSettings(
        stt_provider="whisper_rocm",
        stt_model_root="models/whisper",
        stt_model_size="base.en",
        stt_device="auto",
        stt_local_files_only=True,
        stt_allow_cpu_fallback=False,
        kokoro_model_root="models/kokoro",
        kokoro_local_files_only=True,
        kokoro_device="cpu",
    )


def print_torch_diagnostics() -> None:
    print(f"torch_version={torch.__version__}")
    print(f"torch_cuda_version={torch.version.cuda}")
    print(f"torch_hip_version={torch.version.hip}")
    print(f"torch_cuda_available={torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"torch_device_count={torch.cuda.device_count()}")
        print(f"torch_device_0={torch.cuda.get_device_name(0)}")


async def synthesize_test_pcm(text: str) -> bytes:
    from app.providers.tts import KokoroTTSProvider

    settings = build_settings()
    provider = KokoroTTSProvider(settings)

    async def text_stream():
        yield (0, text)

    chunks = []
    async for chunk in provider.stream_synthesize(text_stream(), voice="default", format="wav", job_id="rocm-check"):
        chunks.append(chunk.audio_bytes)

    wav_bytes = b"".join(chunks)
    audio, sample_rate = sf.read(io.BytesIO(wav_bytes), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    target_rate = 16000
    if sample_rate != target_rate:
        duration = len(audio) / sample_rate
        old_times = np.linspace(0.0, duration, num=len(audio), endpoint=False)
        new_length = int(duration * target_rate)
        new_times = np.linspace(0.0, duration, num=new_length, endpoint=False)
        audio = np.interp(new_times, old_times, audio).astype(np.float32)

    pcm16 = np.clip(audio, -1.0, 1.0)
    return (pcm16 * 32767.0).astype(np.int16).tobytes()


async def transcribe_pcm(pcm16: bytes) -> str:
    from app.providers.stt import WhisperRocmSTTProvider

    settings = build_settings()
    provider = WhisperRocmSTTProvider(settings)
    await provider.start_session({"sample_rate": 16000, "language": "en"})
    await provider.append_audio(pcm16)
    result = await provider.finalize_utterance()
    return result.text


async def main() -> None:
    parser = argparse.ArgumentParser(description="Check Whisper ROCm runtime and run a short STT smoke test.")
    parser.add_argument(
        "--text",
        default="Hello from the ROCm whisper test. This is a short English sentence.",
        help="Text that Kokoro will synthesize on CPU before Whisper transcribes it on ROCm.",
    )
    args = parser.parse_args()

    print_torch_diagnostics()
    pcm16 = await synthesize_test_pcm(args.text)
    transcript = await transcribe_pcm(pcm16)
    print(f"transcript={transcript}")


if __name__ == "__main__":
    asyncio.run(main())
