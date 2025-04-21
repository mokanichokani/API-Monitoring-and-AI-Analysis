#!/usr/bin/env python
"""
Simple utility to list all Elasticsearch indices
"""

import argparse
import json
from elasticsearch import Elasticsearch

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="List all Elasticsearch indices")
    parser.add_argument("--es-url", default="http://localhost:9200", 
                        help="Elasticsearch URL (default: http://localhost:9200)")
    args = parser.parse_args()
    
    # Connect to Elasticsearch
    print(f"Connecting to Elasticsearch at {args.es_url}...")
    es = Elasticsearch(args.es_url, request_timeout=30)
    
    try:
        # Check if ES is responding
        health = es.cluster.health()
        print(f"Cluster health: {health.get('status')}")
        print(f"Number of nodes: {health.get('number_of_nodes')}")
        
        # Get indices
        indices = es.cat.indices(format="json")
        print("\nElasticsearch indices:")
        print("=====================")
        if not indices:
            print("No indices found.")
        else:
            # Sort indices by name
            indices.sort(key=lambda x: x.get('index', ''))
            
            # Print index information
            for idx in indices:
                index_name = idx.get('index', '')
                docs_count = idx.get('docs.count', '0')
                size = idx.get('store.size', '0')
                health = idx.get('health', '')
                print(f"- {index_name}")
                print(f"  Documents: {docs_count}")
                print(f"  Size: {size}")
                print(f"  Health: {health}")
                print("")
            
        # Get more detailed information about the logs-otel index
        if es.indices.exists(index="logs-otel"):
            print("\nDetails for logs-otel index:")
            print("============================")
            stats = es.indices.stats(index="logs-otel")
            print(f"Total docs: {stats['_all']['total']['docs']['count']}")
            print(f"Deleted docs: {stats['_all']['total']['docs']['deleted']}")
            
            # Get mappings
            mappings = es.indices.get_mapping(index="logs-otel")
            print("\nIndex mapping:")
            print(json.dumps(mappings, indent=2))
            
            # Get a sample document
            print("\nSample documents:")
            try:
                results = es.search(index="logs-otel", size=2)
                for hit in results['hits']['hits']:
                    print(f"Document ID: {hit['_id']}")
                    print(json.dumps(hit['_source'], indent=2))
                    print("")
            except Exception as e:
                print(f"Could not get sample documents: {e}")
        
    except Exception as e:
        print(f"Error connecting to Elasticsearch: {e}")
    finally:
        es.close()

if __name__ == "__main__":
    main() 