"""OpenTelemetry setup.

LEARNING NOTES
- A *trace* is one request's journey; *spans* are its steps (triage -> agent.run -> ...).
  Attributes on spans (model, tokens, cost, prompt version) answer "why was this slow/expensive?".
- Exporters decide where spans go: console (debugging), in-memory (tests assert on spans), or
  OTLP (any backend: Jaeger locally, Langfuse for LLM-focused views, X-Ray on AWS).
- BatchSpanProcessor for OTLP so exporting never blocks a request; SimpleSpanProcessor for tests
  so spans are visible immediately.
- Never put raw PII in span attributes. Only counts (pii.redactions) and redacted text.
"""

from __future__ import annotations

import os

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

_exporter: InMemorySpanExporter | None = None
_provider: TracerProvider | None = None


def init(console: bool = False, memory: bool = False) -> InMemorySpanExporter | None:
    global _exporter, _provider
    if _provider is None:
        _provider = TracerProvider(resource=Resource.create({"service.name": "agentops-platform"}))
        trace.set_tracer_provider(_provider)
        if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
            # Reads endpoint (and headers, e.g. Langfuse auth) from standard OTEL_* env vars.
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            _provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    if console:
        _provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    if memory and _exporter is None:
        _exporter = InMemorySpanExporter()
        _provider.add_span_processor(SimpleSpanProcessor(_exporter))
    return _exporter


def tracer() -> trace.Tracer:
    return trace.get_tracer("agentops")
