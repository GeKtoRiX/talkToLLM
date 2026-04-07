from __future__ import annotations

import asyncio
import io
import logging
import math
import threading
import wave
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from app.core.config import AppSettings
from app.providers.base import TTSProvider, TtsChunk

logger = logging.getLogger(__name__)


def build_tone_wav(duration_seconds: float, sample_rate: int = 16000, frequency: float = 440.0) -> bytes:
    frame_count = int(duration_seconds * sample_rate)
    amplitude = 18000
    buffer = io.BytesIO()

    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        frames = bytearray()
        for index in range(frame_count):
            value = int(amplitude * math.sin(2 * math.pi * frequency * (index / sample_rate)))
            frames.extend(value.to_bytes(2, byteorder="little", signed=True))
        wav_file.writeframes(bytes(frames))

    return buffer.getvalue()


class MockKokoroProvider(TTSProvider):
    async def stream_synthesize(
        self,
        text_stream: AsyncIterator[tuple[int, str]],
        voice: str,
        format: str,
        job_id: str | None = None,
    ) -> AsyncIterator[TtsChunk]:
        async for chunk_index, text in text_stream:
            await asyncio.sleep(0.03)
            duration_seconds = min(max(len(text) / 35, 0.35), 1.8)
            frequency = 380 + (chunk_index * 30)
            audio_bytes = build_tone_wav(duration_seconds=duration_seconds, frequency=frequency)
            yield TtsChunk(audio_bytes=audio_bytes, mime_type="audio/wav", chunk_index=chunk_index, text=text)

    async def cancel(self, job_id: str) -> None:
        return None


class KokoroTTSProvider(TTSProvider):
    _pipeline_cache: dict[tuple[str, str, str, str], object] = {}

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self._cancellations: dict[str, threading.Event] = {}
        self._device_logged = False

    async def stream_synthesize(
        self,
        text_stream: AsyncIterator[tuple[int, str]],
        voice: str,
        format: str,
        job_id: str | None = None,
    ) -> AsyncIterator[TtsChunk]:
        effective_job_id = job_id or "default"
        cancellation = threading.Event()
        self._cancellations[effective_job_id] = cancellation

        try:
            async for chunk_index, text in text_stream:
                if cancellation.is_set():
                    break
                audio_bytes = await asyncio.to_thread(self._synthesize_sentence, text, voice, cancellation)
                if cancellation.is_set() or not audio_bytes:
                    break
                yield TtsChunk(
                    audio_bytes=audio_bytes,
                    mime_type="audio/wav",
                    chunk_index=chunk_index,
                    text=text,
                )
        finally:
            self._cancellations.pop(effective_job_id, None)

    async def cancel(self, job_id: str) -> None:
        cancellation = self._cancellations.get(job_id)
        if cancellation is not None:
            cancellation.set()

    def _synthesize_sentence(self, text: str, voice: str, cancellation: threading.Event) -> bytes:
        try:
            import numpy as np
            import soundfile as sf
            from huggingface_hub import hf_hub_download
            from kokoro import KPipeline
            from kokoro.model import KModel
        except ImportError as error:
            raise RuntimeError(
                "kokoro, soundfile, numpy, and huggingface_hub are required for local Kokoro TTS."
            ) from error

        model_root = self.settings.resolve_path(self.settings.kokoro_model_root)
        model_root.mkdir(parents=True, exist_ok=True)
        selected_voice = voice if voice != "default" else self.settings.kokoro_voice
        voice_name = Path(selected_voice).stem if selected_voice.endswith(".pt") else selected_voice
        device = self._resolve_device()
        cache_key = (self.settings.kokoro_lang_code, self.settings.kokoro_repo_id, voice_name, device)

        pipeline = self._pipeline_cache.get(cache_key)
        voice_path = model_root / "voices" / f"{voice_name}.pt"
        if pipeline is None:
            config_path = hf_hub_download(
                repo_id=self.settings.kokoro_repo_id,
                filename="config.json",
                local_dir=model_root,
                local_files_only=self.settings.kokoro_local_files_only,
            )
            model_path = hf_hub_download(
                repo_id=self.settings.kokoro_repo_id,
                filename="kokoro-v1_0.pth",
                local_dir=model_root,
                local_files_only=self.settings.kokoro_local_files_only,
            )
            resolved_voice_path = hf_hub_download(
                repo_id=self.settings.kokoro_repo_id,
                filename=f"voices/{voice_name}.pt",
                local_dir=model_root,
                local_files_only=self.settings.kokoro_local_files_only,
            )
            model = KModel(
                repo_id=self.settings.kokoro_repo_id,
                config=config_path,
                model=model_path,
            ).to(device).eval()
            pipeline = KPipeline(
                lang_code=self.settings.kokoro_lang_code,
                repo_id=self.settings.kokoro_repo_id,
                model=model,
                device=device,
            )
            self._pipeline_cache[cache_key] = pipeline
            voice_path = Path(resolved_voice_path)
            logger.info(
                "initialized kokoro assets",
                extra={
                    "event": "tts.model.initialized",
                    "provider": "kokoro",
                    "kokoro_device": device,
                    "kokoro_repo_id": self.settings.kokoro_repo_id,
                    "kokoro_model_root": str(model_root),
                    "kokoro_voice": voice_name,
                    "kokoro_voice_path": str(voice_path),
                },
            )

        generator = pipeline(
            text,
            voice=str(voice_path),
            speed=self.settings.kokoro_speed,
            split_pattern=r"\n+",
        )

        combined_audio: list[Any] = []
        sample_rate = 24000
        for generated_speech, _phonemes, audio in generator:
            if cancellation.is_set():
                return b""
            if generated_speech:
                combined_audio.append(audio)

        if not combined_audio:
            return b""

        audio_array = np.concatenate(combined_audio)
        buffer = io.BytesIO()
        sf.write(buffer, audio_array, sample_rate, format="WAV")
        return buffer.getvalue()

    def _resolve_device(self) -> str:
        requested = self.settings.kokoro_device
        try:
            import torch
        except ImportError:
            return "cpu"

        if requested != "auto":
            resolved = requested
        elif torch.cuda.is_available():
            resolved = "cuda"
        else:
            resolved = "cpu"

        if not self._device_logged:
            logger.info(
                "selected kokoro device",
                extra={
                    "event": "tts.device.selected",
                    "provider": "kokoro",
                    "resolved_device": resolved,
                    "torch_hip_version": getattr(torch.version, "hip", None),
                    "torch_cuda_available": torch.cuda.is_available(),
                },
            )
            self._device_logged = True
        return resolved
