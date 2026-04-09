"""Unit tests for speech-to-text provider device resolution and validation."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

from app.core.config import AppSettings
from app.providers.stt import WhisperRocmSTTProvider


def _fake_torch(*, hip_version: str | None, cuda_available: bool, device_name: str = "AMD Radeon Graphics"):
    return SimpleNamespace(
        __version__="test-torch",
        version=SimpleNamespace(hip=hip_version),
        cuda=SimpleNamespace(
            is_available=lambda: cuda_available,
            get_device_name=lambda _index: device_name,
        ),
    )


def test_whisper_rocm_auto_resolves_to_cuda_on_rocm_runtime():
    provider = WhisperRocmSTTProvider(
        AppSettings(
            stt_provider="whisper_rocm",
            stt_device="auto",
            stt_allow_cpu_fallback=False,
        )
    )

    resolved = provider._resolve_device(_fake_torch(hip_version="6.4.0", cuda_available=True))

    assert resolved == "cuda"


def test_whisper_rocm_requires_rocm_when_cpu_fallback_disabled():
    provider = WhisperRocmSTTProvider(
        AppSettings(
            stt_provider="whisper_rocm",
            stt_device="auto",
            stt_allow_cpu_fallback=False,
        )
    )

    with pytest.raises(RuntimeError, match="requires a ROCm-enabled torch runtime"):
        provider._resolve_device(_fake_torch(hip_version=None, cuda_available=False))


def test_whisper_rocm_can_explicitly_fallback_to_cpu():
    provider = WhisperRocmSTTProvider(
        AppSettings(
            stt_provider="whisper_rocm",
            stt_device="auto",
            stt_allow_cpu_fallback=True,
        )
    )

    resolved = provider._resolve_device(_fake_torch(hip_version=None, cuda_available=False))

    assert resolved == "cpu"


def test_whisper_rocm_resolves_local_medium_checkpoint(tmp_path: Path):
    checkpoint = tmp_path / "medium.en.pt"
    checkpoint.write_bytes(b"fake whisper checkpoint")
    provider = WhisperRocmSTTProvider(
        AppSettings(
            stt_provider="whisper_rocm",
            stt_model_size="medium.en",
            stt_local_files_only=True,
        )
    )

    resolved = provider._resolve_model_source(tmp_path)

    assert resolved == checkpoint


def test_whisper_rocm_raises_if_model_is_not_on_cuda(monkeypatch, tmp_path: Path):
    checkpoint = tmp_path / "medium.en.pt"
    checkpoint.write_bytes(b"fake whisper checkpoint")
    provider = WhisperRocmSTTProvider(
        AppSettings(
            stt_provider="whisper_rocm",
            stt_model_root=str(tmp_path),
            stt_model_size="medium.en",
            stt_device="auto",
            stt_local_files_only=True,
            stt_allow_cpu_fallback=False,
        )
    )

    fake_torch = _fake_torch(hip_version="6.4.0", cuda_available=True)

    class FakeModel:
        def parameters(self):
            yield SimpleNamespace(device=SimpleNamespace(type="cpu"))

        def transcribe(self, **_kwargs):
            return {"text": "should not be reached"}

    fake_whisper = SimpleNamespace(load_model=lambda *_args, **_kwargs: FakeModel())

    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "whisper", fake_whisper)

    with pytest.raises(RuntimeError, match="expected on ROCm-backed cuda:0"):
        provider._transcribe_pcm(b"\x00\x00" * 16)
