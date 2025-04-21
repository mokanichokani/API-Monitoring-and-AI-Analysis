# API Monitoring System with OpenTelemetry and Elasticsearch

This project demonstrates how to use OpenTelemetry to collect metrics, logs, and traces from a Node.js API and send them to Elasticsearch using the OpenTelemetry Collector.

## Components

- **Node.js Express API**: A simple API that generates logs, metrics, and traces
- **OpenTelemetry SDK**: Collects telemetry data from the application
- **OpenTelemetry Collector**: Receives telemetry data and exports it to Elasticsearch
- **Elasticsearch**: Stores the telemetry data
- **Kibana**: Visualizes the telemetry data

## Prerequisites

- Node.js (v14 or later)
- Docker and Docker Compose

## Setup

1. Install the dependencies:

```bash
npm install
```

2. Start the OpenTelemetry Collector and Elasticsearch using Docker Compose:

```bash
docker-compose up -d
```

3. Start the Node.js application:

```bash
node index.js
```

## Testing the API

Once the application is running, you can test it by making requests to the following endpoints:

- Roll a dice: http://localhost:8080/rolldice
- Health check: http://localhost:8080/health

## Viewing the Telemetry Data

You can view the telemetry data in Kibana at http://localhost:5601.

1. Open Kibana and navigate to "Stack Management" > "Index Management"
2. You should see the following indices:
   - `api-monitoring-logs-*`: Contains the log data
   - `api-monitoring-metrics-*`: Contains the metric data
   - `api-monitoring-traces-*`: Contains the trace data

3. Create index patterns for these indices to visualize the data in Kibana's Discover view.

## Configuration Files

- `instrumentation.js`: Configures the OpenTelemetry SDK in the application
- `otel-collector-config.yaml`: Configures the OpenTelemetry Collector
- `docker-compose.yaml`: Sets up the required infrastructure

## Troubleshooting

If you encounter issues with the OpenTelemetry Collector, check the collector logs:

```bash
docker logs otel-collector
```

For Elasticsearch issues, check the Elasticsearch logs:

```bash
docker logs elasticsearch
``` 