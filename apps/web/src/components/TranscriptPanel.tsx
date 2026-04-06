type TranscriptPanelProps = {
  title: string;
  body: string;
};

export function TranscriptPanel({ title, body }: TranscriptPanelProps) {
  return (
    <article className="panel-card">
      <p className="panel-title">{title}</p>
      <p className="panel-body">{body}</p>
    </article>
  );
}

