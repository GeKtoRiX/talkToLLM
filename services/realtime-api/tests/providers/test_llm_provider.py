from app.api.protocol import ImageAttachment
from app.core.text import build_prompt_messages
from app.providers.base import ChatImagePart, ChatMessage, ChatTextPart
from app.providers.llm import LMStudioLLMProvider


def test_build_prompt_messages_keeps_history_text_only_and_attaches_image_to_current_turn():
    attachment = ImageAttachment(
        mimeType="image/png",
        dataBase64="ZmFrZQ==",
        width=640,
        height=480,
        name="problem.png",
    )

    messages = build_prompt_messages(
        "system prompt",
        [{"role": "assistant", "content": "previous text reply"}],
        "Please analyze the screenshot.",
        [attachment],
    )

    assert len(messages) == 3
    assert messages[1].role == "assistant"
    assert isinstance(messages[1].content_parts[0], ChatTextPart)
    assert isinstance(messages[-1].content_parts[0], ChatTextPart)
    assert isinstance(messages[-1].content_parts[1], ChatImagePart)


def test_lmstudio_message_serialization_uses_image_url_parts():
    messages = [
        ChatMessage(role="system", content_parts=[ChatTextPart(text="You are helpful.")]),
        ChatMessage(
            role="user",
            content_parts=[
                ChatTextPart(text="Study this screenshot."),
                ChatImagePart(mime_type="image/png", data_base64="ZmFrZQ=="),
            ],
        ),
    ]

    serialized = LMStudioLLMProvider._build_openai_messages(messages)

    assert serialized[0] == {"role": "system", "content": "You are helpful."}
    assert serialized[1]["role"] == "user"
    assert serialized[1]["content"][0] == {"type": "text", "text": "Study this screenshot."}
    assert serialized[1]["content"][1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,ZmFrZQ=="},
    }
