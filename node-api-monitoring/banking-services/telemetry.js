/*telemetry.js*/
// Shared OpenTelemetry instrumentation for distributed banking services
const opentelemetry = require('@opentelemetry/api');
const { NodeSDK } = require('@opentelemetry/sdk-node');
const { W3CTraceContextPropagator } = require('@opentelemetry/core');
const { registerInstrumentations } = require('@opentelemetry/instrumentation');
const { HttpInstrumentation } = require('@opentelemetry/instrumentation-http');
const { ExpressInstrumentation } = require('@opentelemetry/instrumentation-express');
const { resourceFromAttributes } = require('@opentelemetry/resources');
const { SemanticResourceAttributes, ATTR_SERVICE_NAME, ATTR_SERVICE_VERSION, ATTR_DEPLOYMENT_ENVIRONMENT } = require('@opentelemetry/semantic-conventions');
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
  // Set default values if not provided
  serviceName = serviceName || 'bank-api';
  environment = environment || 'development';
  
  // Enable OpenTelemetry debug logging in development
  opentelemetry.diag.setLogger(new opentelemetry.DiagConsoleLogger(), opentelemetry.DiagLogLevel.INFO);

  // Define resource information
  const resource = resourceFromAttributes({
    [ATTR_SERVICE_NAME]: serviceName,
    [ATTR_SERVICE_VERSION]: '1.0.0',
    [ATTR_DEPLOYMENT_ENVIRONMENT]: environment,
    'service.name': 'bank-api', // Fix to match exactly what's in the collector config
    'service.instance.id': `${serviceName}-${Math.random().toString(36).substring(2, 12)}`,
    'host.type': environment
  });

  // Configure OTLP exporters to send to OpenTelemetry Collector
  const traceExporter = new OTLPTraceExporter({
    url: 'http://otel-collector:4318/v1/traces', 
    headers: {
      'X-Service-Name': serviceName // Add service name to headers
    }
  });

  const metricExporter = new OTLPMetricExporter({
    url: 'http://otel-collector:4318/v1/metrics',
    headers: {
      'X-Service-Name': serviceName
    }
  });

  const logExporter = new OTLPLogExporter({
    url: 'http://otel-collector:4318/v1/logs',
    headers: {
      'X-Service-Name': serviceName
    }
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
      // Console transport for local visibility
      new winston.transports.Console({
        format: winston.format.combine(
          winston.format.colorize(),
          winston.format.simple()
        )
      }),
      // Note: Logs are collected by the container runtime and visible via 'docker logs'
      // They appear in Prometheus metrics but are not directly indexed in Elasticsearch
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
      new HttpInstrumentation({
        // Add service name as an attribute to every span
        requestHook: (span) => {
          span.setAttribute('service.name', 'bank-api');
        }
      }),
      new ExpressInstrumentation({
        // Add service name as an attribute to every span
        requestHook: (span) => {
          span.setAttribute('service.name', 'bank-api');
        }
      })
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

  // Account service metrics
  const accountCounter = meter.createCounter('bank.accounts_total', {
    description: 'Total number of accounts created',
    unit: '1',
  });

  const accountStatusChangeCounter = meter.createCounter('bank.account_status_changes_total', {
    description: 'Total number of account status changes',
    unit: '1',
  });

  const insufficientFundsCounter = meter.createCounter('bank.insufficient_funds_total', {
    description: 'Total number of insufficient funds errors',
    unit: '1',
  });

  const transferProcessingTime = meter.createHistogram('bank.transfer_processing_time_seconds', {
    description: 'Transfer processing time in seconds',
    unit: 's',
  });

  const transferCounter = meter.createCounter('bank.transfers_total', {
    description: 'Total number of transfers',
    unit: '1',
  });

  const transferAmountSum = meter.createHistogram('bank.transfer_amount_dollars', {
    description: 'Transfer amounts in dollars',
    unit: 'USD',
  });

  const serviceCallDurationHistogram = meter.createHistogram('bank.service_call_duration_seconds', {
    description: 'Service call duration in seconds',
    unit: 's',
  });

  const serviceCallErrorCounter = meter.createCounter('bank.service_call_errors_total', {
    description: 'Total number of service call errors',
    unit: '1',
  });

  // Transaction service metrics
  const transactionProcessingTime = meter.createHistogram('bank.transaction_processing_time_seconds', {
    description: 'Transaction processing time in seconds',
    unit: 's',
  });

  const transactionCounter = meter.createCounter('bank.transactions_total', {
    description: 'Total number of transactions processed',
    unit: '1',
  });

  const transactionAmountSum = meter.createHistogram('bank.transaction_amount_dollars', {
    description: 'Transaction amounts in dollars',
    unit: 'USD',
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
      errorCounter,
      accountCounter,
      accountStatusChangeCounter,
      insufficientFundsCounter,
      transferProcessingTime,
      transferCounter,
      transferAmountSum,
      serviceCallDurationHistogram,
      serviceCallErrorCounter,
      transactionProcessingTime,
      transactionCounter,
      transactionAmountSum
    },
    sdk
  };
}

module.exports = {
  initTelemetry
}; 