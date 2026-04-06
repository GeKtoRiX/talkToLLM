type StatusPillProps = {
  label: string;
  tone?: "default" | "success" | "warning" | "danger";
};

export function StatusPill({ label, tone = "default" }: StatusPillProps) {
  return <span className={`status-pill status-pill--${tone}`}>{label}</span>;
}

