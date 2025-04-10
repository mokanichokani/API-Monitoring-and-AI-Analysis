# app.py
from flask import Flask
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
import logging
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
import random
import time

# Configure resource
resource = Resource.create({
    "service.name": "flask-demo-service",
    "service.version": "1.0.0",
    "deployment.environment": "development"
})

# Configure tracing
tracer_provider = TracerProvider(resource=resource)
otlp_trace_exporter = OTLPSpanExporter(endpoint="http://localhost:4318/v1/traces")
tracer_provider.add_span_processor(BatchSpanProcessor(otlp_trace_exporter))
trace.set_tracer_provider(tracer_provider)
tracer = trace.get_tracer(__name__)

# Configure metrics
metric_reader = PeriodicExportingMetricReader(
    OTLPMetricExporter(endpoint="http://localhost:4318/v1/metrics")
)
metric_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
metrics.set_meter_provider(metric_provider)
meter = metrics.get_meter(__name__)

# Create metrics
request_counter = meter.create_counter(
    name="request_counter",
    description="Counts the number of requests",
    unit="1"
)

request_duration = meter.create_histogram(
    name="request_duration",
    description="Duration of requests",
    unit="ms"
)

# Configure logging
logger_provider = LoggerProvider(resource=resource)
otlp_log_exporter = OTLPLogExporter(endpoint="http://localhost:4318/v1/logs")
logger_provider.add_log_record_processor(BatchLogRecordProcessor(otlp_log_exporter))

# Set up logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Create Flask app
app = Flask(__name__)

# Initialize automatic instrumentation with Flask
FlaskInstrumentor().instrument_app(app)
RequestsInstrumentor().instrument()

@app.route('/')
def hello():
    with tracer.start_as_current_span("hello-operation") as span:
        span.set_attribute("custom.attribute", "hello-value")
        
        logger.info("Processing request to root endpoint")
        
        start_time = time.time()
        time.sleep(random.uniform(0.1, 0.5))
        duration = (time.time() - start_time) * 1000
        
        request_counter.add(1, {"endpoint": "root"})
        request_duration.record(duration, {"endpoint": "root"})
        
        return "Hello, OpenTelemetry!"

@app.route('/error')
def error():
    logger.error("An error occurred in the error endpoint")
    request_counter.add(1, {"endpoint": "error"})
    
    with tracer.start_as_current_span("error-operation") as span:
        span.set_attribute("error", True)
        span.record_exception(Exception("Demo error"))
        return "Error occurred!", 500
    
@app.route('/compute')
def compute():
    with tracer.start_as_current_span("compute-operation") as span:
        span.set_attribute("operation.type", "compute")
        logger.info("Performing compute operation")

        start_time = time.time()
        result = sum(i * i for i in range(10000))
        duration = (time.time() - start_time) * 1000

        request_counter.add(1, {"endpoint": "compute"})
        request_duration.record(duration, {"endpoint": "compute"})

        return f"Computation result: {result}"

@app.route('/external-api')
def external_api():
    with tracer.start_as_current_span("external-api-operation") as span:
        import requests
        span.set_attribute("operation.type", "external-call")
        logger.info("Calling external API")

        start_time = time.time()
        try:
            response = requests.get("https://httpbin.org/get")
            duration = (time.time() - start_time) * 1000
            request_duration.record(duration, {"endpoint": "external-api"})
            request_counter.add(1, {"endpoint": "external-api"})
            return response.json()
        except Exception as e:
            span.record_exception(e)
            logger.error(f"External API call failed: {e}")
            return "Failed to fetch external data", 500

@app.route('/delay/<int:ms>')
def delay(ms):
    with tracer.start_as_current_span("delay-operation") as span:
        span.set_attribute("delay.ms", ms)
        logger.info(f"Delaying response for {ms}ms")

        start_time = time.time()
        time.sleep(ms / 1000)
        duration = (time.time() - start_time) * 1000

        request_counter.add(1, {"endpoint": "delay"})
        request_duration.record(duration, {"endpoint": "delay"})

        return f"Delayed for {ms} ms"

@app.route('/health')
def health():
    logger.info("Health check accessed")
    request_counter.add(1, {"endpoint": "health"})
    return {"status": "ok", "version": "1.0.0"}


if __name__ == '__main__':
    app.run(debug=True, port=5000)