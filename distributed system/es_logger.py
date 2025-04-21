#!/usr/bin/env python
"""
Simple Elasticsearch Logger Utility

This script provides a simple way to send logs to Elasticsearch.
It can be used standalone or imported into other Python applications.
"""

import os
import time
import json
import uuid
import logging
import argparse
import socket
from datetime import datetime, timezone
import requests
from elasticsearch import Elasticsearch, exceptions as es_exceptions

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def resolve_hostname(hostname):
    """Try to resolve a hostname and return first IP address if possible"""
    try:
        return socket.gethostbyname(hostname)
    except socket.gaierror:
        return None

class ElasticsearchLogger:
    """Simple logger that writes logs to both console and Elasticsearch"""
    
    def __init__(self, 
                 es_url="http://elasticsearch:9200", 
                 index_name="logs-otel",
                 service_name="es-logger", 
                 environment="default",
                 auto_fallback=True):
        """Initialize the Elasticsearch logger
        
        Args:
            es_url (str): Elasticsearch URL
            index_name (str): Name of the Elasticsearch index to write logs to
            service_name (str): Name of the service generating logs
            environment (str): Environment name (e.g., prod, dev, test)
            auto_fallback (bool): Whether to try localhost if container hostname fails
        """
        self.es_url = es_url
        self.index_name = index_name
        self.service_name = service_name
        self.environment = environment
        self.auto_fallback = auto_fallback
        self.es_client = None
        self.es_ready = False
        
        # Try to connect to Elasticsearch
        self._init_elasticsearch()
    
    def _init_elasticsearch(self, retry_count=0, max_retries=3, fallback_attempted=False):
        """Initialize connection to Elasticsearch with retry logic"""
        if retry_count >= max_retries:
            # If we've tried the max retries and auto_fallback is enabled,
            # and we haven't tried the fallback yet, try localhost
            if self.auto_fallback and not fallback_attempted and "elasticsearch" in self.es_url:
                logger.warning(f"Failed to connect to {self.es_url}, trying localhost fallback")
                # Switch to localhost
                self.es_url = self.es_url.replace("elasticsearch", "localhost")
                # Reset retry count and try again with localhost
                return self._init_elasticsearch(0, max_retries, True)
            
            logger.error(f"Failed to connect to Elasticsearch after {max_retries} attempts")
            return False
        
        try:
            # Check if hostname is resolvable
            if "http://" in self.es_url:
                hostname = self.es_url.split("//")[1].split(":")[0]
                if hostname != "localhost" and not resolve_hostname(hostname):
                    logger.warning(f"Cannot resolve hostname: {hostname}")
                    if self.auto_fallback and not fallback_attempted:
                        logger.info(f"Trying localhost instead of {hostname}")
                        self.es_url = self.es_url.replace(hostname, "localhost")
                        return self._init_elasticsearch(0, max_retries, True)
            
            # Test if Elasticsearch is reachable
            try:
                response = requests.get(f"{self.es_url}/_cluster/health", timeout=8)
                logger.info(f"Elasticsearch health response: {response.status_code}")
            except Exception as e:
                logger.warning(f"Elasticsearch health check failed: {e}. Will still try to connect.")
            
            # Connect to Elasticsearch
            self.es_client = Elasticsearch(self.es_url, request_timeout=30, retry_on_timeout=True)
            
            # Get cluster info
            es_info = self.es_client.info()
            logger.info(f"Connected to Elasticsearch at {self.es_url}, version: {es_info.get('version', {}).get('number', 'unknown')}")
            
            # Create index if it doesn't exist
            if not self.es_client.indices.exists(index=self.index_name):
                logger.info(f"Creating index {self.index_name}")
                self.es_client.indices.create(
                    index=self.index_name,
                    settings={
                        "number_of_shards": 1,
                        "number_of_replicas": 1
                    },
                    mappings={
                        "properties": {
                            "timestamp": {"type": "date"},
                            "message": {"type": "text"},
                            "severity": {"type": "keyword"},
                            "service": {"type": "keyword"},
                            "environment": {"type": "keyword"},
                            "attributes": {"type": "object", "dynamic": True}
                        }
                    }
                )
                logger.info(f"Successfully created index {self.index_name}")
            
            # Test indexing a document
            test_doc = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "message": "Elasticsearch logger initialization test",
                "severity": "INFO",
                "service": self.service_name,
                "environment": self.environment,
                "attributes": {"test": True}
            }
            result = self.es_client.index(index=self.index_name, document=test_doc)
            logger.info(f"Test document indexed: {result}")
            
            self.es_ready = True
            return True
            
        except (es_exceptions.ConnectionError, es_exceptions.TransportError, requests.exceptions.RequestException) as e:
            logger.warning(f"Elasticsearch connection attempt {retry_count+1} failed: {e}")
            time.sleep(5)  # Wait before retry
            return self._init_elasticsearch(retry_count + 1, max_retries, fallback_attempted)
            
        except Exception as e:
            logger.error(f"Unexpected error connecting to Elasticsearch: {e}")
            return False
    
    def log(self, message, severity="INFO", attributes=None):
        """Log a message to Elasticsearch and console
        
        Args:
            message (str): The log message
            severity (str): Log severity (INFO, WARNING, ERROR)
            attributes (dict): Additional attributes to include in the log
        """
        log_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()
        log_attrs = attributes or {}
        
        # Add some common fields
        log_attrs["log_id"] = log_id
        
        # Write to console log
        log_message = f"{message} - Attributes: {json.dumps(log_attrs)}"
        if severity.upper() == "INFO":
            logger.info(log_message)
        elif severity.upper() == "ERROR":
            logger.error(log_message)
        elif severity.upper() == "WARNING":
            logger.warning(log_message)
        
        # Send to Elasticsearch if available
        if self.es_client and self.es_ready:
            log_doc = {
                "timestamp": timestamp,
                "message": message,
                "severity": severity,
                "service": self.service_name,
                "environment": self.environment,
                "attributes": log_attrs
            }
            try:
                self.es_client.index(index=self.index_name, document=log_doc)
            except Exception as e:
                logger.error(f"Failed to send log to Elasticsearch: {e}")
                # Try to reconnect for future logs
                if "ConnectionError" in str(e) or "TransportError" in str(e):
                    self.es_ready = False
                    self._init_elasticsearch()
    
    def close(self):
        """Close the Elasticsearch connection"""
        if self.es_client:
            self.es_client.close()
            logger.info("Elasticsearch connection closed")

