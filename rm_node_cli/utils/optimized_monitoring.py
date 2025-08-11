"""
Optimized monitoring strategy for large-scale node management.

This module provides:
1. Selective monitoring based on node priority/health
2. Adaptive monitoring intervals
3. Event-driven monitoring instead of continuous polling
4. Resource-aware subscription management
"""

import asyncio
import time
import logging
from typing import Dict, List, Set, Optional, Callable
from dataclasses import dataclass
from enum import Enum
import json
from collections import defaultdict, deque


class MonitoringLevel(Enum):
    CRITICAL = "critical"      # Monitor every 5 seconds
    HIGH = "high"             # Monitor every 30 seconds  
    NORMAL = "normal"         # Monitor every 60 seconds
    LOW = "low"              # Monitor every 300 seconds
    MINIMAL = "minimal"       # Monitor every 600 seconds (10 minutes)


@dataclass
class NodeMonitoringProfile:
    """Monitoring profile for a node."""
    node_id: str
    level: MonitoringLevel = MonitoringLevel.NORMAL
    last_activity: float = 0
    error_count: int = 0
    consecutive_successes: int = 0
    topics_of_interest: Set[str] = None
    custom_interval: Optional[int] = None
    
    def __post_init__(self):
        if self.topics_of_interest is None:
            self.topics_of_interest = set()


