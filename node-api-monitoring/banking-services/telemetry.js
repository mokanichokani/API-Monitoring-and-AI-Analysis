/*telemetry.js*/
// Shared OpenTelemetry instrumentation for distributed banking services
const opentelemetry = require('@opentelemetry/api');
const { NodeSDK } = require('@opentelemetry/sdk-node');
const { W3CTraceContextPropagator } = require('@opentelemetry/core');
const { registerInstrumentations } = require('@opentelemetry/instrumentation');
const { HttpInstrumentation } = require('@opentelemetry/instrumentation-http');
const { ExpressInstrumentation } = require('@opentelemetry/instrumentation-express');
const { resourceFromAttributes } = require('@opentelemetry/resources');
const { SemanticResourceAttributes } = require('@opentelemetry/semantic-conventions');
const { OTLPTraceExporter } = require('@opentelemetry/exporter-trace-otlp-http');
const { OTLPMetricExporter } = require('@opentelemetry/exporter-metrics-otlp-http');
const { OTLPLogExporter } = require('@opentelemetry/exporter-logs-otlp-proto');
const { PeriodicExportingMetricReader, MeterProvider } = require('@opentelemetry/sdk-metrics');
const { LoggerProvider, SimpleLogRecordProcessor } = require('@opentelemetry/sdk-logs');
const winston = require('winston');
const ecsFormat = require('@elastic/ecs-winston-format');

// Configure the trace context propagator
const contextManager = require('@opentelemetry/context-async-hooks');
const { CompositePropagator } = require('@opentelemetry/core');
const { B3InjectEncoding, B3Propagator } = require('@opentelemetry/propagator-b3');

// Initialize a tracer and meter provider
function initTelemetry(serviceName, environment) {
  // Enable OpenTelemetry debug logging in development
  opentelemetry.diag.setLogger(new opentelemetry.DiagConsoleLogger(), opentelemetry.DiagLogLevel.INFO);

  // Define resource information
  const resource = resourceFromAttributes({
    [SemanticResourceAttributes.SERVICE_NAME]: serviceName,
    [SemanticResourceAttributes.SERVICE_VERSION]: '1.0.0',
    [SemanticResourceAttributes.DEPLOYMENT_ENVIRONMENT]: environment,
    'service.instance.id': `${serviceName}-${Math.random().toString(36).substring(2, 12)}`,
    'host.type': environment
  });

  // Configure OTLP exporters to send to OpenTelemetry Collector
  const traceExporter = new OTLPTraceExporter({
    url: 'http://otel-collector:4318/v1/traces', 
    headers: {}
  });

  const metricExporter = new OTLPMetricExporter({
    url: 'http://otel-collector:4318/v1/metrics',
    headers: {}
  });

  const logExporter = new OTLPLogExporter({
    url: 'http://otel-collector:4318/v1/logs',
    headers: {}
  });

  // Initialize MeterProvider
  const meterProvider = new MeterProvider({
    resource: resource,
    readers: [
      new PeriodicExportingMetricReader({
        exporter: metricExporter,
        exportIntervalMillis: 10000, // Export metrics every 10 seconds
      })
    ]
  });

  // Set the global MeterProvider
  opentelemetry.metrics.setGlobalMeterProvider(meterProvider);

  // Create a meter to use for instrumentation
  const meter = opentelemetry.metrics.getMeter(serviceName, '1.0.0');

  // Initialize LoggerProvider
  const loggerProvider = new LoggerProvider({
    resource: resource,
  });
  loggerProvider.addLogRecordProcessor(new SimpleLogRecordProcessor(logExporter));

  // Create a winston logger that includes trace context in logs
  const logger = winston.createLogger({
    level: 'info',
    format: ecsFormat({ 
      convertReqRes: true,
      apmIntegration: true
    }),
    defaultMeta: { 
      service: serviceName,
      environment: environment
    },
    transports: [
      new winston.transports.Console({
        format: winston.format.combine(
          winston.format.colorize(),
          winston.format.simple()
        )
      })
    ]
  });

  // Set up a custom formatter to include trace context
  const addTraceContext = winston.format((info) => {
    const span = opentelemetry.trace.getActiveSpan();
    if (span) {
      const context = span.spanContext();
      info.trace = {
        span_id: context.spanId,
        trace_id: context.traceId
      };
    }
    return info;
  });

  // Apply the formatter to the logger
  logger.format = winston.format.combine(
    addTraceContext(),
    logger.format
  );

  // Initialize the SDK with tracing
  const sdk = new NodeSDK({
    resource: resource,
    traceExporter: traceExporter,
    contextManager: new contextManager.AsyncHooksContextManager(),
    instrumentations: [
      new HttpInstrumentation(),
      new ExpressInstrumentation()
    ],
    // Use both W3C and B3 propagation for maximum compatibility
    textMapPropagator: new CompositePropagator({
      propagators: [
        new W3CTraceContextPropagator(),
        new B3Propagator({ injectEncoding: B3InjectEncoding.MULTI_HEADER })
      ],
    }),
  });

  // Start the SDK
  sdk.start();

  // Create metric instruments
  const requestCounter = meter.createCounter('bank.http_requests_total', {
    description: 'Total number of HTTP requests',
    unit: '1',
  });

  const requestDurationHistogram = meter.createHistogram('bank.http_request_duration_seconds', {
    description: 'HTTP request duration in seconds',
    unit: 's',
  });

  const transactionValueCounter = meter.createCounter('bank.transaction_value_total', {
    description: 'Total value of transactions processed',
    unit: 'USD',
  });

  const activeUsersGauge = meter.createUpDownCounter('bank.active_users', {
    description: 'Number of active users',
    unit: '1',
  });

  const errorCounter = meter.createCounter('bank.errors_total', {
    description: 'Total number of errors',
    unit: '1',
  });

  // Return all initialized components
  return {
    logger,
    meter,
    metrics: {
      requestCounter,
      requestDurationHistogram,
      transactionValueCounter,
      activeUsersGauge,
      errorCounter
    },
    sdk
  };
}

module.exports = {
  initTelemetry
}; 