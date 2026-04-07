from __future__ import annotations

import asyncio
import logging
import tempfile
import wave
from pathlib import Path
from typing import Any

from app.core.config import AppSettings
from app.providers.base import STTProvider, TranscriptResult

logger = logging.getLogger(__name__)


class MockWhisperProvider(STTProvider):
    def __init__(self) -> None:
        self._buffer = bytearray()

    async def start_session(self, config: dict[str, str | int]) -> None:
        self._buffer.clear()

    async def append_audio(self, chunk: bytes) -> None:
        self._buffer.extend(chunk)

    async def finalize_utterance(self) -> TranscriptResult:
        duration_seconds = len(self._buffer) / (16000 * 2)
        duration_seconds = max(duration_seconds, 0.1)
        text = (
            f"Mock transcript from approximately {duration_seconds:.1f} seconds of English audio. "
            "Replace the provider to connect real Whisper transcription."
        )
        self._buffer.clear()
        return TranscriptResult(text=text, is_final=True)


class FasterWhisperSTTProvider(STTProvider):
    _model_cache: dict[tuple[str, str, str, str], object] = {}

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self._buffer = bytearray()
        self._device_logged = False

    async def start_session(self, config: dict[str, str | int]) -> None:
        self._buffer.clear()

    async def append_audio(self, chunk: bytes) -> None:
        self._buffer.extend(chunk)

    async def finalize_utterance(self) -> TranscriptResult:
        if not self._buffer:
            return TranscriptResult(text="", is_final=True)

        audio_path = self._write_pcm_wav(bytes(self._buffer))
        self._buffer.clear()

        try:
            text = await asyncio.to_thread(self._transcribe_file, audio_path)
            return TranscriptResult(text=text.strip(), is_final=True)
        finally:
            audio_path.unlink(missing_ok=True)

    def _transcribe_file(self, audio_path: Path) -> str:
        try:
            from faster_whisper import WhisperModel
        except ImportError as error:
            raise RuntimeError(
                "faster-whisper is not installed. Install the realtime provider dependencies first."
            ) from error

        model_root = self.settings.resolve_path(self.settings.stt_model_root)
        model_root.mkdir(parents=True, exist_ok=True)
        model_source = self._resolve_model_source(model_root)
        device = self._resolve_device()
        compute_type = self.settings.stt_compute_type
        cache_key = (str(model_source), device, compute_type, str(model_root))

        model = self._model_cache.get(cache_key)
        if model is None:
            model = WhisperModel(
                str(model_source),
                device=device,
                compute_type=compute_type,
                download_root=str(model_root),
                local_files_only=self.settings.stt_local_files_only,
            )
            self._model_cache[cache_key] = model
            logger.info(
                "initialized whisper model",
                extra={
                    "event": "stt.model.initialized",
                    "provider": "faster_whisper",
                    "stt_model_size": self.settings.stt_model_size,
                    "stt_device": device,
                    "stt_compute_type": compute_type,
                    "stt_model_source": str(model_source),
                    "stt_model_root": str(model_root),
                },
            )

        segments, _info = model.transcribe(
            str(audio_path),
            language="en",
            beam_size=self.settings.stt_beam_size,
            condition_on_previous_text=False,
            vad_filter=False,
        )
        return " ".join(segment.text.strip() for segment in list(segments)).strip()

    def _resolve_model_source(self, model_root: Path) -> Path | str:
        local_model_dir = model_root / self.settings.stt_model_size
        if local_model_dir.is_dir():
            return local_model_dir
        return self.settings.stt_model_size

    def _resolve_device(self) -> str:
        requested = self.settings.stt_device
        if requested != "auto":
            return requested

        try:
            import torch
        except ImportError:
            return "cpu"

        hip_version = getattr(torch.version, "hip", None)
        cuda_available = torch.cuda.is_available()
        if hip_version and cuda_available:
            if not self._device_logged:
                logger.warning(
                    "rocm detected but faster-whisper backend does not use torch rocm; falling back to cpu",
                    extra={
                        "event": "stt.device.fallback",
                        "provider": "faster_whisper",
                        "requested_device": "auto",
                        "resolved_device": "cpu",
                        "torch_hip_version": hip_version,
                    },
                )
                self._device_logged = True
            return "cpu"

        if cuda_available:
            if not self._device_logged:
                logger.info(
                    "using cuda for faster-whisper",
                    extra={
                        "event": "stt.device.selected",
                        "provider": "faster_whisper",
                        "resolved_device": "cuda",
                    },
                )
                self._device_logged = True
            return "cuda"

        if not self._device_logged:
            logger.info(
                "using cpu for faster-whisper",
                extra={
                    "event": "stt.device.selected",
                    "provider": "faster_whisper",
                    "resolved_device": "cpu",
                    "torch_hip_version": hip_version,
                    "torch_cuda_available": cuda_available,
                },
            )
            self._device_logged = True
        return "cpu"

    def _write_pcm_wav(self, audio_bytes: bytes) -> Path:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            path = Path(handle.name)

        with wave.open(str(path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            wav_file.writeframes(audio_bytes)

        return path


class WhisperRocmSTTProvider(STTProvider):
    _model_cache: dict[tuple[str, str], Any] = {}

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self._buffer = bytearray()
        self._device_logged = False

    async def start_session(self, config: dict[str, str | int]) -> None:
        self._buffer.clear()

    async def append_audio(self, chunk: bytes) -> None:
        self._buffer.extend(chunk)

    async def finalize_utterance(self) -> TranscriptResult:
        if not self._buffer:
            return TranscriptResult(text="", is_final=True)

        audio_bytes = bytes(self._buffer)
        self._buffer.clear()
        text = await asyncio.to_thread(self._transcribe_pcm, audio_bytes)
        return TranscriptResult(text=text.strip(), is_final=True)

    def _transcribe_pcm(self, audio_bytes: bytes) -> str:
        try:
            import numpy as np
            import torch
            import whisper
        except ImportError as error:
            raise RuntimeError(
                "openai-whisper, numpy, and a ROCm-enabled torch build are required for whisper_rocm."
            ) from error

        device = self._resolve_device(torch)
        model_root = self.settings.resolve_path(self.settings.stt_model_root)
        model_root.mkdir(parents=True, exist_ok=True)
        model = self._load_model(whisper, model_root, device)

        model_device = self._model_device(model)
        if device == "cuda" and getattr(model_device, "type", None) != "cuda":
            raise RuntimeError(
                "Whisper model was expected on ROCm-backed cuda:0, but is running on "
                f"{model_device}. Check the PyTorch ROCm install."
            )

        audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        result = model.transcribe(
            audio=audio,
            language="en",
            task="transcribe",
            condition_on_previous_text=False,
            fp16=device == "cuda",
            verbose=False,
        )
        return str(result.get("text", "")).strip()

    def _load_model(self, whisper_module: Any, model_root: Path, device: str) -> Any:
        model_source = self._resolve_model_source(model_root)
        cache_key = (str(model_source), device)
        model = self._model_cache.get(cache_key)
        if model is None:
            model = whisper_module.load_model(
                str(model_source),
                device=device,
                download_root=str(model_root),
                in_memory=False,
            )
            model_device = self._model_device(model)
            self._model_cache[cache_key] = model
            logger.info(
                "initialized whisper rocm model",
                extra={
                    "event": "stt.model.initialized",
                    "provider": "whisper_rocm",
                    "stt_model_size": self.settings.stt_model_size,
                    "stt_model_source": str(model_source),
                    "stt_model_root": str(model_root),
                    "stt_device": device,
                    "stt_model_device": str(model_device),
                },
            )
        return model

    def _resolve_model_source(self, model_root: Path) -> Path | str:
        local_model_path = model_root / f"{self.settings.stt_model_size}.pt"
        if local_model_path.is_file():
            return local_model_path
        if self.settings.stt_local_files_only:
            raise RuntimeError(
                f"Local Whisper checkpoint not found at {local_model_path}. "
                "Run scripts/prepare_local_models.py or disable STT_LOCAL_FILES_ONLY."
            )
        return self.settings.stt_model_size

    def _resolve_device(self, torch: Any) -> str:
        requested = self.settings.stt_device
        hip_version = getattr(torch.version, "hip", None)
        cuda_available = torch.cuda.is_available()

        if requested == "cpu":
            self._log_device_selection(
                requested=requested,
                resolved="cpu",
                hip_version=hip_version,
                cuda_available=cuda_available,
                torch=torch,
            )
            return "cpu"

        if hip_version and cuda_available:
            self._log_device_selection(
                requested=requested,
                resolved="cuda",
                hip_version=hip_version,
                cuda_available=cuda_available,
                torch=torch,
            )
            return "cuda"

        if self.settings.stt_allow_cpu_fallback:
            self._log_device_selection(
                requested=requested,
                resolved="cpu",
                hip_version=hip_version,
                cuda_available=cuda_available,
                torch=torch,
            )
            logger.warning(
                "whisper_rocm requested without a working ROCm runtime; using explicit cpu fallback",
                extra={
                    "event": "stt.device.fallback",
                    "provider": "whisper_rocm",
                    "requested_device": requested,
                    "resolved_device": "cpu",
                },
            )
            return "cpu"

        raise RuntimeError(
            "whisper_rocm requires a ROCm-enabled torch runtime. "
            f"torch.__version__={torch.__version__}, "
            f"torch.version.hip={hip_version}, "
            f"torch.cuda.is_available()={cuda_available}. "
            "Install the ROCm torch build or set STT_ALLOW_CPU_FALLBACK=true for explicit CPU fallback."
        )

    def _log_device_selection(
        self,
        *,
        requested: str,
        resolved: str,
        hip_version: str | None,
        cuda_available: bool,
        torch: Any,
    ) -> None:
        if self._device_logged:
            return
        device_name = None
        if resolved == "cuda" and cuda_available:
            device_name = torch.cuda.get_device_name(0)
        logger.info(
            "selected whisper device",
            extra={
                "event": "stt.device.selected",
                "provider": "whisper_rocm",
                "requested_device": requested,
                "resolved_device": resolved,
                "torch_version": torch.__version__,
                "torch_hip_version": hip_version,
                "torch_cuda_available": cuda_available,
                "torch_device_name": device_name,
            },
        )
        self._device_logged = True

    def _model_device(self, model: Any) -> Any:
        try:
            return next(model.parameters()).device
        except StopIteration:
            return "unknown"
