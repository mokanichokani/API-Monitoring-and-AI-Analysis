from flask import Flask, jsonify
import random
import time
import logging

# Create Flask app
app = Flask(__name__)

# Configure logging (save logs to a file)
logging.basicConfig(
    filename='app_logs.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Endpoint 1: /status (always returns 200)
@app.route('/status', methods=['GET'])
def status():
    logging.info("Status endpoint hit")
    return jsonify({"status": "OK"}), 200


# Endpoint 2: /predict (random errors and variable response times)
@app.route('/predict', methods=['GET'])
def predict():
    response_time = random.uniform(0.1, 2.0)  # Simulate random response times
    time.sleep(response_time)  # Introduce artificial delay

    # Randomly generate errors (5% chance)
    if random.random() < 0.05:
        logging.error("Error occurred in predict endpoint")
        return jsonify({"error": "Something went wrong!"}), 500

    # Log normal request with response time
    logging.info(f"Predict endpoint hit. Response time: {response_time:.2f} seconds")
    return jsonify({"prediction": "Success", "response_time": f"{response_time:.2f} seconds"}), 200


# Run the Flask app
if __name__ == '__main__':
    app.run(debug=True, port=5000)
