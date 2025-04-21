#!/usr/bin/env python
import os
import time
import random
import logging
import socket
from datetime import datetime, timezone
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
import uvicorn
import uuid
import json
import requests
from elasticsearch import Elasticsearch, exceptions as es_exceptions
from logging.handlers import RotatingFileHandler

# OpenTelemetry imports
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource, SERVICE_NAMESPACE

# OpenTelemetry metrics
from opentelemetry.metrics import get_meter_provider, set_meter_provider
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# Define a minimal version of the severity number for our logs
class MySeverityNumber:
    UNSPECIFIED = 0
    TRACE = 1
    DEBUG = 5
    INFO = 9
    WARN = 13
    ERROR = 17
    FATAL = 21

# Get service configuration from environment variables
API_NAME = os.getenv("API_NAME", "generic")
API_ENVIRONMENT = os.getenv("API_ENVIRONMENT", "unknown")
API_URL = os.getenv("API_URL", "http://localhost:8000")
AVG_LATENCY = float(os.getenv("AVG_LATENCY", "0.3"))
ERROR_RATE = float(os.getenv("ERROR_RATE", "0.05"))
OTEL_COLLECTOR_ENDPOINT = os.getenv("OTEL_COLLECTOR_ENDPOINT", "http://localhost:4318/v1/traces")
ELASTICSEARCH_URL = os.getenv("ELASTICSEARCH_URL", "http://elasticsearch:9200")  # Match docker-compose service name
LOG_FILE_PATH = os.getenv("LOG_FILE_PATH", f"logs/{API_NAME}_api.log")
ES_INDEX_PREFIX = os.getenv("ES_INDEX_PREFIX", "logs-otel")
ES_MAX_RETRIES = int(os.getenv("ES_MAX_RETRIES", "5"))
ES_RETRY_INTERVAL = int(os.getenv("ES_RETRY_INTERVAL", "5"))
ES_AUTO_FALLBACK = os.getenv("ES_AUTO_FALLBACK", "false").lower() == "true"  # Disabled by default

# Ensure log directory exists
os.makedirs(os.path.dirname(LOG_FILE_PATH), exist_ok=True)

# Configure file logging
file_handler = RotatingFileHandler(
    LOG_FILE_PATH,
    maxBytes=10_000_000,  # 10MB
    backupCount=5
)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

# Configure console logging
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

# Configure root logger
logging.basicConfig(
    level=logging.DEBUG,  # Change to DEBUG to see more logs
    handlers=[file_handler, console_handler]
)
logger = logging.getLogger(__name__)

# Helper function to resolve hostname
def resolve_hostname(hostname):
    """Try to resolve a hostname and return first IP address if possible"""
    try:
        return socket.gethostbyname(hostname)
    except socket.gaierror:
        return None

