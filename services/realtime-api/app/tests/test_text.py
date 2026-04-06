from app.core.text import SentenceChunker, build_prompt_messages


def test_sentence_chunker_emits_complete_sentences():
    chunker = SentenceChunker()
    sentences = chunker.push("Hello there. How are")
    sentences.extend(chunker.push(" you?"))
    assert sentences == ["Hello there.", "How are you?"]


def test_prompt_builder_keeps_system_message_and_last_turns():
    history = [{"role": "assistant", "content": f"turn-{index}"} for index in range(10)]
    messages = build_prompt_messages("system", history, "user-turn")
    assert messages[0] == {"role": "system", "content": "system"}
    assert messages[-1] == {"role": "user", "content": "user-turn"}
    assert len(messages) == 8