def main():
    """Run as a standalone script to test logging to Elasticsearch"""
    parser = argparse.ArgumentParser(description="Simple Elasticsearch Logger")
    parser.add_argument("--es-url", default=os.getenv("ELASTICSEARCH_URL", "http://elasticsearch:9200"),
                       help="Elasticsearch URL")
    parser.add_argument("--index", default=os.getenv("ES_INDEX_PREFIX", "logs-otel"),
                       help="Elasticsearch index name")
    parser.add_argument("--service", default=os.getenv("API_NAME", "es-logger"),
                       help="Service name")
    parser.add_argument("--env", default=os.getenv("API_ENVIRONMENT", "test"),
                       help="Environment name")
    parser.add_argument("--message", default="Test log message",
                       help="Message to log")
    parser.add_argument("--count", type=int, default=1,
                       help="Number of logs to send")
    parser.add_argument("--severity", default="INFO", choices=["INFO", "WARNING", "ERROR"],
                       help="Log severity")
    parser.add_argument("--no-fallback", action="store_true",
                       help="Disable automatic fallback to localhost")
    
    args = parser.parse_args()
    
    # Create logger
    es_logger = ElasticsearchLogger(
        es_url=args.es_url,
        index_name=args.index,
        service_name=args.service,
        environment=args.env,
        auto_fallback=not args.no_fallback
    )
    
    try:
        # Generate and send logs
        for i in range(args.count):
            es_logger.log(
                message=f"{args.message} #{i+1}",
                severity=args.severity,
                attributes={
                    "count": i+1,
                    "total": args.count,
                    "timestamp_ms": int(time.time() * 1000)
                }
            )
            if args.count > 1:
                time.sleep(0.1)  # Small delay between logs if sending multiple
        
        logger.info(f"Successfully sent {args.count} log(s) to Elasticsearch")
    finally:
        es_logger.close()

if __name__ == "__main__":
    main() 