# Create a custom Elasticsearch logger (based on our standalone es_logger.py)
class ElasticsearchLogger:
    """Simple logger that writes logs to both console and Elasticsearch"""
    
    def __init__(self, 
                 es_url="http://elasticsearch:9200", 
                 index_name="logs-otel",
                 service_name="api-service", 
                 environment="default",
                 auto_fallback=False):
        """Initialize the Elasticsearch logger"""
        self.es_url = es_url
        self.index_name = index_name
        self.service_name = service_name
        self.environment = environment
        self.auto_fallback = auto_fallback
        self.es_client = None
        self.es_ready = False
        
        # Docker DNS to IP address resolution can take time
        # We'll use just the Docker service name with high retry settings
        logger.info(f"Initializing Elasticsearch logger with URL: {self.es_url}")
        
        # Try to connect to Elasticsearch with retries
        self._init_elasticsearch(max_retries=ES_MAX_RETRIES)
    
    def _init_elasticsearch(self, retry_count=0, max_retries=5):
        """Initialize connection to Elasticsearch with retry logic"""
        if retry_count >= max_retries:
            logger.error(f"Failed to connect to Elasticsearch at {self.es_url} after {max_retries} attempts")
            return False
        
        try:
            # Test if Elasticsearch is reachable
            try:
                logger.info(f"Attempt {retry_count+1}/{max_retries}: Connecting to Elasticsearch at {self.es_url}...")
                response = requests.get(f"{self.es_url}/_cluster/health", timeout=10)
                logger.info(f"Elasticsearch health response: {response.status_code} - {response.text[:100]}")
            except Exception as e:
                logger.warning(f"Elasticsearch health check failed: {e}. Will still try to connect with the client.")
            
            # Connect to Elasticsearch with longer timeouts for Docker networking
            self.es_client = Elasticsearch(
                self.es_url, 
                request_timeout=60,  # Longer timeout
                retry_on_timeout=True, 
                max_retries=3  # More retries
            )
            
            # Get cluster info
            es_info = self.es_client.info()
            logger.info(f"Connected to Elasticsearch at {self.es_url}, version: {es_info.get('version', {}).get('number', 'unknown')}")
            
            # Create index if it doesn't exist
            if not self.es_client.indices.exists(index=self.index_name):
                logger.info(f"Creating index {self.index_name}")
                self.es_client.indices.create(
                    index=self.index_name,
                    settings={
                        "number_of_shards": 1,
                        "number_of_replicas": 1
                    },
                    mappings={
                        "properties": {
                            "timestamp": {"type": "date"},
                            "message": {"type": "text"},
                            "severity": {"type": "keyword"},
                            "service": {"type": "keyword"},
                            "environment": {"type": "keyword"},
                            "attributes": {"type": "object", "dynamic": True}
                        }
                    }
                )
                logger.info(f"Successfully created index {self.index_name}")
            
            # Test indexing a document
            test_doc = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "message": f"Test document from {self.service_name} service startup",
                "severity": "INFO",
                "service": self.service_name,
                "environment": self.environment,
                "attributes": {"test": True}
            }
            
            # Try with forced refresh
            result = self.es_client.index(
                index=self.index_name, 
                document=test_doc,
                refresh="true"  # Force immediate refresh
            )
            logger.info(f"Test document indexed: {result}")
            
            # If we get here, connection is good
            self.es_ready = True
            logger.info(f"Successfully connected to Elasticsearch at {self.es_url}")
            return True
            
        except (es_exceptions.ConnectionError, es_exceptions.TransportError, requests.exceptions.RequestException) as e:
            logger.warning(f"Elasticsearch connection attempt {retry_count+1} failed: {e}")
            time.sleep(ES_RETRY_INTERVAL)  # Wait before retry
            return self._init_elasticsearch(retry_count + 1, max_retries)
            
        except Exception as e:
            logger.error(f"Unexpected error connecting to Elasticsearch: {str(e)}")
            return False
    
    def log(self, message, severity="INFO", attributes=None):
        """Log a message to Elasticsearch and console"""
        log_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()
        log_attrs = attributes or {}
        
        # Add some common fields
        log_attrs["log_id"] = log_id
        
        # Write to console log
        log_message = f"{message} - Attributes: {json.dumps(log_attrs)}"
        if severity.upper() == "INFO":
            logger.info(log_message)
        elif severity.upper() == "ERROR":
            logger.error(log_message)
        elif severity.upper() == "WARNING":
            logger.warning(log_message)
        
        # Send to Elasticsearch if available
        if self.es_client and self.es_ready:
            log_doc = {
                "timestamp": timestamp,
                "message": message,
                "severity": severity,
                "service": self.service_name,
                "environment": self.environment,
                "attributes": log_attrs
            }
            try:
                # Explicitly log the document we're sending
                logger.debug(f"Sending to Elasticsearch: {json.dumps(log_doc)}")
                
                # Index the document and capture the result
                # Add refresh=True to force immediate refresh
                result = self.es_client.index(
                    index=self.index_name, 
                    document=log_doc,
                    refresh="true"  # Force Elasticsearch to refresh the index immediately
                )
                
                # Log success at DEBUG level (won't clutter console in normal operation)
                if result and result.get('_id'):
                    logger.debug(f"Successfully indexed document with ID: {result.get('_id')}")
                else:
                    logger.warning(f"Document indexed but no ID returned: {result}")
                    
            except Exception as e:
                logger.error(f"Failed to send log to Elasticsearch: {e}")
                # Try to reconnect for future logs
                if "ConnectionError" in str(e) or "TransportError" in str(e):
                    self.es_ready = False
                    # We need to reconnect - set debug level to higher to see what's happening
                    logger.warning(f"Connection to Elasticsearch lost, attempting to reconnect")
                    self._init_elasticsearch()
        else:
            # Log if we have a client but it's not ready
            if self.es_client and not self.es_ready:
                logger.warning(f"Not sending to Elasticsearch: client exists but not ready")
            elif not self.es_client:
                logger.warning(f"Not sending to Elasticsearch: no client available")
                # Try to reconnect
                if not self._init_elasticsearch():
                    logger.error("Failed to reconnect to Elasticsearch")
    
    def close(self):
        """Close the Elasticsearch connection"""
        if self.es_client:
            self.es_client.close()
            logger.info("Elasticsearch connection closed")

