from collections.abc import Iterable


def build_prompt_messages(system_prompt: str, history: list[dict[str, str]], user_text: str) -> list[dict[str, str]]:
    rolling_history = history[-6:]
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(rolling_history)
    messages.append({"role": "user", "content": user_text})
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

