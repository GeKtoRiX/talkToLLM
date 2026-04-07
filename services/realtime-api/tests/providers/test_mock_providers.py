"""Unit tests for mock STT, LLM, and TTS provider implementations."""
from __future__ import annotations

import io
import wave

import pytest

from app.providers.base import ChatMessage, ChatTextPart, TranscriptResult, TtsChunk
from app.providers.llm import MockLLMProvider
from app.providers.stt import MockWhisperProvider
from app.providers.tts import MockKokoroProvider, build_tone_wav


# ── MockWhisperProvider ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mock_whisper_returns_transcript_result():
    provider = MockWhisperProvider()
    await provider.start_session({"sample_rate": 16000})
    await provider.append_audio(b"\x00\x00" * 16000)

    result = await provider.finalize_utterance()

    assert isinstance(result, TranscriptResult)
    assert result.is_final is True
    assert len(result.text) > 0


@pytest.mark.asyncio
async def test_mock_whisper_clears_buffer_after_finalize():
    provider = MockWhisperProvider()
    await provider.start_session({})
    await provider.append_audio(b"\x01\x02" * 1000)

    await provider.finalize_utterance()

    assert len(provider._buffer) == 0


@pytest.mark.asyncio
async def test_mock_whisper_start_session_clears_buffer():
    provider = MockWhisperProvider()
    await provider.append_audio(b"\xff" * 100)

    await provider.start_session({})

    assert len(provider._buffer) == 0


@pytest.mark.asyncio
async def test_mock_whisper_duration_scales_with_audio_length():
    provider = MockWhisperProvider()
    await provider.start_session({})
    # 2 seconds of PCM at 16 kHz, 16-bit = 64000 bytes
    await provider.append_audio(b"\x00\x00" * 32000)

    result = await provider.finalize_utterance()

    assert "2.0 seconds" in result.text


# ── MockLLMProvider ───────────────────────────────────────────────────────────


def _user_message(text: str) -> list[ChatMessage]:
    return [ChatMessage(role="user", content_parts=[ChatTextPart(text=text)])]


@pytest.mark.asyncio
async def test_mock_llm_streams_non_empty_response():
    provider = MockLLMProvider()
    chunks: list[str] = []
    async for delta in provider.stream(_user_message("hello"), config={"turn_id": "t1"}):
        chunks.append(delta)

    assert len(chunks) > 0
    assert "".join(chunks).strip()


@pytest.mark.asyncio
async def test_mock_llm_echoes_user_text():
    provider = MockLLMProvider()
    chunks: list[str] = []
    async for delta in provider.stream(_user_message("tell me a joke"), config={}):
        chunks.append(delta)

    full = "".join(chunks)
    assert "tell me a joke" in full


@pytest.mark.asyncio
async def test_mock_llm_mentions_screenshot_when_has_images():
    from app.providers.base import ChatImagePart

    msg = ChatMessage(
        role="user",
        content_parts=[
            ChatTextPart(text="analyze this"),
            ChatImagePart(mime_type="image/png", data_base64="ZmFrZQ=="),
        ],
    )
    provider = MockLLMProvider()
    chunks: list[str] = []
    async for delta in provider.stream([msg], config={"has_images": True}):
        chunks.append(delta)

    assert "screenshot" in "".join(chunks).lower()


@pytest.mark.asyncio
async def test_mock_llm_cancel_does_not_raise():
    provider = MockLLMProvider()
    await provider.cancel("any-id")


# ── MockKokoroProvider ────────────────────────────────────────────────────────


async def _collect_tts(sentences: list[tuple[int, str]]) -> list[TtsChunk]:
    provider = MockKokoroProvider()

    async def stream():
        for item in sentences:
            yield item

    return [chunk async for chunk in provider.stream_synthesize(stream(), voice="default", format="wav")]


@pytest.mark.asyncio
async def test_mock_tts_yields_one_chunk_per_sentence():
    chunks = await _collect_tts([(0, "Hello world."), (1, "How are you?")])
    assert len(chunks) == 2


@pytest.mark.asyncio
async def test_mock_tts_chunk_has_correct_index_and_mime():
    chunks = await _collect_tts([(0, "Hi."), (1, "Bye.")])
    assert chunks[0].chunk_index == 0
    assert chunks[1].chunk_index == 1
    assert all(c.mime_type == "audio/wav" for c in chunks)


@pytest.mark.asyncio
async def test_mock_tts_audio_bytes_are_valid_wav():
    chunks = await _collect_tts([(0, "Test sentence.")])
    wav_bytes = chunks[0].audio_bytes
    with wave.open(io.BytesIO(wav_bytes)) as wf:
        assert wf.getnchannels() == 1
        assert wf.getframerate() == 16000
        assert wf.getnframes() > 0


@pytest.mark.asyncio
async def test_mock_tts_cancel_does_not_raise():
    provider = MockKokoroProvider()
    await provider.cancel("any-id")


# ── build_tone_wav ────────────────────────────────────────────────────────────


def test_build_tone_wav_produces_valid_wav():
    wav_bytes = build_tone_wav(0.1, sample_rate=16000, frequency=440.0)
    with wave.open(io.BytesIO(wav_bytes)) as wf:
        assert wf.getnchannels() == 1
        assert wf.getframerate() == 16000
        assert wf.getnframes() == pytest.approx(1600, abs=5)


def test_build_tone_wav_respects_duration():
    short = build_tone_wav(0.1, sample_rate=16000)
    long_ = build_tone_wav(1.0, sample_rate=16000)
    assert len(long_) > len(short)
