"""OpenTelemetry setup. Console exporter by default; in-memory exporter for tests."""
from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

_exporter: InMemorySpanExporter | None = None
_provider: TracerProvider | None = None


def init(console: bool = False, memory: bool = False) -> InMemorySpanExporter | None:
    global _exporter, _provider
    if _provider is None:
        _provider = TracerProvider()
        trace.set_tracer_provider(_provider)
    if console:
        _provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    if memory:
        _exporter = InMemorySpanExporter()
        _provider.add_span_processor(SimpleSpanProcessor(_exporter))
    return _exporter


def tracer():
    return trace.get_tracer("agentops")
