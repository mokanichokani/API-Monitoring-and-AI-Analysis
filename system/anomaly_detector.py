#!/usr/bin/env python
import pandas as pd
import numpy as np
from elasticsearch import Elasticsearch
import matplotlib.pyplot as plt
from sklearn.ensemble import IsolationForest
import argparse
import os
import time
from datetime import datetime, timedelta

def connect_to_elasticsearch(host='localhost', port=9200):
    """Connect to Elasticsearch"""
    try:
        es = Elasticsearch([f'http://{host}:{port}'])
        if es.ping():
            print(f"Connected to Elasticsearch at {host}:{port}")
            return es
        else:
            print("Failed to connect to Elasticsearch")
            return None
    except Exception as e:
        print(f"Error connecting to Elasticsearch: {e}")
        return None

def fetch_trace_data(es, index_name, time_range_hours=24, max_docs=10000):
    """Fetch trace data from Elasticsearch"""
    query = {
        "query": {
            "range": {
                "@timestamp": {
                    "gte": f"now-{time_range_hours}h"
                }
            }
        },
        "size": max_docs,
        "_source": [
            "@timestamp", 
            "EndTimestamp",
            "Name",
            "Attributes.*",
            "Resource.*",
            "Kind",
            "TraceId",
            "SpanId",
            "ParentSpanId",
            "TraceStatus"
        ]
    }
    
    try:
        print(f"Fetching data from index {index_name} for the last {time_range_hours} hours...")
        response = es.search(index=index_name, body=query)
        
        hit_count = len(response['hits']['hits'])
        print(f"Retrieved {hit_count} documents")
        
        return response
    except Exception as e:
        print(f"Error fetching data: {e}")
        return None

def process_trace_data(response):
    """Process the trace data into a pandas DataFrame"""
    data = []
    
    if not response or 'hits' not in response or 'hits' not in response['hits']:
        print("No data to process")
        return None
    
    print("Processing trace data...")
    
    # First, get a sample document to understand the structure
    if len(response['hits']['hits']) > 0:
        sample = response['hits']['hits'][0]['_source']
        print(f"Sample document keys: {list(sample.keys())}")
    
    api_call_spans = []
    process_data_spans = []
    call_spans = []
    
    # First pass - categorize spans
    for hit in response['hits']['hits']:
        source = hit['_source']
        span_name = source.get('Name', '')
        
        if span_name == 'api_call':
            api_call_spans.append(source)
        elif span_name == 'process_data':
            process_data_spans.append(source)
        elif span_name.startswith('call_'):
            call_spans.append(source)
    
    print(f"Found {len(api_call_spans)} api_call spans, {len(process_data_spans)} process_data spans, and {len(call_spans)} call_X spans")
    
    # Extract latency information
    for span in api_call_spans:
        try:
            # Calculate latency from timestamps if available
            start_time = datetime.fromisoformat(span.get('@timestamp', '').replace('Z', '+00:00'))
            end_time = datetime.fromisoformat(span.get('EndTimestamp', '').replace('Z', '+00:00'))
            
            # Calculate duration in seconds
            latency = (end_time - start_time).total_seconds()
            
            # Get associated trace and parent span info
            trace_id = span.get('TraceId', '')
            span_id = span.get('SpanId', '')
            parent_span_id = span.get('ParentSpanId', '')
            
            # Look for error attributes (in our app, we set error=true for failed calls)
            error = False
            error_type = None
            
            # Check for error indicators in all possible attribute fields
            for key, value in span.items():
                if key.startswith('Attributes.error'):
                    error = True
                if key.startswith('Attributes.error.type'):
                    error_type = value
            
            # Check if the span has a non-zero TraceStatus
            if span.get('TraceStatus', 0) != 0:
                error = True
            
            entry = {
                'timestamp': start_time,
                'latency': latency,
                'trace_id': trace_id,
                'span_id': span_id,
                'parent_span_id': parent_span_id,
                'error': 1 if error else 0,
                'error_type': error_type,
                'service': span.get('Resource.service.name', 'unknown')
            }
            
            # Add any other attributes we find
            for key, value in span.items():
                if key.startswith('Attributes.'):
                    attr_name = key.replace('Attributes.', '')
                    if attr_name not in entry:
                        entry[attr_name] = value
            
            data.append(entry)
        except Exception as e:
            print(f"Error processing span: {e}")
            continue
    
    if not data:
        # If we couldn't find api_call spans with latency, try to extract durations from all spans
        print("No api_call spans with latency found. Trying to extract duration from all spans...")
        for hit in response['hits']['hits']:
            source = hit['_source']
            try:
                # Calculate latency from timestamps if available
                if '@timestamp' in source and 'EndTimestamp' in source:
                    start_time = datetime.fromisoformat(source['@timestamp'].replace('Z', '+00:00'))
                    end_time = datetime.fromisoformat(source['EndTimestamp'].replace('Z', '+00:00'))
                    
                    # Calculate duration in seconds
                    latency = (end_time - start_time).total_seconds()
                    
                    entry = {
                        'timestamp': start_time,
                        'latency': latency,
                        'span_name': source.get('Name', 'unknown'),
                        'trace_id': source.get('TraceId', ''),
                        'error': 1 if source.get('TraceStatus', 0) != 0 else 0,
                        'service': source.get('Resource.service.name', 'unknown')
                    }
                    
                    # Add any other attributes we find
                    for key, value in source.items():
                        if key.startswith('Attributes.'):
                            attr_name = key.replace('Attributes.', '')
                            if attr_name not in entry:
                                entry[attr_name] = value
                    
                    data.append(entry)
            except Exception as e:
                print(f"Error processing span: {e}")
                continue
    
    if not data:
        print("No usable latency data found in the response")
        return None
    
    # Convert to DataFrame
    df = pd.DataFrame(data)
    
    print(f"Processed {len(df)} data points with latency information")
    
    if len(df) > 0:
        print(f"Data columns: {df.columns.tolist()}")
        print(f"Latency statistics: Min={df['latency'].min():.4f}s, Max={df['latency'].max():.4f}s, Avg={df['latency'].mean():.4f}s")
    
    return df

