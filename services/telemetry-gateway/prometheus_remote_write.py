"""
Prometheus Remote Write Protocol Handler
Handles snappy-compressed protobuf WriteRequest
"""
import gzip
import logging
import struct
from datetime import datetime, timezone
from typing import List, Dict, Any, Tuple, Optional

import snappy
from fastapi import Request, HTTPException

logger = logging.getLogger("prometheus-remote-write")


class WriteRequest:
    """Simplified Prometheus remote write request parser.
    
    For full protobuf support, install:
    pip install prometheus-client protobuf
    
    This implementation provides a fallback JSON decoder for testing.
    """
    
    @staticmethod
    async def parse(request: Request) -> List[Dict[str, Any]]:
        """
        Parse Prometheus remote write request.
        
        Supports:
        1. Snappy-compressed protobuf (native Prometheus)
        2. Snappy-compressed JSON
        3. Plain JSON (for testing)
        4. Gzip-compressed JSON
        
        Returns list of metric samples with format:
        {
            'metric_name': str,
            'labels': Dict[str, str],
            'value': float,
            'timestamp_ms': int
        }
        """
        body = await request.body()
        content_encoding = request.headers.get('content-encoding', '').lower()
        content_type = request.headers.get('content-type', '').lower()
        
        # Decompress if needed
        if 'snappy' in content_encoding:
            try:
                body = snappy.decompress(body)
                logger.debug("Decompressed snappy payload")
            except Exception as e:
                logger.warning(f"Snappy decompression failed: {e}")
                # Try to parse as-is (might be plain JSON)
        
        elif 'gzip' in content_encoding:
            try:
                body = gzip.decompress(body)
                logger.debug("Decompressed gzip payload")
            except Exception as e:
                logger.warning(f"Gzip decompression failed: {e}")
        
        # Try JSON first (for testing and compatibility)
        try:
            import json
            data = json.loads(body)
            return WriteRequest._parse_json(data)
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
        
        # Try protobuf if available
        try:
            return WriteRequest._parse_protobuf(body)
        except Exception as e:
            logger.error(f"Failed to parse protobuf: {e}")
            raise HTTPException(400, "Unable to parse request body. Expected snappy-protobuf or JSON.")
    
    @staticmethod
    def _parse_json(data: Any) -> List[Dict[str, Any]]:
        """Parse JSON format (for testing)."""
        samples = []
        
        # Handle direct list of samples
        if isinstance(data, list):
            for item in data:
                samples.extend(WriteRequest._extract_samples(item))
        # Handle dict with 'timeseries' key
        elif isinstance(data, dict):
            if 'timeseries' in data:
                for ts in data['timeseries']:
                    samples.extend(WriteRequest._extract_timeseries(ts))
            elif 'metrics' in data:
                for m in data['metrics']:
                    samples.extend(WriteRequest._extract_samples(m))
            else:
                samples.extend(WriteRequest._extract_samples(data))
        
        return samples
    
    @staticmethod
    def _extract_timeseries(ts: Dict) -> List[Dict[str, Any]]:
        """Extract samples from a timeseries object."""
        labels = {label['name']: label['value'] for label in ts.get('labels', [])}
        metric_name = labels.pop('__name__', 'unknown')
        
        samples = []
        for sample in ts.get('samples', []):
            samples.append({
                'metric_name': metric_name,
                'labels': labels.copy(),
                'value': float(sample.get('value', 0)),
                'timestamp_ms': int(sample.get('timestamp', datetime.now(timezone.utc).timestamp() * 1000))
            })
        return samples
    
    @staticmethod
    def _extract_samples(item: Dict) -> List[Dict[str, Any]]:
        """Extract samples from a metric item."""
        name = item.get('name', item.get('__name__', 'unknown'))
        labels = item.get('labels', item.get('label', {}))
        value = float(item.get('value', 0))
        
        # Handle timestamp
        ts = item.get('timestamp_ms')
        if ts is None:
            ts = int(datetime.now(timezone.utc).timestamp() * 1000)
        else:
            ts = int(ts)
        
        return [{
            'metric_name': name,
            'labels': labels,
            'value': value,
            'timestamp_ms': ts
        }]
    
    @staticmethod
    def _parse_protobuf(body: bytes) -> List[Dict[str, Any]]:
        """Parse protobuf format (requires prometheus_client or generated protobuf)."""
        try:
            # Try using prometheus_client if available
            from prometheus_client.parser import text_string_to_metric_families
            
            # For now, we use a simplified protobuf parser
            # In production, generate protobuf from:
            # https://github.com/prometheus/prometheus/blob/main/prompb/remote.proto
            
            # Try to import generated protobuf
            from .prometheus_pb2 import WriteRequest as PBWriteRequest
            
            wr = PBWriteRequest()
            wr.ParseFromString(body)
            
            samples = []
            for ts in wr.timeseries:
                labels = {}
                for label in ts.labels:
                    labels[label.name] = label.value
                
                metric_name = labels.pop('__name__', 'unknown')
                
                for sample in ts.samples:
                    samples.append({
                        'metric_name': metric_name,
                        'labels': labels.copy(),
                        'value': float(sample.value),
                        'timestamp_ms': int(sample.timestamp)
                    })
            
            return samples
            
        except ImportError:
            logger.error("protobuf module not available. Install: pip install prometheus-client protobuf")
            raise HTTPException(400, "Protobuf support not available. Use JSON format for testing.")
        except Exception as e:
            logger.error(f"Protobuf parsing error: {e}")
            raise


def generate_prometheus_stats() -> str:
    """Generate Prometheus exposition format for telemetry-gateway self-metrics."""
    from .main import stats, _metric_map, _source_map
    
    output = []
    output.append("# HELP telemetry_gateway_metrics_received Total metrics received")
    output.append("# TYPE telemetry_gateway_metrics_received counter")
    output.append(f'telemetry_gateway_metrics_received{{service="telemetry-gateway"}} {stats["metrics_received"]}')
    
    output.append("# HELP telemetry_gateway_alerts_received Total alerts received")
    output.append("# TYPE telemetry_gateway_alerts_received counter")
    output.append(f'telemetry_gateway_alerts_received{{service="telemetry-gateway"}} {stats["alerts_received"]}')
    
    output.append("# HELP telemetry_gateway_events_received Total events received")
    output.append("# TYPE telemetry_gateway_events_received counter")
    output.append(f'telemetry_gateway_events_received{{service="telemetry-gateway"}} {stats["events_received"]}')
    
    output.append("# HELP telemetry_gateway_dead_letters Total dead letter messages")
    output.append("# TYPE telemetry_gateway_dead_letters counter")
    output.append(f'telemetry_gateway_dead_letters{{service="telemetry-gateway"}} {stats["dead_letters"]}')
    
    output.append("# HELP telemetry_gateway_metric_mappings_loaded Number of metric catalogue mappings loaded")
    output.append("# TYPE telemetry_gateway_metric_mappings_loaded gauge")
    output.append(f'telemetry_gateway_metric_mappings_loaded{{service="telemetry-gateway"}} {len(_metric_map)}')
    
    output.append("# HELP telemetry_gateway_sources_loaded Number of telemetry sources loaded")
    output.append("# TYPE telemetry_gateway_sources_loaded gauge")
    output.append(f'telemetry_gateway_sources_loaded{{service="telemetry-gateway"}} {len(_source_map)}')
    
    return "\n".join(output)