# Add a debug log right before we create the ElasticsearchLogger to see environment variables
logger.info(f"Creating Elasticsearch logger with URL: {ELASTICSEARCH_URL}, index: {ES_INDEX_PREFIX}")
logger.info(f"Service name: {API_NAME}, environment: {API_ENVIRONMENT}")

# Initialize our custom Elasticsearch logger
es_logger = ElasticsearchLogger(
    es_url=ELASTICSEARCH_URL,
    index_name=ES_INDEX_PREFIX,
    service_name=API_NAME,
    environment=API_ENVIRONMENT,
    auto_fallback=ES_AUTO_FALLBACK
)

# Configure OpenTelemetry resource
resource = Resource(attributes={
    SERVICE_NAME: f"{API_NAME}-api",
    SERVICE_NAMESPACE: API_ENVIRONMENT,
    "environment": API_ENVIRONMENT,
    "api.name": API_NAME
})

# Set up trace provider (keep using OpenTelemetry for tracing)
tracer_provider = TracerProvider(resource=resource)
trace.set_tracer_provider(tracer_provider)

# Configure trace exporter
otlp_trace_exporter = OTLPSpanExporter(endpoint=OTEL_COLLECTOR_ENDPOINT)
tracer_provider.add_span_processor(BatchSpanProcessor(otlp_trace_exporter))

# Set up metrics provider (keep using OpenTelemetry for metrics)
metrics_endpoint = OTEL_COLLECTOR_ENDPOINT.replace("/traces", "/metrics")
metric_exporter = OTLPMetricExporter(endpoint=metrics_endpoint)
metric_reader = PeriodicExportingMetricReader(metric_exporter, export_interval_millis=15000)
meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
set_meter_provider(meter_provider)

# Get a tracer and meter
tracer = trace.get_tracer(__name__)
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

# Helper function for creating log records (now using our custom logger)
def create_log_record(message, severity, attributes=None):
    """Create a log record using our custom Elasticsearch logger"""
    try:
        # Use our custom logger
        es_logger.log(message, severity, attributes)
    except Exception as e:
        logger.error(f"Error creating log record: {e}")

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
    create_log_record(
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
            create_log_record(
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
        else:
            # Log the successful response
            create_log_record(
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
        create_log_record(
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
        create_log_record(
            f"Processing {span_name} operation with target latency {latency:.2f}s",
            "INFO",
            {
                "operation": span_name,
                "target_latency": latency,
                "api.name": API_NAME,
                "api.environment": API_ENVIRONMENT
            }
        )
        
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
            create_log_record(
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
        else:
            # Log the success
            create_log_record(
                f"Operation {span_name} completed successfully in {latency:.2f}s",
                "INFO",
                {
                    "operation": span_name,
                    "latency": latency,
                    "api.name": API_NAME,
                    "api.environment": API_ENVIRONMENT
                }
            )
            
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
        meter_provider.shutdown()
        # Close Elasticsearch connection
        es_logger.close()