class AdaptiveMonitor:
    """Adaptive monitoring system that adjusts based on node behavior."""
    
    def __init__(self, max_concurrent_monitors: int = 0):  # 0 = unlimited
        self.max_concurrent_monitors = max_concurrent_monitors
        self.node_profiles: Dict[str, NodeMonitoringProfile] = {}
        self.active_monitors: Set[str] = set()
        self.monitoring_tasks: Dict[str, asyncio.Task] = {}
        self.event_handlers: Dict[str, List[Callable]] = defaultdict(list)
        
        # Resource management - unlimited if set to 0
        if max_concurrent_monitors > 0:
            self.monitor_semaphore = asyncio.Semaphore(max_concurrent_monitors)
        else:
            self.monitor_semaphore = None
            
        self.is_running = False
        
        # Statistics
        self.monitoring_stats = {
            "total_events": 0,
            "error_events": 0,
            "nodes_monitored": 0,
            "active_subscriptions": 0
        }
        
        self.logger = logging.getLogger("rm_node_cli.adaptive_monitor")
        
    async def start(self):
        """Start the adaptive monitoring system."""
        self.is_running = True
        self.logger.info("Adaptive monitor started")
        
    async def stop(self):
        """Stop all monitoring tasks."""
        self.is_running = False
        
        # Suppress logging during shutdown
        self.logger.setLevel(logging.CRITICAL)
        
        # Cancel all monitoring tasks
        for task in self.monitoring_tasks.values():
            task.cancel()
            
        await asyncio.gather(*self.monitoring_tasks.values(), return_exceptions=True)
        self.monitoring_tasks.clear()
        self.active_monitors.clear()
        
    def add_node(self, node_id: str, initial_level: MonitoringLevel = MonitoringLevel.NORMAL,
                topics: Set[str] = None):
        """Add a node to monitoring with specified level."""
        if topics is None:
            topics = {"params/remote", "otaurl", "to-node"}
            
        profile = NodeMonitoringProfile(
            node_id=node_id,
            level=initial_level,
            last_activity=time.time(),
            topics_of_interest=topics
        )
        
        self.node_profiles[node_id] = profile
        
        # Start monitoring immediately (no capacity limits)
        asyncio.create_task(self._start_monitoring_node(node_id))
            
    def remove_node(self, node_id: str):
        """Remove a node from monitoring."""
        if node_id in self.monitoring_tasks:
            self.monitoring_tasks[node_id].cancel()
            del self.monitoring_tasks[node_id]
            
        self.active_monitors.discard(node_id)
        self.node_profiles.pop(node_id, None)
        
    def update_node_level(self, node_id: str, new_level: MonitoringLevel):
        """Update monitoring level for a node."""
        if node_id in self.node_profiles:
            self.node_profiles[node_id].level = new_level
            self.logger.debug(f"Updated monitoring level for {node_id} to {new_level.value}")
            
    async def _start_monitoring_node(self, node_id: str):
        """Start monitoring a specific node."""
        if node_id in self.active_monitors or not self.is_running:
            return
            
        # No capacity limits - start monitoring immediately
        if self.monitor_semaphore:
            async with self.monitor_semaphore:
                self.active_monitors.add(node_id)
                task = asyncio.create_task(self._monitor_node_loop(node_id))
                self.monitoring_tasks[node_id] = task
        else:
            # Unlimited monitoring
            self.active_monitors.add(node_id)
            task = asyncio.create_task(self._monitor_node_loop(node_id))
            self.monitoring_tasks[node_id] = task
            
    async def _monitor_node_loop(self, node_id: str):
        """Main monitoring loop for a node."""
        try:
            while self.is_running and node_id in self.node_profiles:
                profile = self.node_profiles[node_id]
                interval = self._get_monitoring_interval(profile)
                
                # Perform monitoring check
                await self._check_node_health(node_id)
                
                # Adaptive level adjustment
                self._adjust_monitoring_level(profile)
                
                # Wait for next check
                await asyncio.sleep(interval)
                
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.error(f"Error in monitoring loop for {node_id}: {str(e)}")
        finally:
            self.active_monitors.discard(node_id)
            self.monitoring_tasks.pop(node_id, None)
            
    def _get_monitoring_interval(self, profile: NodeMonitoringProfile) -> int:
        """Get monitoring interval based on profile level."""
        if profile.custom_interval:
            return profile.custom_interval
            
        # Optimized for ESP RainMaker 20s keep-alive
        intervals = {
            MonitoringLevel.CRITICAL: 15,  # More frequent than keep-alive for critical nodes
            MonitoringLevel.HIGH: 25,     # Just over keep-alive period
            MonitoringLevel.NORMAL: 45,   # 2x keep-alive period  
            MonitoringLevel.LOW: 120,     # 6x keep-alive period
            MonitoringLevel.MINIMAL: 300  # 15x keep-alive period
        }
        
        return intervals.get(profile.level, 60)
        
    async def _check_node_health(self, node_id: str):
        """Check health of a specific node."""
        try:
            # This would be implemented to check specific node health
            # For now, it's a placeholder that can be extended
            profile = self.node_profiles[node_id]
            
            # Simulate health check
            # In real implementation, this would:
            # 1. Check if connection is alive
            # 2. Send a ping/health check message
            # 3. Verify response within timeout
            
            current_time = time.time()
            time_since_activity = current_time - profile.last_activity
            
            # If no activity for too long, increase monitoring level
            if time_since_activity > 300:  # 5 minutes
                if profile.level != MonitoringLevel.CRITICAL:
                    profile.level = MonitoringLevel.HIGH
                    
            profile.consecutive_successes += 1
            self.monitoring_stats["nodes_monitored"] += 1
            
        except Exception as e:
            profile = self.node_profiles[node_id]
            profile.error_count += 1
            profile.consecutive_successes = 0
            self.monitoring_stats["error_events"] += 1
            self.logger.warning(f"Health check failed for {node_id}: {str(e)}")
            
    def _adjust_monitoring_level(self, profile: NodeMonitoringProfile):
        """Dynamically adjust monitoring level based on node behavior."""
        # Upgrade monitoring level if errors detected
        if profile.error_count > 0:
            if profile.consecutive_successes < 3:
                profile.level = MonitoringLevel.HIGH
            elif profile.consecutive_successes >= 10:
                # Downgrade if consistently successful
                if profile.level == MonitoringLevel.HIGH:
                    profile.level = MonitoringLevel.NORMAL
                elif profile.level == MonitoringLevel.NORMAL and profile.error_count == 0:
                    profile.level = MonitoringLevel.LOW
                    
        # Reset error count after successful period
        if profile.consecutive_successes >= 20:
            profile.error_count = max(0, profile.error_count - 1)
            
    def record_node_activity(self, node_id: str, activity_type: str = "message"):
        """Record activity for a node to adjust monitoring."""
        if node_id in self.node_profiles:
            profile = self.node_profiles[node_id]
            profile.last_activity = time.time()
            
            # Activity suggests node is healthy, can reduce monitoring
            if activity_type == "successful_operation":
                profile.consecutive_successes += 1
                
    def record_node_error(self, node_id: str, error_details: str = ""):
        """Record an error for a node to increase monitoring."""
        if node_id in self.node_profiles:
            profile = self.node_profiles[node_id]
            profile.error_count += 1
            profile.consecutive_successes = 0
            profile.level = MonitoringLevel.CRITICAL
            self.logger.warning(f"Error recorded for {node_id}: {error_details}")
            
    def get_priority_nodes(self, max_count: int = None) -> List[str]:
        """Get nodes that should be prioritized for monitoring."""
        # Sort by monitoring level priority and error count
        priority_order = [
            MonitoringLevel.CRITICAL,
            MonitoringLevel.HIGH,
            MonitoringLevel.NORMAL,
            MonitoringLevel.LOW,
            MonitoringLevel.MINIMAL
        ]
        
        nodes_by_priority = []
        for level in priority_order:
            level_nodes = [
                (node_id, profile) for node_id, profile in self.node_profiles.items()
                if profile.level == level
            ]
            # Sort by error count (descending) and last activity (ascending)
            level_nodes.sort(key=lambda x: (-x[1].error_count, x[1].last_activity))
            nodes_by_priority.extend([node_id for node_id, _ in level_nodes])
            
        if max_count:
            return nodes_by_priority[:max_count]
        return nodes_by_priority
        
    def get_monitoring_summary(self) -> Dict:
        """Get summary of monitoring status."""
        level_counts = defaultdict(int)
        error_nodes = []
        
        for node_id, profile in self.node_profiles.items():
            level_counts[profile.level.value] += 1
            if profile.error_count > 0:
                error_nodes.append({
                    "node_id": node_id,
                    "error_count": profile.error_count,
                    "level": profile.level.value
                })
                
        return {
            "total_nodes": len(self.node_profiles),
            "active_monitors": len(self.active_monitors),
            "level_distribution": dict(level_counts),
            "nodes_with_errors": len(error_nodes),
            "error_nodes": error_nodes[:10],  # Top 10 error nodes
            "stats": self.monitoring_stats.copy()
        }
        
    async def bulk_adjust_monitoring(self, criteria: Dict):
        """Bulk adjust monitoring levels based on criteria."""
        adjustments = 0
        
        for node_id, profile in self.node_profiles.items():
            # Example criteria: adjust based on error rate
            if "max_errors" in criteria and profile.error_count > criteria["max_errors"]:
                profile.level = MonitoringLevel.CRITICAL
                adjustments += 1
            elif "min_successes" in criteria and profile.consecutive_successes > criteria["min_successes"]:
                if profile.level in [MonitoringLevel.CRITICAL, MonitoringLevel.HIGH]:
                    profile.level = MonitoringLevel.NORMAL
                    adjustments += 1
                    
        self.logger.info(f"Bulk adjusted monitoring for {adjustments} nodes")
        return adjustments


