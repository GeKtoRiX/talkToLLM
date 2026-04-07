import { useEffect, useRef } from "react";
import { StatusPill } from "./components/StatusPill";
import { acceptedImageFileInput } from "./lib/imageAttachments";
import { useVoiceSession } from "./hooks/useVoiceSession";

export default function App() {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const conversationEndRef = useRef<HTMLDivElement | null>(null);

  const {
    sessionState,
    transcript,
    assistantText,
    conversationHistory,
    error,
    connected,
    textQuestion,
    setTextQuestion,
    activeScreenshot,
    activeScreenshotPreviewUrl,
    replaceActiveScreenshotFromFile,
    clearActiveScreenshot,
    startSession,
    stopSession,
    startTalking,
    stopTalking,
    submitTextTurn,
    interrupt,
  } = useVoiceSession();

  useEffect(() => {
    conversationEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [conversationHistory, transcript, assistantText]);

  return (
    <main className="app-shell">
      <section className="hero-card">
        <div className="status-row">
          <StatusPill label={`State: ${sessionState}`} tone={error ? "danger" : "default"} />
          <StatusPill label={connected ? "Realtime connected" : "Disconnected"} tone={connected ? "success" : "warning"} />
          {activeScreenshot ? <StatusPill label="Screenshot active for next turns" tone="success" /> : null}
        </div>

        <section className="screenshot-card">
          <p className="panel-title">Active Screenshot</p>

          <input
            ref={fileInputRef}
            aria-label="Upload screenshot"
            className="screenshot-input"
            type="file"
            accept={acceptedImageFileInput}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) {
                void replaceActiveScreenshotFromFile(file);
              }
              event.currentTarget.value = "";
            }}
          />

          {activeScreenshot ? (
            <>
              <div className="screenshot-card__body">
                <img className="screenshot-preview" alt="Active screenshot preview" src={activeScreenshotPreviewUrl!} />
                <div className="screenshot-meta">
                  <p className="screenshot-meta__line">{activeScreenshot.name || "clipboard-screenshot"}</p>
                  <p className="screenshot-meta__line">
                    {activeScreenshot.width} x {activeScreenshot.height} px
                  </p>
                  <p className="screenshot-meta__line">{activeScreenshot.mimeType}</p>
                </div>
              </div>
              <div className="actions">
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => fileInputRef.current?.click()}
                >
                  Replace Screenshot
                </button>
                <button type="button" className="secondary-button" onClick={clearActiveScreenshot}>
                  Clear Screenshot
                </button>
              </div>
            </>
          ) : (
            <div className="screenshot-empty">
              <button
                type="button"
                className="secondary-button"
                onClick={() => fileInputRef.current?.click()}
              >
                Upload Screenshot
              </button>
              <span className="screenshot-empty__hint">or paste (Ctrl+V)</span>
            </div>
          )}
        </section>

        <div className="actions">
          <button type="button" className="primary-button" onClick={startSession} disabled={connected}>
            Start Conversation
          </button>
          <button type="button" className="secondary-button" onClick={stopSession} disabled={!connected}>
            Stop Session
          </button>
          <button
            type="button"
            className="talk-button"
            aria-keyshortcuts="Q"
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
            Hold to Talk (Q)
          </button>
          <button type="button" className="secondary-button" onClick={interrupt} disabled={!connected}>
            Interrupt Playback
          </button>
        </div>

        <form
          className="text-turn-form"
          onSubmit={(event) => {
            event.preventDefault();
            submitTextTurn();
          }}
        >
          <input
            aria-label="Type a question"
            className="text-turn-input"
            type="text"
            placeholder="Ask about the screenshot or type a task..."
            value={textQuestion}
            onChange={(event) => setTextQuestion(event.target.value)}
          />
          <button type="submit" className="primary-button" disabled={!connected || !textQuestion.trim()}>
            Send Text
          </button>
        </form>

        {error ? <p className="error-banner">{error}</p> : null}
      </section>

      <section className="panels">
        <article className="panel-card">
          <p className="panel-title">Conversation</p>
          <div className="conversation-messages">
            {conversationHistory.length === 0 && !transcript && !assistantText ? (
              <p className="panel-body">Your conversation will appear here.</p>
            ) : null}
            {conversationHistory.map((msg, i) => (
              <div key={i} className={`conversation-message conversation-message--${msg.role}`}>
                <span className="conversation-message__role">{msg.role === "user" ? "You" : "Assistant"}</span>
                <p className="conversation-message__text">{msg.text}</p>
              </div>
            ))}
            {transcript ? (
              <div className="conversation-message conversation-message--user conversation-message--streaming">
                <span className="conversation-message__role">You</span>
                <p className="conversation-message__text">{transcript}</p>
              </div>
            ) : null}
            {assistantText ? (
              <div className="conversation-message conversation-message--assistant conversation-message--streaming">
                <span className="conversation-message__role">Assistant</span>
                <p className="conversation-message__text">{assistantText}</p>
              </div>
            ) : null}
            <div ref={conversationEndRef} />
          </div>
        </article>
      </section>
    </main>
  );
}
