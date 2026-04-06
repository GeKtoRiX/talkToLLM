from app.core.state_machine import SessionState, transition_state


def test_state_machine_happy_path():
    assert transition_state(SessionState.IDLE, "session_started") == SessionState.LISTENING
    assert transition_state(SessionState.LISTENING, "speech_started") == SessionState.CAPTURING_SPEECH
    assert transition_state(SessionState.CAPTURING_SPEECH, "speech_ended") == SessionState.TRANSCRIBING


def test_state_machine_rejects_invalid_transition():
    assert transition_state(SessionState.IDLE, "speech_started") == SessionState.IDLE

