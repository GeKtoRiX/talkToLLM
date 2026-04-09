from app.providers.base import ChatTextPart
from app.core.text import SentenceChunker, build_prompt_messages, strip_tts_noise


def test_strip_tts_noise_removes_bold_and_italic():
    assert strip_tts_noise("**bold** and *italic* text") == "bold and italic text"


def test_strip_tts_noise_removes_headers():
    assert strip_tts_noise("## Section title") == "Section title"


def test_strip_tts_noise_removes_emoji():
    assert strip_tts_noise("Hello! 😊 How are you? 🎉") == "Hello! How are you?"


def test_strip_tts_noise_keeps_link_text():
    assert strip_tts_noise("See [the docs](https://example.com) for details.") == "See the docs for details."


def test_strip_tts_noise_removes_backticks():
    assert strip_tts_noise("Use `print()` to debug.") == "Use print() to debug."


def test_strip_tts_noise_plain_text_unchanged():
    assert strip_tts_noise("Hello, world. How are you?") == "Hello, world. How are you?"


def test_sentence_chunker_emits_complete_sentences():
    chunker = SentenceChunker()
    sentences = chunker.push("Hello there. How are")
    sentences.extend(chunker.push(" you?"))
    assert sentences == ["Hello there.", "How are you?"]


def test_ocr_prompt_includes_markdown_label():
    messages = build_prompt_messages("sys", [], "what is shown?", ocr_texts=["# Heading\nsome text"])
    text = messages[-1].content_parts[0].text
    assert "Markdown" in text
    assert "# Heading" in text
    assert "what is shown?" in text


def test_prompt_builder_keeps_system_message_and_last_turns():
    history = [{"role": "assistant", "content": f"turn-{index}"} for index in range(10)]
    messages = build_prompt_messages("system", history, "user-turn")
    assert messages[0].role == "system"
    assert isinstance(messages[0].content_parts[0], ChatTextPart)
    assert messages[0].content_parts[0].text == "system"
    assert messages[-1].role == "user"
    assert isinstance(messages[-1].content_parts[0], ChatTextPart)
    assert messages[-1].content_parts[0].text == "user-turn"
    assert len(messages) == 8
