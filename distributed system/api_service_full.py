#!/usr/bin/env python
import os
import time
import random
import logging
from datetime import datetime
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
import uvicorn
import uuid

# OpenTelemetry imports
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource, SERVICE_NAMESPACE

# OpenTelemetry logs
from opentelemetry import _logs
from opentelemetry.sdk import _logs as logs_sdk
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter

# OpenTelemetry metrics
from opentelemetry.metrics import get_meter_provider, set_meter_provider
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Get service configuration from environment variables
API_NAME = os.getenv("API_NAME", "generic")
API_ENVIRONMENT = os.getenv("API_ENVIRONMENT", "unknown")
API_URL = os.getenv("API_URL", "http://localhost:8000")
AVG_LATENCY = float(os.getenv("AVG_LATENCY", "0.3"))
ERROR_RATE = float(os.getenv("ERROR_RATE", "0.05"))
OTEL_COLLECTOR_ENDPOINT = os.getenv("OTEL_COLLECTOR_ENDPOINT", "http://localhost:4318/v1/traces")

# Configure OpenTelemetry resource
resource = Resource(attributes={
    SERVICE_NAME: f"{API_NAME}-api",
    SERVICE_NAMESPACE: API_ENVIRONMENT,
    "environment": API_ENVIRONMENT,
    "api.name": API_NAME
})

# Set up trace provider
tracer_provider = TracerProvider(resource=resource)
trace.set_tracer_provider(tracer_provider)

# Configure trace exporter
otlp_trace_exporter = OTLPSpanExporter(endpoint=OTEL_COLLECTOR_ENDPOINT)
tracer_provider.add_span_processor(BatchSpanProcessor(otlp_trace_exporter))

# Set up logs provider
logger_provider = logs_sdk.LoggerProvider(resource=resource)
_logs.set_logger_provider(logger_provider)

# Configure logs exporter
logs_endpoint = OTEL_COLLECTOR_ENDPOINT.replace("/traces", "/logs")
otlp_log_exporter = OTLPLogExporter(endpoint=logs_endpoint)
logger_provider.add_log_record_processor(BatchLogRecordProcessor(otlp_log_exporter))

# Set up metrics provider
metrics_endpoint = OTEL_COLLECTOR_ENDPOINT.replace("/traces", "/metrics")
metric_exporter = OTLPMetricExporter(endpoint=metrics_endpoint)
metric_reader = PeriodicExportingMetricReader(metric_exporter, export_interval_millis=15000)
meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
set_meter_provider(meter_provider)

# Get a tracer, logger and meter
tracer = trace.get_tracer(__name__)
otel_logger = logger_provider.get_logger(__name__)
meter = get_meter_provider().get_meter(__name__)

# Create metrics
request_counter = meter.create_counter(
    name="api.request.count",
    description="Number of API requests",
    unit="1",
)

error_counter = meter.create_counter(
    name="api.request.errors",
    description="Number of API errors",
    unit="1",
)

latency_histogram = meter.create_histogram(
    name="api.request.duration",
    description="Duration of API requests",
    unit="s",
)

# Helper function for creating log records
def create_log_record(message, severity, attributes=None):
    try:
        if severity.upper() == "INFO":
            severity_num = logs_sdk.SeverityNumber.INFO
        elif severity.upper() == "ERROR":
            severity_num = logs_sdk.SeverityNumber.ERROR
        elif severity.upper() == "WARNING":
            severity_num = logs_sdk.SeverityNumber.WARN
        else:
            severity_num = logs_sdk.SeverityNumber.UNSPECIFIED
        
        return logs_sdk.LogRecord(
            timestamp=int(time.time() * 1_000_000_000),  # nanoseconds
            severity_number=severity_num,
            severity_text=severity,
            body=message,
            attributes=attributes or {}
        )
    except Exception as e:
        logger.error(f"Error creating log record: {e}")
        return None

# Create FastAPI app
app = FastAPI(title=f"{API_NAME.capitalize()} API")

