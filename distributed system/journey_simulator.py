#!/usr/bin/env python
import os
import time
import random
import logging
import asyncio
import aiohttp
import uuid
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

# Get service configuration from environment variables
PAYMENT_API_URL = os.getenv("PAYMENT_API_URL", "http://payment-api:8000/process")
ORDER_API_URL = os.getenv("ORDER_API_URL", "http://order-api:8000/submit")
INVENTORY_API_URL = os.getenv("INVENTORY_API_URL", "http://inventory-api:8000/check")
USER_API_URL = os.getenv("USER_API_URL", "http://user-api:8000/profile")
OTEL_COLLECTOR_ENDPOINT = os.getenv("OTEL_COLLECTOR_ENDPOINT", "http://localhost:4318/v1/traces")

# Configure OpenTelemetry resource
resource = Resource(attributes={
    SERVICE_NAME: "journey-simulator",
    "monitoring.system": "otel-api-monitoring"
})

# Set up trace provider
tracer_provider = TracerProvider(resource=resource)
trace.set_tracer_provider(tracer_provider)

# Configure trace exporter
otlp_exporter = OTLPSpanExporter(endpoint=OTEL_COLLECTOR_ENDPOINT)
tracer_provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

# Get a tracer
tracer = trace.get_tracer(__name__)

# Define API journeys
journeys = [
    {
        "name": "user_login",
        "steps": [
            {"name": "get_user_profile", "url": USER_API_URL, "method": "GET"}
        ],
        "frequency": 0.4  # 40% of journeys
    },
    {
        "name": "checkout",
        "steps": [
            {"name": "get_user_profile", "url": USER_API_URL, "method": "GET"},
            {"name": "check_inventory", "url": INVENTORY_API_URL, "method": "GET"},
            {"name": "process_payment", "url": PAYMENT_API_URL, "method": "POST"},
            {"name": "submit_order", "url": ORDER_API_URL, "method": "POST"}
        ],
        "frequency": 0.2  # 20% of journeys
    },
    {
        "name": "browse_catalog",
        "steps": [
            {"name": "get_user_profile", "url": USER_API_URL, "method": "GET"},
            {"name": "check_inventory", "url": INVENTORY_API_URL, "method": "GET"}
        ],
        "frequency": 0.3  # 30% of journeys
    },
    {
        "name": "order_status",
        "steps": [
            {"name": "get_user_profile", "url": USER_API_URL, "method": "GET"},
            {"name": "check_order", "url": ORDER_API_URL, "method": "GET"}
        ],
        "frequency": 0.1  # 10% of journeys
    }
]

def select_journey():
    """Select a journey based on frequency weights"""
    r = random.random()
    cumulative = 0
    for journey in journeys:
        cumulative += journey["frequency"]
        if r <= cumulative:
            return journey
    return journeys[0]  # Fallback to first journey

async def call_api(session, step, journey_id, request_id, journey_name):
    """Make an API call with proper span context propagation"""
    method = step["method"]
    url = step["url"]
    
    headers = {
        "X-Request-ID": request_id,
        "X-Journey-ID": journey_id,
        "X-Journey-Name": journey_name,
        "X-Step-Name": step["name"]
    }
    
    try:
        if method == "GET":
            async with session.get(url, headers=headers) as response:
                response_json = await response.json()
                return response.status, response_json
        elif method == "POST":
            async with session.post(url, headers=headers, json={}) as response:
                response_json = await response.json()
                return response.status, response_json
    except Exception as e:
        logger.error(f"Error calling {url}: {str(e)}")
        return 500, {"error": str(e)}

