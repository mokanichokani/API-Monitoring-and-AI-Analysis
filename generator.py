import requests
import random
import time

# Base URL of the Flask API
BASE_URL = "http://127.0.0.1:5001"

# List of available endpoints to hit
ENDPOINTS = ["/status", "/predict", "/data", "/process"]

# Function to hit an endpoint and log the result
def hit_endpoint(endpoint):
    try:
        response = requests.get(BASE_URL + endpoint)
        print(f"Hit {endpoint}: Status Code {response.status_code}, Response: {response.json()}")
    except Exception as e:
        print(f"Error hitting {endpoint}: {str(e)}")

# Main loop to hit endpoints and generate logs
def main():
    print("Starting to hit endpoints and generate logs...")

    for _ in range(100):  # Hit the endpoints 100 times (adjust as needed)
        endpoint = random.choice(ENDPOINTS)  # Pick a random endpoint to hit
        hit_endpoint(endpoint)
        
        # Random delay between 0.5 to 2.5 seconds to simulate real traffic
        time.sleep(random.uniform(0.5, 2.5))

    print("Finished hitting endpoints and generating logs.")

if __name__ == "__main__":
    main()