@app.middleware("http")
async def add_api_attributes(request: Request, call_next):
    """Add API-specific attributes to the current span and record metrics"""
    start_time = time.time()
    
    # Get current span
    current_span = trace.get_current_span()
    current_span.set_attribute("api.name", API_NAME)
    current_span.set_attribute("api.environment", API_ENVIRONMENT)
    current_span.set_attribute("api.url", API_URL)
    
    # Add unique request ID that can be used to track the request across services
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    current_span.set_attribute("request.id", request_id)
    
    # Add journey context if provided
    journey_id = request.headers.get("X-Journey-ID")
    journey_name = request.headers.get("X-Journey-Name")
    step_name = request.headers.get("X-Step-Name")
    
    if journey_id:
        current_span.set_attribute("journey.id", journey_id)
        request.state.journey_id = journey_id
    
    if journey_name:
        current_span.set_attribute("journey.name", journey_name)
        request.state.journey_name = journey_name
        
    if step_name:
        current_span.set_attribute("journey.step.name", step_name)
        request.state.step_name = step_name
    
    # Log the request start
    log_record = create_log_record(
        f"Started {request.method} {request.url.path}",
        "INFO",
        {
            "http.method": request.method,
            "http.url": str(request.url),
            "request.id": request_id,
            "journey.id": journey_id,
            "journey.name": journey_name,
            "journey.step.name": step_name
        }
    )
    if log_record:
        otel_logger.emit(log_record)
    
    # Track request count in metrics
    attributes = {
        "api": API_NAME,
        "environment": API_ENVIRONMENT,
        "method": request.method,
        "path": request.url.path
    }
    request_counter.add(1, attributes)
    
    # Process the request
    try:
        response = await call_next(request)
        
        # Record the duration
        duration = time.time() - start_time
        latency_histogram.record(
            duration,
            {**attributes, "status_code": response.status_code}
        )
        
        # Count errors
        if response.status_code >= 500:
            error_counter.add(
                1, 
                {**attributes, "status_code": response.status_code, "error_type": "server_error"}
            )
            
            # Log the error
            log_record = create_log_record(
                f"Request failed with status {response.status_code}",
                "ERROR",
                {
                    "http.method": request.method,
                    "http.url": str(request.url),
                    "http.status_code": response.status_code,
                    "request.id": request_id,
                    "journey.id": journey_id,
                    "journey.name": journey_name,
                    "journey.step.name": step_name,
                    "duration": duration
                }
            )
            if log_record:
                otel_logger.emit(log_record)
        else:
            # Log the successful response
            log_record = create_log_record(
                f"Completed {request.method} {request.url.path} with status {response.status_code}",
                "INFO",
                {
                    "http.method": request.method,
                    "http.url": str(request.url),
                    "http.status_code": response.status_code,
                    "request.id": request_id,
                    "journey.id": journey_id,
                    "journey.name": journey_name,
                    "journey.step.name": step_name,
                    "duration": duration
                }
            )
            if log_record:
                otel_logger.emit(log_record)
        
        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id
        return response
        
    except Exception as e:
        # Record the error
        duration = time.time() - start_time
        error_counter.add(
            1, 
            {**attributes, "error_type": "exception", "exception.type": type(e).__name__}
        )
        
        # Log the exception
        log_record = create_log_record(
            f"Request failed with exception: {str(e)}",
            "ERROR",
            {
                "http.method": request.method,
                "http.url": str(request.url),
                "request.id": request_id,
                "journey.id": journey_id,
                "journey.name": journey_name,
                "journey.step.name": step_name,
                "exception.type": type(e).__name__,
                "exception.message": str(e),
                "duration": duration
            }
        )
        if log_record:
            otel_logger.emit(log_record)
        
        # Re-raise the exception
        raise

