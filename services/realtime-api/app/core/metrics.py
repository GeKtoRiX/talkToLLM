from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram, generate_latest
from starlette.responses import Response

registry = CollectorRegistry()

session_counter = Counter(
    "talktollm_sessions_total",
    "Number of realtime sessions started and stopped",
    ["event"],
    registry=registry,
)

provider_errors = Counter(
    "talktollm_provider_errors_total",
    "Provider errors by provider type",
    ["provider"],
    registry=registry,
)

interruption_counter = Counter(
    "talktollm_interruptions_total",
    "Number of playback interruptions",
    registry=registry,
)

stage_latency = Histogram(
    "talktollm_stage_latency_seconds",
    "Latency for each voice pipeline stage",
    ["stage"],
    registry=registry,
)


def observe_stage(stage: str, duration_seconds: float) -> None:
    stage_latency.labels(stage=stage).observe(duration_seconds)


def metrics_response() -> Response:
    return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
