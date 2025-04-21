/*load-tester.js*/
const axios = require('axios');

// Configuration
const API_BASE_URL = process.env.API_URL || 'http://app:8080'; // Use the service name in Docker
const REQUEST_INTERVAL_MS = 500; // Send a request every 500ms
const TOTAL_DURATION_MS = 60000; // Run for 60 seconds
const endpoints = [
  '/rolldice',
  '/health',
  // Add a non-existent endpoint to generate some errors
  '/nonexistent'
];

// Track statistics
let stats = {
  totalRequests: 0,
  successfulRequests: 0,
  failedRequests: 0,
  startTime: Date.now()
};

// Function to make a request to a random endpoint
async function makeRequest() {
  // Pick a random endpoint
  const endpoint = endpoints[Math.floor(Math.random() * endpoints.length)];
  const url = `${API_BASE_URL}${endpoint}`;
  
  console.log(`Making request to: ${url}`);
  
  try {
    stats.totalRequests++;
    const response = await axios.get(url, { timeout: 5000 });
    stats.successfulRequests++;
    console.log(`Success: ${url} - Status: ${response.status}`);
  } catch (error) {
    stats.failedRequests++;
    if (error.response) {
      console.log(`Error: ${url} - Status: ${error.response.status}`);
    } else {
      console.log(`Error: ${url} - ${error.message}`);
    }
  }
}

// Function to print statistics
function printStats() {
  const runningTime = (Date.now() - stats.startTime) / 1000;
  console.log('\n--- Load Test Statistics ---');
  console.log(`Running time: ${runningTime.toFixed(2)} seconds`);
  console.log(`Total requests: ${stats.totalRequests}`);
  console.log(`Successful requests: ${stats.successfulRequests}`);
  console.log(`Failed requests: ${stats.failedRequests}`);
  console.log(`Requests per second: ${(stats.totalRequests / runningTime).toFixed(2)}`);
  console.log('---------------------------\n');
}

// Start the load test
console.log('Starting load test...');

// Set up the periodic request interval
const intervalId = setInterval(makeRequest, REQUEST_INTERVAL_MS);

// Set up periodic stats printing
const statsIntervalId = setInterval(printStats, 5000);

// Set a timeout to stop the test after the specified duration
setTimeout(() => {
  clearInterval(intervalId);
  clearInterval(statsIntervalId);
  printStats();
  console.log('Load test complete.');
}, TOTAL_DURATION_MS);

// Make the first request immediately
makeRequest(); 