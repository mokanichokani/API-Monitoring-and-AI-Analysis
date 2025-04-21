/*instrumentation.js*/
// Require dependencies
const { NodeSDK } = require('@opentelemetry/sdk-node');
const { resourceFromAttributes } = require('@opentelemetry/resources');
const { ATTR_SERVICE_NAME, ATTR_SERVICE_VERSION, ATTR_DEPLOYMENT_ENVIRONMENT } = require('@opentelemetry/semantic-conventions');
const { OTLPTraceExporter } = require('@opentelemetry/exporter-trace-otlp-http');
const { OTLPMetricExporter } = require('@opentelemetry/exporter-metrics-otlp-http');
const { OTLPLogExporter } = require('@opentelemetry/exporter-logs-otlp-proto');
const { PeriodicExportingMetricReader } = require('@opentelemetry/sdk-metrics');
const { MeterProvider } = require('@opentelemetry/sdk-metrics');
const { LoggerProvider, SimpleLogRecordProcessor } = require('@opentelemetry/sdk-logs');
const { getNodeAutoInstrumentations } = require('@opentelemetry/auto-instrumentations-node');
const { metrics, diag, DiagConsoleLogger, DiagLogLevel } = require('@opentelemetry/api');
const winston = require('winston');

// Enable diagnostic logging
diag.setLogger(new DiagConsoleLogger(), DiagLogLevel.INFO);

// Create resource
const resource = resourceFromAttributes({
  [ATTR_SERVICE_NAME]: 'api-monitoring-service',
  [ATTR_SERVICE_VERSION]: '1.0.0',
  [ATTR_DEPLOYMENT_ENVIRONMENT]: 'development'
});

// Configure OTLP exporters to send to OpenTelemetry Collector
const traceExporter = new OTLPTraceExporter({
  url: 'http://localhost:4318/v1/traces',
  headers: {}
});

const metricExporter = new OTLPMetricExporter({
  url: 'http://localhost:4318/v1/metrics',
  headers: {}
});

const logExporter = new OTLPLogExporter({
  url: 'http://localhost:4318/v1/logs',
  headers: {}
});

// Initialize MeterProvider
const meterProvider = new MeterProvider({
  resource: resource,
});

// Add metric reader
meterProvider.addMetricReader(
  new PeriodicExportingMetricReader({
    exporter: metricExporter,
    exportIntervalMillis: 1000,
  })
);

// Set the global meter provider
metrics.setGlobalMeterProvider(meterProvider);

// Create a meter
const meter = metrics.getMeter('example-meter');

// Create some metrics
const requestCounter = meter.createCounter('http_requests_total', {
  description: 'Total number of HTTP requests',
});

const requestDurationHistogram = meter.createHistogram('http_request_duration_seconds', {
  description: 'HTTP request duration in seconds',
  unit: 's',
});

// Initialize LoggerProvider
const loggerProvider = new LoggerProvider({
  resource: resource,
});
loggerProvider.addLogRecordProcessor(new SimpleLogRecordProcessor(logExporter));

// Configure Winston logger with custom OpenTelemetry transport
const logger = winston.createLogger({
  level: 'info',
  format: winston.format.combine(
    winston.format.timestamp(),
    winston.format.json()
  ),
  defaultMeta: { service: 'api-monitoring-service' },
  transports: [
    new winston.transports.Console(),
    // Log to console for debugging purposes
  ]
});

// Create a custom Winston logger that also logs to OpenTelemetry
// Wrap the Winston logger methods to send logs to OTel
const originalLoggerMethods = {
  info: logger.info,
  warn: logger.warn,
  error: logger.error,
  debug: logger.debug,
};

// Wrap Winston logger methods to also send logs to OpenTelemetry
['info', 'warn', 'error', 'debug'].forEach(level => {
  logger[level] = function(message, meta) {
    // Call the original Winston method
    originalLoggerMethods[level].call(logger, message, meta);
    
    // Also log to OpenTelemetry
    const otelLogger = loggerProvider.getLogger('winston-logger');
    otelLogger.emit({
      severityText: level,
      body: message,
      attributes: meta || {}
    });
  };
});

// Initialize and start the OpenTelemetry SDK
const sdk = new NodeSDK({
  resource: resource,
  traceExporter,
  metricReader: new PeriodicExportingMetricReader({
    exporter: metricExporter,
    exportIntervalMillis: 1000,
  }),
  instrumentations: [getNodeAutoInstrumentations()]
});

// Export the logger for use in the application
module.exports = {
  logger,
  sdk,
  metrics: {
    requestCounter,
    requestDurationHistogram
  }
};

sdk.start();