def detect_latency_anomalies(df, contamination=0.05):
    """Detect anomalies in API latency"""
    if df is None or len(df) == 0 or 'latency' not in df.columns:
        print("No latency data available for anomaly detection")
        return df
    
    print("Detecting latency anomalies...")
    
    # Reshape for sklearn
    X = df[['latency']].values
    
    # Train isolation forest
    model = IsolationForest(contamination=contamination, random_state=42)
    df['latency_anomaly'] = model.fit_predict(X)
    
    # -1 indicates anomaly, convert to 0/1 for clarity
    df['latency_anomaly'] = df['latency_anomaly'].map({1: 0, -1: 1})
    
    anomaly_count = df['latency_anomaly'].sum()
    print(f"Found {anomaly_count} latency anomalies out of {len(df)} data points")
    
    return df

def detect_error_rate_anomalies(df, window='5min', threshold=0.2):
    """Detect anomalies in error rates"""
    if df is None or len(df) == 0 or 'error' not in df.columns or 'timestamp' not in df.columns:
        print("No error data available for anomaly detection")
        return df
    
    print("Detecting error rate anomalies...")
    
    # Calculate error rate over time
    df_resampled = df.set_index('timestamp').resample(window).agg({
        'error': 'mean'  # This gives us error rate in each window
    }).reset_index()
    
    # Mark windows with high error rates as anomalies
    df_resampled['error_rate_anomaly'] = (df_resampled['error'] > threshold).astype(int)
    
    # Merge back to original dataframe
    df_resampled = df_resampled.rename(columns={'error': 'window_error_rate'})
    df = pd.merge_asof(df.sort_values('timestamp'), 
                        df_resampled.sort_values('timestamp'),
                        on='timestamp',
                        direction='backward')
    
    anomaly_count = df['error_rate_anomaly'].sum()
    print(f"Found {anomaly_count} error rate anomalies based on a threshold of {threshold}")
    
    return df

