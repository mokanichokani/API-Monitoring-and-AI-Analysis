#!/usr/bin/env python
import logging
import time
import random
from datetime import datetime

# OpenTelemetry imports
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configure OpenTelemetry resource
resource = Resource(attributes={
    SERVICE_NAME: "otel-elasticsearch-demo"
})

# Set up the trace provider
tracer_provider = TracerProvider(resource=resource)
trace.set_tracer_provider(tracer_provider)

# Configure trace exporter to send traces to OpenTelemetry Collector using HTTP
otlp_trace_exporter = OTLPSpanExporter(
    # HTTP endpoint for the collector
    endpoint="http://localhost:4318/v1/traces"
)

# Add the trace exporter to the tracer provider
tracer_provider.add_span_processor(BatchSpanProcessor(otlp_trace_exporter))

# Get a tracer
tracer = trace.get_tracer(__name__)

def simulate_api_call():
    """Simulate an API call with random latency"""
    with tracer.start_as_current_span("api_call") as span:
        # Add some attributes to the span
        span.set_attribute("http.method", "GET")
        span.set_attribute("http.url", "https://api.example.com/data")
        
        # Log the start of the API call
        logger.info(f"Making API call at {datetime.now().isoformat()}")
        
        # Simulate API latency
        latency = random.uniform(0.1, 2.0)
        span.set_attribute("latency_seconds", latency)
        
        # Simulate random errors
        if random.random() < 0.1:  # 10% chance of error
            span.set_attribute("error", True)
            span.set_attribute("error.type", "timeout")
            error_msg = f"API call failed with timeout after {latency:.2f} seconds"
            logger.error(error_msg)
            return False
        
        # Simulate processing time
        time.sleep(latency)
        
        # Log success
        success_msg = f"API call completed successfully in {latency:.2f} seconds"
        logger.info(success_msg)
        return True

def main():
    """Main application loop"""
    logger.info("Starting OpenTelemetry to Elasticsearch demo application")
    
    try:
        while True:
            # Create a parent span for the entire operation
            with tracer.start_as_current_span("process_data") as parent_span:
                # Add some context to the parent span
                process_id = random.randint(1000, 9999)
                timestamp = datetime.now().isoformat()
                parent_span.set_attribute("process_id", process_id)
                parent_span.set_attribute("timestamp", timestamp)
                
                logger.info(f"Starting process {process_id}")
                
                # Simulate multiple API calls in a single process
                num_calls = random.randint(1, 5)
                success_count = 0
                
                for i in range(num_calls):
                    # Create child spans for each API call
                    with tracer.start_as_current_span(f"call_{i}") as child_span:
                        child_span.set_attribute("call_number", i)
                        
                        logger.info(f"Making API call {i} for process {process_id}")
                        
                        if simulate_api_call():
                            success_count += 1
                
                # Record success rate in the parent span
                success_rate = success_count / num_calls
                parent_span.set_attribute("success_rate", success_rate)
                
                logger.info(f"Process {process_id} completed with success rate: {success_rate:.2f}")
                
                # Wait between process runs
                time.sleep(random.uniform(1.0, 5.0))
    
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
    finally:
        # Shutdown the providers
        tracer_provider.shutdown()

if __name__ == "__main__":
    main() 