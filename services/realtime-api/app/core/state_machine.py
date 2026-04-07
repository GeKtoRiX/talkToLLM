from enum import StrEnum


class SessionState(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    CAPTURING_SPEECH = "capturing_speech"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    SYNTHESIZING = "synthesizing"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"
    ERROR = "error"


TRANSITIONS: dict[SessionState, dict[str, SessionState]] = {
    SessionState.IDLE: {"session_started": SessionState.LISTENING, "failed": SessionState.ERROR},
    SessionState.LISTENING: {
        "speech_started": SessionState.CAPTURING_SPEECH,
        "session_stopped": SessionState.IDLE,
        "failed": SessionState.ERROR,
    },
    SessionState.CAPTURING_SPEECH: {
        "speech_ended": SessionState.TRANSCRIBING,
        "playback_interrupted": SessionState.INTERRUPTED,
        "failed": SessionState.ERROR,
    },
    SessionState.TRANSCRIBING: {
        "transcript_finalized": SessionState.THINKING,
        "session_stopped": SessionState.IDLE,
        "failed": SessionState.ERROR,
    },
    SessionState.THINKING: {
        "tts_started": SessionState.SYNTHESIZING,
        "session_stopped": SessionState.IDLE,
        "failed": SessionState.ERROR,
    },
    SessionState.SYNTHESIZING: {
        "playback_started": SessionState.SPEAKING,
        "playback_interrupted": SessionState.INTERRUPTED,
        "failed": SessionState.ERROR,
    },
    SessionState.SPEAKING: {
        "speech_started": SessionState.CAPTURING_SPEECH,
        "playback_interrupted": SessionState.INTERRUPTED,
        "session_stopped": SessionState.IDLE,
        "failed": SessionState.ERROR,
    },
    SessionState.INTERRUPTED: {
        "speech_started": SessionState.CAPTURING_SPEECH,
        "session_stopped": SessionState.IDLE,
        "failed": SessionState.ERROR,
    },
    SessionState.ERROR: {
        "session_started": SessionState.LISTENING,
        "speech_started": SessionState.CAPTURING_SPEECH,
        "session_stopped": SessionState.IDLE,
    },
}


def transition_state(current: SessionState, action: str) -> SessionState:
    return TRANSITIONS[current].get(action, current)
