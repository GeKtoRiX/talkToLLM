from __future__ import annotations

import argparse
from pathlib import Path

from huggingface_hub import hf_hub_download, snapshot_download
import whisper


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODELS_ROOT = PROJECT_ROOT / "models"
WHISPER_ROOT = MODELS_ROOT / "whisper"
KOKORO_ROOT = MODELS_ROOT / "kokoro"
OCR_ROOT = MODELS_ROOT / "ocr"

WHISPER_MODEL_SIZE = "medium.en"
WHISPER_REPO_ID = f"Systran/faster-whisper-{WHISPER_MODEL_SIZE}"
KOKORO_REPO_ID = "hexgrad/Kokoro-82M"
KOKORO_VOICE = "af_heart"
OCR_REPO_ID = "stepfun-ai/GOT-OCR-2.0-hf"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pre-download local talkToLLM model assets into ./models.",
    )
    parser.add_argument(
        "--include-ocr",
        action="store_true",
        help="also download GOT-OCR-2.0 weights into models/ocr/GOT-OCR-2.0-hf",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
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

    if args.include_ocr:
        ocr_target = OCR_ROOT / "GOT-OCR-2.0-hf"
        OCR_ROOT.mkdir(parents=True, exist_ok=True)
        snapshot_download(repo_id=OCR_REPO_ID, local_dir=ocr_target)
        print(f"GOT-OCR-2.0 model prepared at: {ocr_target}")
    else:
        print("Skipping GOT-OCR-2.0 download. Re-run with --include-ocr to prefetch OCR weights.")


if __name__ == "__main__":
    main()