def simulate_processing(span_name):
    """Simulate API processing with controlled latency and errors"""
    with tracer.start_as_current_span(span_name) as span:
        # Add some more context
        span.set_attribute("api.processor", span_name)
        
        # Determine latency for this request
        # Occasionally have high latency
        if random.random() < 0.05:  # 5% chance of high latency
            latency = AVG_LATENCY * random.uniform(3.0, 10.0)
            span.set_attribute("latency.anomaly", True)
            span.set_attribute("latency.multiplier", latency / AVG_LATENCY)
        else:
            latency = AVG_LATENCY * random.uniform(0.7, 1.5)
        
        # Log the latency we're going to simulate
        logger.info(f"{API_NAME} API processing with latency: {latency:.2f}s")
        span.set_attribute("latency_seconds", latency)
        
        # Log the operation start
        log_record = create_log_record(
            f"Processing {span_name} operation with target latency {latency:.2f}s",
            "INFO",
            {
                "operation": span_name,
                "target_latency": latency,
                "api.name": API_NAME,
                "api.environment": API_ENVIRONMENT
            }
        )
        if log_record:
            otel_logger.emit(log_record)
        
        # Environment-specific issues
        env_error = False
        error_type = None
        error_message = None
        
        # Cloud: Occasional network issues
        if API_ENVIRONMENT == "cloud" and random.random() < 0.02:
            span.set_attribute("error", True)
            span.set_attribute("error.type", "network_timeout")
            span.set_attribute("error.message", "Network connection timed out")
            env_error = True
            error_type = "network_timeout"
            error_message = "Network connection timed out"
            
        # On-premise: Occasional resource constraints
        elif API_ENVIRONMENT == "on-premise" and random.random() < 0.03:
            span.set_attribute("error", True)
            span.set_attribute("error.type", "resource_exhausted")
            span.set_attribute("error.message", "Server resources exhausted")
            env_error = True
            error_type = "resource_exhausted"
            error_message = "Server resources exhausted"
            
        # Multi-cloud: Occasional configuration issues
        elif API_ENVIRONMENT == "multi-cloud" and random.random() < 0.015:
            span.set_attribute("error", True)
            span.set_attribute("error.type", "configuration_error")
            span.set_attribute("error.message", "Service configuration mismatch")
            env_error = True
            error_type = "configuration_error"
            error_message = "Service configuration mismatch"
            
        # Regular error rate for this API
        if not env_error and random.random() < ERROR_RATE:
            span.set_attribute("error", True)
            span.set_attribute("error.type", "internal_error")
            span.set_attribute("error.message", f"Internal error in {API_NAME} API")
            env_error = True
            error_type = "internal_error"
            error_message = f"Internal error in {API_NAME} API"
            
        # Simulate processing time
        time.sleep(latency)
        
        # Record metrics
        attributes = {
            "api": API_NAME,
            "environment": API_ENVIRONMENT,
            "operation": span_name
        }
        
        latency_histogram.record(latency, attributes)
        
        if env_error:
            error_counter.add(1, {
                **attributes,
                "error_type": error_type
            })
            
            # Log the error
            log_record = create_log_record(
                f"Operation {span_name} failed: {error_message}",
                "ERROR",
                {
                    "operation": span_name,
                    "error.type": error_type,
                    "error.message": error_message,
                    "latency": latency,
                    "api.name": API_NAME,
                    "api.environment": API_ENVIRONMENT
                }
            )
            if log_record:
                otel_logger.emit(log_record)
        else:
            # Log the success
            log_record = create_log_record(
                f"Operation {span_name} completed successfully in {latency:.2f}s",
                "INFO",
                {
                    "operation": span_name,
                    "latency": latency,
                    "api.name": API_NAME,
                    "api.environment": API_ENVIRONMENT
                }
            )
            if log_record:
                otel_logger.emit(log_record)
            
        return not env_error  # Return success/failure

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "api": API_NAME, "environment": API_ENVIRONMENT}

@app.get("/")
async def root(request: Request):
    """Root endpoint with API info"""
    return {
        "api": API_NAME,
        "environment": API_ENVIRONMENT,
        "request_id": request.state.request_id
    }

# Payment API specific endpoints
if API_NAME == "payment":
    @app.post("/process")
    async def process_payment(request: Request):
        success = simulate_processing("payment_processing")
        if success:
            return {"status": "success", "message": "Payment processed successfully", "request_id": request.state.request_id}
        else:
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": "Payment processing failed", "request_id": request.state.request_id}
            )

# Order API specific endpoints
elif API_NAME == "order":
    @app.post("/submit")
    async def submit_order(request: Request):
        success = simulate_processing("order_processing")
        if success:
            return {"status": "success", "message": "Order submitted successfully", "request_id": request.state.request_id}
        else:
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": "Order submission failed", "request_id": request.state.request_id}
            )

# Inventory API specific endpoints
elif API_NAME == "inventory":
    @app.get("/check")
    async def check_inventory(request: Request):
        success = simulate_processing("inventory_check")
        if success:
            return {"status": "success", "message": "Inventory checked successfully", "request_id": request.state.request_id}
        else:
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": "Inventory check failed", "request_id": request.state.request_id}
            )

# User API specific endpoints
elif API_NAME == "user":
    @app.get("/profile")
    async def get_profile(request: Request):
        success = simulate_processing("profile_retrieval")
        if success:
            return {"status": "success", "message": "User profile retrieved", "request_id": request.state.request_id}
        else:
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": "User profile retrieval failed", "request_id": request.state.request_id}
            )

# Instrument the FastAPI app
FastAPIInstrumentor.instrument_app(app)

if __name__ == "__main__":
    logger.info(f"Starting {API_NAME} API in {API_ENVIRONMENT} environment")
    try:
        uvicorn.run(app, host="0.0.0.0", port=8000)
    finally:
        # Shutdown the providers
        tracer_provider.shutdown()
        logger_provider.shutdown()
        meter_provider.shutdown() 