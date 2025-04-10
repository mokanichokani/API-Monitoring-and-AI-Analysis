const pino = require('pino');

const transport = pino.transport({
  target: 'pino/file', // fallback to local file
  options: { destination: './logs/app.log' }
});

// Optionally send logs to OTEL via OTLP HTTP exporter (if you want real logs in Elasticsearch)
const logger = pino({
  timestamp: pino.stdTimeFunctions.isoTime,
}, transport);

module.exports = logger;
