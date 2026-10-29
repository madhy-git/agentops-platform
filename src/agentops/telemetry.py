"""OpenTelemetry setup. Console exporter by default; in-memory exporter for tests;
OTLP (e.g. to Jaeger) when OTEL_EXPORTER_OTLP_ENDPOINT is set and the `otlp` extra is installed."""
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
            # Reads the endpoint from the env var itself; Batch so exporting never blocks a request.
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            _provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    if console:
        _provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    if memory:
        _exporter = InMemorySpanExporter()
        _provider.add_span_processor(SimpleSpanProcessor(_exporter))
    return _exporter


def tracer():
    return trace.get_tracer("agentops")