def visualize_anomalies(df, output_dir='./'):
    """Create visualizations of the detected anomalies"""
    if df is None or len(df) == 0:
        print("No data to visualize")
        return
    
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Plot latency anomalies
    if 'latency' in df.columns and 'latency_anomaly' in df.columns:
        plt.figure(figsize=(12, 6))
        plt.scatter(df['timestamp'], df['latency'], 
                   c=df['latency_anomaly'], cmap='coolwarm', alpha=0.7)
        plt.xlabel('Time')
        plt.ylabel('Latency (seconds)')
        plt.title('API Call Latency Anomalies')
        plt.colorbar(label='Anomaly')
        plt.tight_layout()
        plt.savefig(f"{output_dir}/latency_anomalies_{timestamp}.png")
        plt.close()
        print(f"Saved latency anomaly visualization to {output_dir}/latency_anomalies_{timestamp}.png")
    
    # Plot error rate anomalies
    if 'window_error_rate' in df.columns and 'error_rate_anomaly' in df.columns:
        plt.figure(figsize=(12, 6))
        
        # Get unique timestamps for the error rate windows
        window_data = df.drop_duplicates(subset=['timestamp', 'window_error_rate', 'error_rate_anomaly'])
        
        plt.scatter(window_data['timestamp'], window_data['window_error_rate'], 
                   c=window_data['error_rate_anomaly'], cmap='coolwarm', alpha=0.7, s=50)
        plt.xlabel('Time')
        plt.ylabel('Error Rate')
        plt.title('API Call Error Rate Anomalies')
        plt.colorbar(label='Anomaly')
        plt.tight_layout()
        plt.savefig(f"{output_dir}/error_rate_anomalies_{timestamp}.png")
        plt.close()
        print(f"Saved error rate anomaly visualization to {output_dir}/error_rate_anomalies_{timestamp}.png")
    
    # Print detailed anomaly information
    if 'latency_anomaly' in df.columns:
        latency_anomalies = df[df['latency_anomaly'] == 1]
        if len(latency_anomalies) > 0:
            print("\nLatency Anomalies:")
            print(latency_anomalies[['timestamp', 'latency', 'trace_id', 'span_id', 'parent_span_id', 'error', 'error_type']].head(10))
    
    if 'error_rate_anomaly' in df.columns:
        error_anomalies = df[df['error_rate_anomaly'] == 1]
        if len(error_anomalies) > 0:
            print("\nError Rate Anomalies:")
            print(error_anomalies[['timestamp', 'window_error_rate']].drop_duplicates().head(10))

def main():
    parser = argparse.ArgumentParser(description='Detect anomalies in OpenTelemetry trace data from Elasticsearch')
    parser.add_argument('--host', default='localhost', help='Elasticsearch host')
    parser.add_argument('--port', default=9200, type=int, help='Elasticsearch port')
    parser.add_argument('--index', default='traces-generic-default', help='Elasticsearch index name')
    parser.add_argument('--hours', default=24, type=int, help='Time range in hours to analyze')
    parser.add_argument('--contamination', default=0.05, type=float, help='Isolation Forest contamination parameter')
    parser.add_argument('--error-threshold', default=0.2, type=float, help='Error rate threshold for anomaly detection')
    parser.add_argument('--output-dir', default='./anomaly_results', help='Directory to save results')
    parser.add_argument('--continuous', action='store_true', help='Run continuously with interval')
    parser.add_argument('--interval', default=300, type=int, help='Interval in seconds for continuous mode')
    
    args = parser.parse_args()
    
    # Ensure output directory exists
    os.makedirs(args.output_dir, exist_ok=True)
    
    def run_analysis():
        # Connect to Elasticsearch
        es = connect_to_elasticsearch(args.host, args.port)
        if not es:
            return
        
        # Fetch trace data
        response = fetch_trace_data(es, args.index, args.hours)
        if not response:
            return
        
        # Process the data
        df = process_trace_data(response)
        if df is None or len(df) == 0:
            print("No data to analyze")
            return
        
        # Detect anomalies
        df = detect_latency_anomalies(df, args.contamination)
        df = detect_error_rate_anomalies(df, threshold=args.error_threshold)
        
        # Visualize the results
        visualize_anomalies(df, args.output_dir)
    
    if args.continuous:
        print(f"Running in continuous mode with {args.interval} second intervals. Press Ctrl+C to stop.")
        try:
            while True:
                print(f"\n=== Analysis run at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
                run_analysis()
                print(f"Sleeping for {args.interval} seconds...")
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nStopping continuous analysis")
    else:
        run_analysis()

if __name__ == "__main__":
    main() 