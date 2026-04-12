"""
FlowCore — OpenTelemetry Instrumentation Utility

Provides automatic logging and tracing export to SigNoz via OTLP.
Import this module at the top of your main.py to enable telemetry.

Example:
    import telemetry  # Must be first import
    import logging
    logger = logging.getLogger(__name__)
"""
import os
import logging
from typing import Optional

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_NAMESPACE, DEPLOYMENT_ENVIRONMENT, HOST_NAME
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry._logs import set_logger_provider

from opentelemetry.instrumentation.logging import LoggingInstrumentor


def setup_telemetry(
    service_name: str,
    otlp_endpoint: Optional[str] = None,
    log_level: int = logging.INFO
) -> trace.Tracer:
    """
    Configure OpenTelemetry tracing and logging for a FlowCore service.

    Args:
        service_name: Name of the service (e.g., "dcim-ingestion")
        otlp_endpoint: OTLP gRPC endpoint (defaults to env OTEL_EXPORTER_OTLP_ENDPOINT)
        log_level: Python logging level

    Returns:
        Tracer instance for creating custom spans
    """
    # Get configuration from environment
    endpoint = otlp_endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://signoz-otel-collector:4317")
    namespace = os.getenv("OTEL_SERVICE_NAMESPACE", "flowcore")
    environment = os.getenv("DEPLOYMENT_ENVIRONMENT", "development")
    host = os.getenv("HOSTNAME", os.getenv("HOST", "unknown"))

    # Create resource with service attributes
    resource = Resource.create({
        SERVICE_NAME: service_name,
        SERVICE_NAMESPACE: namespace,
        DEPLOYMENT_ENVIRONMENT: environment,
        HOST_NAME: host,
    })

    # ========== Tracing ==========
    tracer_provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(tracer_provider)

    # OTLP span exporter to SigNoz
    span_exporter = OTLPSpanExporter(
        endpoint=endpoint,
        insecure=True,  # Internal network
    )
    span_processor = BatchSpanProcessor(span_exporter)
    tracer_provider.add_span_processor(span_processor)

    # ========== Logging ==========
    logger_provider = LoggerProvider(resource=resource)
    set_logger_provider(logger_provider)

    # OTLP log exporter to SigNoz
    log_exporter = OTLPLogExporter(
        endpoint=endpoint,
        insecure=True,
    )
    log_processor = BatchLogRecordProcessor(log_exporter)
    logger_provider.add_log_record_processor(log_processor)

    # Configure Python logging to use OTel handler
    otel_handler = LoggingHandler(
        level=log_level,
        logger_provider=logger_provider,
    )
    otel_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(name)s %(levelname)s %(message)s"
    ))

    # Setup root logger
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=[otel_handler, logging.StreamHandler()]
    )

    # Auto-instrument logging calls
    LoggingInstrumentor().instrument()

    return tracer_provider.get_tracer(service_name)


def instrument_fastapi(app, tracer: Optional[trace.Tracer] = None):
    """
    Instrument a FastAPI app for automatic trace generation.

    Args:
        app: FastAPI application instance
        tracer: Optional tracer instance from setup_telemetry()
    """
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    FastAPIInstrumentor.instrument_app(app)


def get_tracer(name: str) -> trace.Tracer:
    """Get a tracer by name."""
    return trace.get_tracer(name)
