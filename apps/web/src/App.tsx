import { useRef } from "react";
import { StatusPill } from "./components/StatusPill";
import { TranscriptPanel } from "./components/TranscriptPanel";
import { acceptedImageFileInput } from "./lib/imageAttachments";
import { useVoiceSession } from "./hooks/useVoiceSession";

export default function App() {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const {
    sessionState,
    transcript,
    assistantText,
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
          {activeScreenshot ? <StatusPill label="Screenshot active for next turns" tone="success" /> : null}
        </div>

        <section className="screenshot-card">
          <div className="screenshot-card__header">
            <div>
              <p className="panel-title">Active Screenshot</p>
              <p className="screenshot-help">
                Paste a screenshot anywhere or upload a PNG, JPG, or WebP file. The latest screenshot stays active
                until you replace or clear it.
              </p>
            </div>
          </div>

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

          <div className="screenshot-card__body">
            {activeScreenshotPreviewUrl ? (
              <img className="screenshot-preview" alt="Active screenshot preview" src={activeScreenshotPreviewUrl} />
            ) : (
              <div className="screenshot-empty">No screenshot attached yet.</div>
            )}

            <div className="screenshot-meta">
              {activeScreenshot ? (
                <>
                  <p className="screenshot-meta__line">{activeScreenshot.name || "clipboard-screenshot"}</p>
                  <p className="screenshot-meta__line">
                    {activeScreenshot.width} x {activeScreenshot.height} px
                  </p>
                  <p className="screenshot-meta__line">{activeScreenshot.mimeType}</p>
                </>
              ) : (
                <>
                  <p className="screenshot-meta__line">Use PrintScreen + paste for the fastest workflow.</p>
                  <p className="screenshot-meta__line">You can then ask about the screenshot by voice or text.</p>
                </>
              )}
            </div>
          </div>

          <div className="actions">
            <button
              type="button"
              className="secondary-button"
              onClick={() => {
                fileInputRef.current?.click();
              }}
            >
              {activeScreenshot ? "Replace Screenshot" : "Upload Screenshot"}
            </button>
            <button type="button" className="secondary-button" onClick={clearActiveScreenshot} disabled={!activeScreenshot}>
              Clear Screenshot
            </button>
          </div>
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
        <TranscriptPanel title="Transcript" body={transcript || "Your final transcript will appear here."} />
        <TranscriptPanel title="Assistant" body={assistantText || "The assistant response will stream here."} />
      </section>
    </main>
  );
}
