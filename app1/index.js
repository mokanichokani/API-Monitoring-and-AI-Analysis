// app.js
const { NodeSDK } = require('@opentelemetry/sdk-node');
const { OTLPTraceExporter } = require('@opentelemetry/exporter-trace-otlp-http');
const { OTLPMetricExporter } = require('@opentelemetry/exporter-metrics-otlp-http');
const { OTLPLogExporter } = require('@opentelemetry/exporter-logs-otlp-http');
const { getNodeAutoInstrumentations } = require('@opentelemetry/auto-instrumentations-node');
const { Resource } = require('@opentelemetry/resources');
const { SemanticResourceAttributes } = require('@opentelemetry/semantic-conventions');
const { PeriodicExportingMetricReader } = require('@opentelemetry/sdk-metrics');
const { LoggerProvider, SimpleLogRecordProcessor } = require('@opentelemetry/sdk-logs');
const { logs } = require('@opentelemetry/api-logs');
const express = require('express');

// Create a resource that identifies our service
const resource = Resource.create({
  [SemanticResourceAttributes.SERVICE_NAME]: 'demo-service',
  [SemanticResourceAttributes.SERVICE_VERSION]: '1.0.0',
});

// Rest of the code remains the same...

// Configure OpenTelemetry SDK
const sdk = new NodeSDK({
  resource,
  traceExporter: new OTLPTraceExporter({
    url: 'http://localhost:4318/v1/traces',
  }),
  metricReader: new PeriodicExportingMetricReader({
    exporter: new OTLPMetricExporter({
      url: 'http://localhost:4318/v1/metrics',
    }),
    exportIntervalMillis: 1000,
  }),
  instrumentations: [getNodeAutoInstrumentations()],
});

// Configure Logger for OpenTelemetry Logs
const loggerProvider = new LoggerProvider({ resource });
loggerProvider.addLogRecordProcessor(
  new SimpleLogRecordProcessor(
    new OTLPLogExporter({
      url: 'http://localhost:4318/v1/logs',
    })
  )
);
logs.setGlobalLoggerProvider(loggerProvider);
const logger = logs.getLogger('demo-logger');

// Start the SDK
sdk.start().then(() => {
  console.log('SDK started successfully');
  
  // Create Express app after OpenTelemetry is initialized
  const app = express();
  const PORT = 3000;

  // Endpoint that generates trace, metrics, and logs
  app.get('/', (req, res) => {
    // Log something
    logger.emit({
      severityText: 'INFO',
      body: 'Request received at root endpoint',
      attributes: { httpMethod: 'GET', path: '/' }
    });
    
    // Simulate some work
    const randomDelay = Math.floor(Math.random() * 200);
    setTimeout(() => {
      // Log the result
      logger.emit({
        severityText: 'INFO',
        body: `Request processed in ${randomDelay}ms`,
        attributes: { processingTime: randomDelay }
      });
      res.send('Hello from OpenTelemetry demo!');
    }, randomDelay);
  });

  // Error endpoint to demonstrate error logging
  app.get('/error', (req, res) => {
    logger.emit({
      severityText: 'ERROR',
      body: 'An error occurred',
      attributes: { errorType: 'demo_error' }
    });
    res.status(500).send('Something went wrong');
  });

  app.listen(PORT, () => {
    console.log(`Server running at http://localhost:${PORT}`);
  });
});

// Graceful shutdown
process.on('SIGTERM', () => {
  sdk.shutdown()
    .then(() => console.log('SDK shut down successfully'))
    .catch((error) => console.log('Error shutting down SDK', error))
    .finally(() => process.exit(0));
});