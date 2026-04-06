import { StatusPill } from "./components/StatusPill";
import { TranscriptPanel } from "./components/TranscriptPanel";
import { useVoiceSession } from "./hooks/useVoiceSession";

export default function App() {
  const {
    sessionState,
    transcript,
    assistantText,
    error,
    connected,
    startSession,
    stopSession,
    startTalking,
    stopTalking,
    interrupt,
  } = useVoiceSession();

  return (
    <main className="app-shell">
      <section className="hero-card">
        <div className="hero-copy">
          <p className="eyebrow">English-only prototype</p>
          <h1>Realtime Voice Loop For LLM Conversations</h1>
          <p className="lede">
            Push to talk, watch transcripts stream, and interrupt playback instantly. The frontend uses
            browser audio capture, a websocket session, and a playback queue designed for barge-in.
          </p>
        </div>

        <div className="status-row">
          <StatusPill label={`State: ${sessionState}`} tone={error ? "danger" : "default"} />
          <StatusPill label={connected ? "Realtime connected" : "Disconnected"} tone={connected ? "success" : "warning"} />
        </div>

        <div className="actions">
          <button className="primary-button" onClick={startSession} disabled={connected}>
            Start Conversation
          </button>
          <button className="secondary-button" onClick={stopSession} disabled={!connected}>
            Stop Session
          </button>
          <button
            className="talk-button"
            onMouseDown={startTalking}
            onMouseUp={stopTalking}
            onMouseLeave={stopTalking}
            onTouchStart={(event) => {
              event.preventDefault();
              startTalking();
            }}
            onTouchEnd={(event) => {
              event.preventDefault();
              stopTalking();
            }}
            disabled={!connected}
          >
            Hold to Talk
          </button>
          <button className="secondary-button" onClick={interrupt} disabled={!connected}>
            Interrupt Playback
          </button>
        </div>

        {error ? <p className="error-banner">{error}</p> : null}
      </section>

      <section className="panels">
        <TranscriptPanel title="Transcript" body={transcript || "Your final transcript will appear here."} />
        <TranscriptPanel title="Assistant" body={assistantText || "The assistant response will stream here."} />
      </section>
    </main>
  );
}

