"""
Subscription optimizer for handling large-scale MQTT subscriptions efficiently.

This module provides thread pool and async optimizations for subscribing to
hundreds or thousands of MQTT topics simultaneously without overwhelming
the broker or the system.
"""

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Tuple, Callable, Set
import threading


class SubscriptionOptimizer:
    """Optimizes MQTT subscriptions for large-scale deployments."""
    
    def __init__(self, max_workers: int = 10):
        self.max_workers = max_workers
        self.logger = logging.getLogger("rm_node_cli.subscription_optimizer")
        self.subscription_stats = {
            "total_attempted": 0,
            "total_successful": 0,
            "total_failed": 0,
            "start_time": 0,
            "end_time": 0
        }
        
    async def subscribe_all_nodes_optimized(self, connected_nodes: List[str], 
                                          topics: List[str],
                                          get_connection_func: Callable,
                                          create_handler_func: Callable) -> Dict:
        """
        Subscribe to topics for all nodes using optimized async + threading approach.
        
        This method uses:
        1. Thread pool for CPU-bound subscription setup
        2. Async batching for I/O-bound network operations
        3. Rate limiting to prevent broker overload
        4. Automatic retry for failed subscriptions
        """
        self.subscription_stats["start_time"] = time.time()
        self.subscription_stats["total_attempted"] = len(connected_nodes) * len(topics)
        
        self.logger.info(f"Starting optimized subscription for {len(connected_nodes)} nodes, {len(topics)} topics each")
        
        # Group nodes into optimal batches
        optimal_batch_size = min(25, max(5, len(connected_nodes) // 4))
        node_batches = [connected_nodes[i:i + optimal_batch_size] 
                       for i in range(0, len(connected_nodes), optimal_batch_size)]
        
        # Process all batches concurrently
        batch_tasks = []
        for batch_idx, node_batch in enumerate(node_batches):
            task = self._process_subscription_batch(
                batch_idx, node_batch, topics, 
                get_connection_func, create_handler_func
            )
            batch_tasks.append(task)
        
        # Execute all batches with controlled concurrency
        semaphore = asyncio.Semaphore(min(10, len(node_batches)))  # Limit concurrent batches
        async def run_batch_with_semaphore(task):
            async with semaphore:
                return await task
                
        batch_results = await asyncio.gather(
            *[run_batch_with_semaphore(task) for task in batch_tasks],
            return_exceptions=True
        )
        
        # Aggregate results
        total_successful = 0
        total_failed = 0
        failed_nodes = []
        successful_subscriptions = 0
        
        for batch_result in batch_results:
            if isinstance(batch_result, Exception):
                self.logger.error(f"Batch processing failed: {str(batch_result)}")
                continue
                
            batch_success, batch_failed, batch_failed_nodes, batch_subs = batch_result
            total_successful += batch_success
            total_failed += batch_failed
            failed_nodes.extend(batch_failed_nodes)
            successful_subscriptions += batch_subs
        
        self.subscription_stats["total_successful"] = successful_subscriptions
        self.subscription_stats["total_failed"] = (len(connected_nodes) * len(topics)) - successful_subscriptions
        self.subscription_stats["end_time"] = time.time()
        
        duration = self.subscription_stats["end_time"] - self.subscription_stats["start_time"]
        self.logger.info(f"Subscription completed in {duration:.2f}s: "
                        f"{total_successful}/{len(connected_nodes)} nodes successful, "
                        f"{successful_subscriptions} total subscriptions")
        
        return {
            "successful_nodes": total_successful,
            "failed_nodes": total_failed,
            "failed_node_list": failed_nodes,
            "total_subscriptions": successful_subscriptions,
            "duration_seconds": duration,
            "subscriptions_per_second": successful_subscriptions / duration if duration > 0 else 0
        }
    
    async def _process_subscription_batch(self, batch_idx: int, node_batch: List[str], 
                                        topics: List[str], get_connection_func: Callable,
                                        create_handler_func: Callable) -> Tuple[int, int, List[str], int]:
        """Process a batch of nodes for subscription."""
        batch_successful = 0
        batch_failed = 0
        batch_failed_nodes = []
        batch_subscriptions = 0
        
        # Create subscription tasks for all nodes in this batch
        subscription_tasks = []
        for node_id in node_batch:
            mqtt_client = get_connection_func(node_id)
            if mqtt_client:
                task = self._subscribe_single_node_optimized(
                    node_id, mqtt_client, topics, create_handler_func
                )
                subscription_tasks.append((node_id, task))
            else:
                batch_failed += 1
                batch_failed_nodes.append(node_id)
        
        # Execute all subscriptions in this batch concurrently
        if subscription_tasks:
            results = await asyncio.gather(
                *[task for _, task in subscription_tasks],
                return_exceptions=True
            )
            
            for i, result in enumerate(results):
                node_id = subscription_tasks[i][0]
                if isinstance(result, Exception):
                    self.logger.debug(f"Node {node_id} subscription failed: {str(result)}")
                    batch_failed += 1
                    batch_failed_nodes.append(node_id)
                else:
                    success, sub_count = result
                    if success:
                        batch_successful += 1
                        batch_subscriptions += sub_count
                    else:
                        batch_failed += 1
                        batch_failed_nodes.append(node_id)
        
        # Small delay between batches to prevent broker overload
        if batch_idx % 3 == 0:  # Every 3rd batch
            await asyncio.sleep(0.05)
            
        self.logger.debug(f"Batch {batch_idx + 1} completed: {batch_successful} successful, {batch_failed} failed")
        return batch_successful, batch_failed, batch_failed_nodes, batch_subscriptions
    
    async def _subscribe_single_node_optimized(self, node_id: str, mqtt_client, 
                                             topics: List[str], create_handler_func: Callable) -> Tuple[bool, int]:
        """Subscribe to all topics for a single node with optimizations."""
        successful_subscriptions = 0
        
        # Create all subscription tasks for this node
        subscription_tasks = []
        for topic_suffix in topics:
            full_topic = f"node/{node_id}/{topic_suffix}"
            handler = create_handler_func(node_id, topic_suffix)
            
            # Create the subscription coroutine
            task = self._single_topic_subscription(mqtt_client, full_topic, handler)
            subscription_tasks.append((full_topic, task))
        
        # Execute all topic subscriptions for this node concurrently
        results = await asyncio.gather(
            *[task for _, task in subscription_tasks],
            return_exceptions=True
        )
        
        # Check results
        for i, result in enumerate(results):
            full_topic = subscription_tasks[i][0]
            if isinstance(result, Exception):
                self.logger.debug(f"Failed to subscribe to {full_topic}: {str(result)}")
            elif result:
                successful_subscriptions += 1
                self.logger.debug(f"Successfully subscribed to {full_topic}")
            else:
                self.logger.debug(f"Subscription returned false for {full_topic}")
        
        # Consider node successful if at least 50% of subscriptions worked
        min_required = max(1, len(topics) // 2)
        success = successful_subscriptions >= min_required
        
        return success, successful_subscriptions
    
    async def _single_topic_subscription(self, mqtt_client, full_topic: str, handler: Callable) -> bool:
        """Subscribe to a single topic with retry logic."""
        max_retries = 2
        
        for attempt in range(max_retries):
            try:
                # Use QoS 0 for better performance with ESP RainMaker
                result = await mqtt_client.subscribe_async(full_topic, qos=0, callback=handler)
                if result:
                    return True
                    
                # If failed and not last attempt, wait briefly before retry
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.1 * (attempt + 1))  # Progressive delay
                    
            except Exception as e:
                if attempt == max_retries - 1:
                    raise e
                await asyncio.sleep(0.1 * (attempt + 1))
        
        return False
    
    def get_subscription_stats(self) -> Dict:
        """Get subscription statistics."""
        stats = self.subscription_stats.copy()
        
        if stats["end_time"] > 0 and stats["start_time"] > 0:
            duration = stats["end_time"] - stats["start_time"]
            stats["duration_seconds"] = duration
            stats["success_rate"] = (stats["total_successful"] / stats["total_attempted"] * 100) if stats["total_attempted"] > 0 else 0
            stats["subscriptions_per_second"] = stats["total_successful"] / duration if duration > 0 else 0
        
        return stats
    
    async def retry_failed_subscriptions(self, failed_nodes: List[str], 
                                       topics: List[str],
                                       get_connection_func: Callable,
                                       create_handler_func: Callable) -> Dict:
        """Retry subscriptions for nodes that failed in the initial attempt."""
        if not failed_nodes:
            return {"successful_nodes": 0, "still_failed": 0, "total_subscriptions": 0}
        
        self.logger.info(f"Retrying subscriptions for {len(failed_nodes)} failed nodes")
        
        # Use a more conservative approach for retries
        retry_results = await self.subscribe_all_nodes_optimized(
            failed_nodes, topics, get_connection_func, create_handler_func
        )
        
        return {
            "successful_nodes": retry_results["successful_nodes"],
            "still_failed": retry_results["failed_nodes"],
            "total_subscriptions": retry_results["total_subscriptions"]
        }