class SelectiveSubscriptionManager:
    """Manages MQTT subscriptions with dynamic scaling for unlimited nodes."""
    
    def __init__(self, max_subscriptions: int = None):
        # If None, allow unlimited subscriptions with dynamic resource management
        self.max_subscriptions = max_subscriptions
        self.active_subscriptions: Dict[str, Set[str]] = defaultdict(set)  # node_id -> topics
        self.topic_handlers: Dict[str, Callable] = {}
        self.subscription_priority: Dict[str, int] = {}
        self.logger = logging.getLogger("rm_node_cli.selective_subscription")
        
    def subscribe_node_topics(self, node_id: str, topics: List[str], 
                            mqtt_client, priority: int = 1):
        """Subscribe to topics for a node with priority."""
        current_total = sum(len(topics) for topics in self.active_subscriptions.values())
        
        # If max_subscriptions is set and we're at capacity, remove lower priority subscriptions
        if self.max_subscriptions and current_total + len(topics) > self.max_subscriptions:
            self._cleanup_low_priority_subscriptions(len(topics))
            
        for topic in topics:
            full_topic = f"{node_id}/{topic}"
            try:
                mqtt_client.subscribe(full_topic, qos=0)  # Use QoS 0 for better performance
                self.active_subscriptions[node_id].add(topic)
                self.subscription_priority[full_topic] = priority
                self.logger.debug(f"Subscribed to {full_topic}")
            except Exception as e:
                self.logger.error(f"Failed to subscribe to {full_topic}: {str(e)}")
                
    def unsubscribe_node(self, node_id: str, mqtt_client):
        """Unsubscribe from all topics for a node."""
        if node_id in self.active_subscriptions:
            for topic in self.active_subscriptions[node_id]:
                full_topic = f"{node_id}/{topic}"
                try:
                    mqtt_client.unsubscribe(full_topic)
                    self.subscription_priority.pop(full_topic, None)
                except Exception as e:
                    self.logger.error(f"Failed to unsubscribe from {full_topic}: {str(e)}")
            del self.active_subscriptions[node_id]
            
    def _cleanup_low_priority_subscriptions(self, needed_slots: int):
        """Remove low priority subscriptions to make room."""
        # Sort by priority (lower number = lower priority)
        sorted_topics = sorted(self.subscription_priority.items(), key=lambda x: x[1])
        
        removed = 0
        for full_topic, priority in sorted_topics:
            if removed >= needed_slots:
                break
                
            # Extract node_id and topic from full_topic
            if '/' in full_topic:
                node_id, topic = full_topic.split('/', 1)
                self.active_subscriptions[node_id].discard(topic)
                del self.subscription_priority[full_topic]
                removed += 1
                self.logger.debug(f"Removed low priority subscription: {full_topic}")
                
    def get_subscription_summary(self) -> Dict:
        """Get summary of current subscriptions."""
        total_subscriptions = sum(len(topics) for topics in self.active_subscriptions.values())
        
        return {
            "total_subscriptions": total_subscriptions,
            "max_subscriptions": self.max_subscriptions or "Unlimited",
            "utilization": f"{(total_subscriptions/self.max_subscriptions)*100:.1f}%" if self.max_subscriptions else "Unlimited",
            "nodes_with_subscriptions": len(self.active_subscriptions),
            "average_topics_per_node": total_subscriptions / max(len(self.active_subscriptions), 1)
        }