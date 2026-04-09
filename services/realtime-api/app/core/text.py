import re

from app.api.protocol import ImageAttachment
from app.providers.base import ChatImagePart, ChatMessage, ChatTextPart

# Matches characters/sequences that TTS should not read aloud.
_MARKDOWN_RE = re.compile(
    r"\*{1,3}|_{1,3}|~~|`{1,3}|#{1,6}\s*"  # bold, italic, strike, code, headers
    r"|!\[.*?\]\(.*?\)"                       # images ![alt](url)
    r"|\[([^\]]*)\]\(.*?\)"                   # links [text](url) → keep text
    r"|<[^>]+>"                               # HTML tags
)
# Unicode emoji ranges (BMP + supplementary planes)
_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U00002700-\U000027BF"  # dingbats
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U00002600-\U000026FF"  # misc symbols
    "\U00002B50-\U00002B55"  # stars
    "\U0000FE0F"             # variation selector
    "\U0001FA00-\U0001FA9F"  # chess / symbols ext-A
    "]+",
    flags=re.UNICODE,
)


def strip_tts_noise(text: str) -> str:
    """Remove markdown formatting and emoji that TTS would read literally."""
    # Replace [text](url) links with just the text
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    # Remove remaining markdown tokens
    text = re.sub(r"\*{1,3}|_{1,3}|~~|`{1,3}|#{1,6}\s*|!\[[^\]]*\]\([^)]*\)|<[^>]+>", "", text)
    # Remove emoji
    text = _EMOJI_RE.sub("", text)
    # Collapse extra whitespace
    text = re.sub(r" {2,}", " ", text).strip()
    return text


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