async def execute_journey(journey):
    """Execute a full journey with proper tracing"""
    journey_name = journey["name"]
    journey_id = str(uuid.uuid4())
    request_id = str(uuid.uuid4())
    
    with tracer.start_as_current_span(f"journey_{journey_name}") as journey_span:
        journey_span.set_attribute("journey.id", journey_id)
        journey_span.set_attribute("journey.name", journey_name)
        journey_span.set_attribute("request.id", request_id)
        
        logger.info(f"Starting journey: {journey_name} (ID: {journey_id})")
        
        success_count = 0
        total_steps = len(journey["steps"])
        
        async with aiohttp.ClientSession() as session:
            for i, step in enumerate(journey["steps"]):
                step_name = step["name"]
                
                with tracer.start_as_current_span(f"journey_step_{step_name}") as step_span:
                    step_span.set_attribute("journey.id", journey_id)
                    step_span.set_attribute("journey.name", journey_name)
                    step_span.set_attribute("journey.step", i)
                    step_span.set_attribute("journey.step.name", step_name)
                    step_span.set_attribute("request.id", request_id)
                    
                    logger.info(f"Executing step {i+1}/{total_steps}: {step_name} for journey {journey_name}")
                    
                    status, response = await call_api(session, step, journey_id, request_id, journey_name)
                    
                    step_span.set_attribute("http.status_code", status)
                    
                    if 200 <= status < 300:
                        success_count += 1
                        logger.info(f"Step {step_name} completed successfully")
                    else:
                        logger.error(f"Step {step_name} failed with status {status}: {response}")
                        step_span.set_attribute("error", True)
                        step_span.set_attribute("error.message", str(response))
                        
                        # If a step fails, there might be a chance that subsequent steps will fail too
                        # This simulates dependency failures in a journey
                        if random.random() < 0.4 and i < total_steps - 1:
                            logger.warning(f"Dependency failure: {step_name} failure may affect subsequent steps")
                            step_span.set_attribute("caused.dependency.failure", True)
                    
                    # Add some delay between steps to make traces more realistic
                    await asyncio.sleep(random.uniform(0.1, 0.3))
        
        # Record success rate
        success_rate = success_count / total_steps
        journey_span.set_attribute("journey.success_rate", success_rate)
        
        # Add a journey health attribute based on success rate
        if success_rate == 1.0:
            health = "healthy"
        elif success_rate >= 0.7:
            health = "degraded"
        else:
            health = "critical"
            
        journey_span.set_attribute("journey.health", health)
        
        logger.info(f"Journey {journey_name} completed with success rate: {success_rate:.2f} (Health: {health})")
        
        return success_rate, health

async def run_simulation():
    """Run a continuous simulation of user journeys"""
    logger.info("Starting journey simulation")
    
    try:
        while True:
            # Simulate user load patterns
            current_hour = datetime.now().hour
            
            # Simulate higher traffic during business hours (8am-6pm)
            if 8 <= current_hour < 18:
                # More journeys during business hours
                num_concurrent_journeys = random.randint(3, 8)
                delay_between_batches = random.uniform(1.0, 3.0)
            else:
                # Fewer journeys outside business hours
                num_concurrent_journeys = random.randint(1, 3)
                delay_between_batches = random.uniform(2.0, 5.0)
                
            logger.info(f"Simulating {num_concurrent_journeys} concurrent journeys")
            
            # Select and execute multiple journeys concurrently
            selected_journeys = [select_journey() for _ in range(num_concurrent_journeys)]
            tasks = [execute_journey(journey) for journey in selected_journeys]
            
            # Wait for all journeys to complete
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Log a summary of results
            success_rates = [r[0] for r in results if isinstance(r, tuple)]
            if success_rates:
                avg_success_rate = sum(success_rates) / len(success_rates)
                logger.info(f"Batch completed. Average success rate: {avg_success_rate:.2f}")
            
            # Wait before starting the next batch
            logger.info(f"Waiting {delay_between_batches:.2f} seconds before next batch")
            await asyncio.sleep(delay_between_batches)
                
    except KeyboardInterrupt:
        logger.info("Journey simulation stopped")
    finally:
        # Ensure all spans are exported
        tracer_provider.shutdown()

if __name__ == "__main__":
    # Run the simulation
    try:
        asyncio.run(run_simulation())
    except KeyboardInterrupt:
        logger.info("Journey simulation stopped by user")
    except Exception as e:
        logger.error(f"Simulation failed: {str(e)}")
        raise 