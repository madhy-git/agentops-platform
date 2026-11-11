"""OpenTelemetry setup: traces AND metrics, plus the app's business metrics in one place.

LEARNING NOTES
- A *trace* is one request's journey; *spans* are its steps (HTTP request -> triage -> agent.run -> model call
  -> SQL...). Attributes on spans (model, tokens, cost, prompt version) answer "why was THIS one slow/expensive?".
- *Metrics* are numbers aggregated over time (requests/s, p95 latency, tokens per hour, blocks per day). They
  answer "is the system healthy?" and drive dashboards and alerts. Traces explain one request; metrics
  describe all of them. You need both.
- Exporters decide where telemetry goes. Here: OTLP to an OpenTelemetry Collector, which routes traces to Jaeger
  and metrics to Prometheus (deploy/k8s-local/observability.yaml). On AWS the same app sends to ADOT -> X-Ray /
  CloudWatch. The app never knows which backend is behind the collector.
- Auto-instrumentation: FastAPI (every HTTP request becomes a root span, with route and status), psycopg (every
  SQL statement becomes a child span), PydanticAI (every model request, with model name and token usage).
- Data minimisation: PydanticAI is instrumented with include_content=False, so prompts and answers are NOT put in
  spans. The exact conversation lives in the access-controlled, append-only AI trail (model_traces) instead.
  Telemetry backends usually have wider access and longer retention than the database: keep content out.
- Never put raw PII in attributes or metric labels. Labels must also be low-cardinality: category, model, status
  are fine; a case id or user id as a metric label would create one time series per value and swamp Prometheus.
"""

from __future__ import annotations

import os
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

_exporter: InMemorySpanExporter | None = None
_provider: TracerProvider | None = None
_instrumented = False


def _resource() -> Resource:
    # OTEL_SERVICE_NAME distinguishes the API from the worker in Jaeger and Grafana (set per Deployment).
    return Resource.create({"service.name": os.getenv("OTEL_SERVICE_NAME", "agentops-platform")})


def init(console: bool = False, memory: bool = False) -> InMemorySpanExporter | None:
    global _exporter, _provider
    if _provider is None:
        _provider = TracerProvider(resource=_resource())
        trace.set_tracer_provider(_provider)
        if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
            # Endpoint (and headers, e.g. Langfuse auth) come from the standard OTEL_* environment variables.
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

            _provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
            reader = PeriodicExportingMetricReader(OTLPMetricExporter(), export_interval_millis=15_000)
            metrics.set_meter_provider(MeterProvider(resource=_resource(), metric_readers=[reader]))
            _instrument_libraries()
    if console:
        _provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    if memory and _exporter is None:
        _exporter = InMemorySpanExporter()
        _provider.add_span_processor(SimpleSpanProcessor(_exporter))
    return _exporter


def _instrument_libraries() -> None:
    """psycopg + PydanticAI auto-instrumentation (FastAPI is per app: see instrument_app)."""
    global _instrumented
    if _instrumented:
        return
    _instrumented = True
    try:
        from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor

        PsycopgInstrumentor().instrument(enable_commenter=False)
    except ImportError:  # the `otlp` extra isn't installed: tracing still works, just without SQL spans
        pass
    from pydantic_ai import Agent, InstrumentationSettings

    Agent.instrument_all(InstrumentationSettings(include_content=False))


def instrument_app(app: Any) -> None:
    """One span per HTTP request (route, status, duration) and the standard http.server.* metrics."""
    if not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    except ImportError:
        return
    # Health probes every few seconds would drown the real traffic in Jaeger. exclude_spans drops the per-chunk
    # "http send"/"receive" spans: a streamed copilot answer produced ~15 of them, burying the steps that matter.
    FastAPIInstrumentor.instrument_app(app, excluded_urls="health,ready", exclude_spans=["send", "receive"])


def tracer() -> trace.Tracer:
    return trace.get_tracer("agentops")


# --- Business metrics ----------------------------------------------------------------------------------------
# Created at import time: until a MeterProvider is set they're no-ops, so tests and offline runs pay nothing.
_meter = metrics.get_meter("agentops")
TRIAGES = _meter.create_counter("agentops.triage", description="Triaged messages, by outcome")
TRIAGE_DURATION = _meter.create_histogram("agentops.triage.duration", unit="ms", description="End-to-end triage time")
LLM_TOKENS = _meter.create_counter("agentops.llm.tokens", description="Model tokens, by model and direction")
LLM_COST = _meter.create_counter("agentops.llm.cost", unit="USD", description="Estimated model spend")
GUARDRAIL_BLOCKS = _meter.create_counter("agentops.guardrail.blocks", description="Requests stopped by a guardrail")
COPILOT_ANSWERS = _meter.create_counter("agentops.copilot.answers", description="Copilot answers, by who produced them")
COPILOT_TTFT = _meter.create_histogram("agentops.copilot.ttft", unit="ms", description="Copilot time to first token")
APPROVAL_DECISIONS = _meter.create_counter("agentops.approval.decisions", description="Human approval decisions")
APPROVAL_ESCALATIONS = _meter.create_counter("agentops.approval.escalations", description="SLA escalations")
