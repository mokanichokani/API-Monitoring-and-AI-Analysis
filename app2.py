from flask import Flask, jsonify
import random
import time
import logging
import psutil  # To simulate CPU/memory usage logs

# Create Flask app
app = Flask(__name__)

# Configure logging (save logs to a file)
logging.basicConfig(
    filename='logs.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Simulate different anomaly patterns
API_ENDPOINTS = ['/status', '/predict', '/data', '/process']
ERROR_RATE_THRESHOLD = 0.1  # 10% error rate
HIGH_CPU_THRESHOLD = 80  # Simulated CPU anomaly threshold
HIGH_MEMORY_THRESHOLD = 70  # Simulated memory anomaly threshold


# Endpoint 1: /status (random response times, spike anomalies)
@app.route('/status', methods=['GET'])
def status():
    response_time = random.uniform(0.1, 2.5)  # Variable response time
    time.sleep(response_time)

    # Simulate occasional spikes in response time (10% chance)
    if random.random() < 0.1:
        logging.warning("Response time spike detected at /status endpoint!")
        response_time *= 3
        time.sleep(response_time)  # Introduce spike

    logging.info(f"Status endpoint hit. Response time: {response_time:.2f} seconds")
    return jsonify({"status": "OK", "response_time": f"{response_time:.2f} seconds"}), 200


# Endpoint 2: /predict (random errors and CPU/memory anomalies)
@app.route('/predict', methods=['GET'])
def predict():
    response_time = random.uniform(0.1, 2.0)
    time.sleep(response_time)

    # Simulate CPU/memory anomalies
    cpu_usage = psutil.cpu_percent(interval=0.1) + random.uniform(-5, 5)
    memory_usage = psutil.virtual_memory().percent + random.uniform(-3, 5)
    
    # Randomly trigger high CPU or memory anomaly logs
    if cpu_usage > HIGH_CPU_THRESHOLD:
        logging.error(f"High CPU usage anomaly detected: {cpu_usage:.2f}%")
    if memory_usage > HIGH_MEMORY_THRESHOLD:
        logging.error(f"High Memory usage anomaly detected: {memory_usage:.2f}%")
    
    # Random error generation (10% chance)
    if random.random() < 0.1:
        logging.error("Error occurred in predict endpoint")
        return jsonify({"error": "Something went wrong!"}), 500

    # Log normal request with response time
    logging.info(f"Predict endpoint hit. CPU: {cpu_usage:.2f}%, Memory: {memory_usage:.2f}%, "
                 f"Response time: {response_time:.2f} seconds")
    return jsonify({"prediction": "Success", "response_time": f"{response_time:.2f} seconds"}), 200


# Endpoint 3: /data (Simulates high error rates and throughput anomalies)
@app.route('/data', methods=['GET'])
def data():
    # Random errors to simulate increased error rate
    if random.random() < ERROR_RATE_THRESHOLD:
        logging.error("Data endpoint error - simulated high error rate!")
        return jsonify({"error": "Data processing failure"}), 500

    # Log high throughput during simulated spikes
    for _ in range(random.randint(1, 3)):
        logging.info("Data endpoint hit - Simulated high request throughput")
    
    return jsonify({"data": "Here is some data"}), 200


# Endpoint 4: /process (Simulates multi-level errors and retry behavior)
@app.route('/process', methods=['GET'])
def process():
    response_time = random.uniform(0.1, 1.5)
    time.sleep(response_time)

    # Simulate cascading errors (retry logic)
    if random.random() < 0.05:
        logging.warning("Retrying request due to transient issue")
        response_time = random.uniform(0.1, 1.0)
        time.sleep(response_time)
        logging.info("Request retried successfully")

    if random.random() < 0.1:
        logging.error("Permanent failure in process endpoint!")
        return jsonify({"error": "Process failure"}), 500

    logging.info(f"Process endpoint hit. Response time: {response_time:.2f} seconds")
    return jsonify({"process": "Processing complete"}), 200


# Run the Flask app
if __name__ == '__main__':
    app.run(debug=True, port=5001)
