from __future__ import annotations

from pathlib import Path

from huggingface_hub import hf_hub_download, snapshot_download
import whisper


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODELS_ROOT = PROJECT_ROOT / "models"
WHISPER_ROOT = MODELS_ROOT / "whisper"
KOKORO_ROOT = MODELS_ROOT / "kokoro"

WHISPER_MODEL_SIZE = "base.en"
WHISPER_REPO_ID = f"Systran/faster-whisper-{WHISPER_MODEL_SIZE}"
KOKORO_REPO_ID = "hexgrad/Kokoro-82M"
KOKORO_VOICE = "af_heart"


def main() -> None:
    WHISPER_ROOT.mkdir(parents=True, exist_ok=True)
    KOKORO_ROOT.mkdir(parents=True, exist_ok=True)

    whisper_target = WHISPER_ROOT / WHISPER_MODEL_SIZE
    snapshot_download(
        repo_id=WHISPER_REPO_ID,
        local_dir=whisper_target,
    )
    whisper_model = whisper.load_model(WHISPER_MODEL_SIZE, device="cpu", download_root=str(WHISPER_ROOT), in_memory=False)
    del whisper_model
    whisper_checkpoint = WHISPER_ROOT / f"{WHISPER_MODEL_SIZE}.pt"

    hf_hub_download(repo_id=KOKORO_REPO_ID, filename="config.json", local_dir=KOKORO_ROOT)
    hf_hub_download(repo_id=KOKORO_REPO_ID, filename="kokoro-v1_0.pth", local_dir=KOKORO_ROOT)
    voice_path = hf_hub_download(
        repo_id=KOKORO_REPO_ID,
        filename=f"voices/{KOKORO_VOICE}.pt",
        local_dir=KOKORO_ROOT,
    )

    print(f"Faster-Whisper model prepared at: {whisper_target}")
    print(f"OpenAI Whisper checkpoint prepared at: {whisper_checkpoint}")
    print(f"Kokoro config/model prepared at: {KOKORO_ROOT}")
    print(f"Kokoro voice prepared at: {voice_path}")


if __name__ == "__main__":
    main()
