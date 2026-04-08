from collections.abc import Iterable

from app.api.protocol import ImageAttachment
from app.providers.base import ChatImagePart, ChatMessage, ChatTextPart


def build_text_message(role: str, text: str) -> ChatMessage:
    return ChatMessage(role=role, content_parts=[ChatTextPart(text=text)])


def build_prompt_messages(
    system_prompt: str,
    history: list[dict[str, str]],
    user_text: str,
    attachments: list[ImageAttachment] | None = None,
    ocr_texts: list[str] | None = None,
) -> list[ChatMessage]:
    rolling_history = history[-6:]
    messages = [build_text_message("system", system_prompt)]
    messages.extend(build_text_message(item["role"], item["content"]) for item in rolling_history)

    if ocr_texts:
        formatted = "\n\n---\n\n".join(ocr_texts)
        user_text = f"[Текст скриншота (Markdown, сохранён порядок чтения):\n{formatted}]\n\n{user_text}"

    user_parts = [ChatTextPart(text=user_text)]
    # Only attach the raw image when OCR did not produce text (fallback path).
    if not ocr_texts:
        user_parts.extend(
            ChatImagePart(mime_type=att.mimeType, data_base64=att.dataBase64)
            for att in attachments or []
        )
    messages.append(ChatMessage(role="user", content_parts=user_parts))
    return messages


class SentenceChunker:
    def __init__(self) -> None:
        self.buffer = ""

    def push(self, delta: str) -> list[str]:
        self.buffer += delta
        return self._extract_sentences()

    def flush(self) -> list[str]:
        remainder = self.buffer.strip()
        self.buffer = ""
        return [remainder] if remainder else []

    def _extract_sentences(self) -> list[str]:
        sentences: list[str] = []
        current = []
        for character in self.buffer:
            current.append(character)
            if character in ".?!\n":
                candidate = "".join(current).strip()
                if candidate:
                    sentences.append(candidate)
                current = []

        self.buffer = "".join(current)
        return sentences


def stream_words(text: str) -> Iterable[str]:
    words = text.split(" ")
    for index, word in enumerate(words):
        suffix = " " if index < len(words) - 1 else ""
        yield word + suffix
