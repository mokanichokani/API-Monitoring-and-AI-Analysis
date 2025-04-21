/*app.js*/
// Import OpenTelemetry instrumentation first
const { logger } = require('./instrumentation');
const express = require('express');

const PORT = parseInt(process.env.PORT || '8080');
const app = express();

function getRandomNumber(min, max) {
  return Math.floor(Math.random() * (max - min + 1) + min);
}

app.get('/rolldice', (req, res) => {
  const result = getRandomNumber(1, 6);
  logger.info('Dice rolled', { result, path: req.path, method: req.method });
  res.send(result.toString());
});

// Add a health check endpoint
app.get('/health', (req, res) => {
  logger.info('Health check', { status: 'OK', path: req.path, method: req.method });
  res.status(200).json({ status: 'OK' });
});

// Add error handling middleware
app.use((err, req, res, next) => {
  logger.error('Application error', { 
    error: err.message, 
    stack: err.stack,
    path: req.path,
    method: req.method
  });
  res.status(500).json({ error: 'Internal Server Error' });
});

app.listen(PORT, () => {
  logger.info(`Server started`, { port: PORT, url: `http://localhost:${PORT}` });
});
