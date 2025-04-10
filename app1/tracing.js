const { NodeSDK } = require('@opentelemetry/sdk-node');
const { getNodeAutoInstrumentations } = require('@opentelemetry/auto-instrumentations-node');
const { OTLPTraceExporter } = require('@opentelemetry/exporter-otlp-http');
const { OTLPMetricExporter } = require('@opentelemetry/exporter-otlp-http');
const { PeriodicExportingMetricReader } = require('@opentelemetry/sdk-metrics');
const { Resource } = require('@opentelemetry/resources');

const { SemanticResourceAttributes } = require('@opentelemetry/semantic-conventions');

// Define a shared resource
const resource = new Resource({
  [SemanticResourceAttributes.SERVICE_NAME]: 'app1-service',
});

// Metric setup
const metricReader = new PeriodicExportingMetricReader({
  exporter: new OTLPMetricExporter({ url: 'http://localhost:4318/v1/metrics' }),
  exportIntervalMillis: 1000,
});

// Tracing setup
const sdk = new NodeSDK({
  traceExporter: new OTLPTraceExporter({
    url: 'http://localhost:4318/v1/traces',
  }),
  resource,
  metricReader,  // Add metrics reader to SDK directly
  instrumentations: [getNodeAutoInstrumentations()],
});

(async () => {
  try {
    await sdk.start();
    console.log('✅ OpenTelemetry tracing and metrics initialized');
  } catch (err) {
    console.error('❌ Error initializing telemetry:', err);
  }
})();
