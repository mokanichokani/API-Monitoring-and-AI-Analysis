const axios = require('axios');

const baseURL = 'http://127.0.0.1:5000'; // Flask app base URL

const endpoints = [
  '/',                // Root
  '/error',           // Error
  '/compute',         // CPU-bound task
  '/external-api',    // External API call
  '/delay/200',       // Delay endpoint
  '/health'           // Health check
];

const simulateTraffic = async () => {
  try {
    const endpoint = endpoints[Math.floor(Math.random() * endpoints.length)];
    const response = await axios.get(`${baseURL}${endpoint}`);
    console.log(`✅ Hit ${endpoint} → Status: ${response.status}`);
  } catch (err) {
    console.error(`❌ Error hitting endpoint: ${err.config?.url || ''} → ${err.message}`);
  }
};

// Hit a random endpoint every 3 seconds
setInterval(simulateTraffic, 3000);
