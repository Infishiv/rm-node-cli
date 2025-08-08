# Detailed Connection and Monitoring Flow

This document provides a step-by-step breakdown of exactly what happens when connecting to nodes and how monitoring works, including all limits, timeouts, and timing details.

## 🔗 Node Connection Flow

### Phase 1: Initialization
```
Time: 0s
┌─────────────────────────────────────────────────────────────┐
│ 1. CLI Startup                                              │
│    - Parse --max-nodes parameter (default: 1000)           │
│    - Initialize ConnectionPool with config:                 │
│      • max_concurrent_connections: min(max_nodes, 100)     │
│      • connection_rate_limit: 20 connections/second        │
│      • batch_size: 25 nodes per batch                      │
│      • circuit_breaker_threshold: 3 failures              │
│      • circuit_breaker_timeout: 180 seconds (3 minutes)   │
│      • connection_timeout: 10 seconds                      │
│      • operation_timeout: 8 seconds                        │
│      • max_retries: 2 attempts per node                    │
│    - Initialize AdaptiveMonitor (max 50 concurrent)        │
│    - Initialize SelectiveSubscriptionManager (max 300)     │
└─────────────────────────────────────────────────────────────┘
```

### Phase 2: Node Discovery
```
Time: ~1-3s
┌─────────────────────────────────────────────────────────────┐
│ 2. Certificate Discovery                                    │
│    - Scan certificate directories in parallel              │
│    - Use ThreadPoolExecutor (max 4 threads)               │
│    - Find node certificates and keys                       │
│    - Remove duplicates based on node_id                    │
│    Result: List of (node_id, cert_path, key_path) tuples   │
└─────────────────────────────────────────────────────────────┘
```

### Phase 3: Batch Connection Process
```
Time: Starting at ~3s
┌─────────────────────────────────────────────────────────────┐
│ 3. Connection Pool Startup                                  │
│    - Start rate limiter reset task (runs every 1 second)   │
│    - Start health check task (runs every 120 seconds)      │
│    - Set broker URL in connection pool                     │
└─────────────────────────────────────────────────────────────┘

For each batch of 25 nodes:
┌─────────────────────────────────────────────────────────────┐
│ 4. Batch Processing Loop                                    │
│    Time per batch: ~2-5 seconds                           │
│                                                            │
│    For each node in batch (parallel):                     │
│    ┌─────────────────────────────────────────────────────┐ │
│    │ 4a. Rate Limiting Check                             │ │
│    │     - Acquire rate limiter semaphore               │ │
│    │     - Max 20 connections/second allowed            │ │
│    │     - If at limit, wait for next second            │ │
│    └─────────────────────────────────────────────────────┘ │
│                                                            │
│    ┌─────────────────────────────────────────────────────┐ │
│    │ 4b. Connection Semaphore                           │ │
│    │     - Acquire connection semaphore                 │ │
│    │     - Max 100 concurrent connections allowed       │ │
│    │     - If at limit, wait for slot to free up        │ │
│    └─────────────────────────────────────────────────────┘ │
│                                                            │
│    ┌─────────────────────────────────────────────────────┐ │
│    │ 4c. Circuit Breaker Check                          │ │
│    │     - Check if node circuit breaker is open        │ │
│    │     - If open and < 180s elapsed, skip node        │ │
│    │     - If open and > 180s elapsed, reset and try    │ │
│    └─────────────────────────────────────────────────────┘ │
│                                                            │
│    ┌─────────────────────────────────────────────────────┐ │
│    │ 4d. Connection Attempt Loop (max 2 retries)        │ │
│    │     Attempt 1:                                     │ │
│    │     - Create MQTTOperations instance               │ │
│    │     - Set connection timeout: 10 seconds           │ │
│    │     - Set operation timeout: 8 seconds             │ │
│    │     - Call connect_async() with 10s timeout        │ │
│    │                                                    │ │
│    │     If Attempt 1 fails:                           │ │
│    │     - Wait 2 seconds (exponential backoff)         │ │
│    │     - Attempt 2: (same process)                    │ │
│    │                                                    │ │
│    │     If Attempt 2 fails:                           │ │
│    │     - Open circuit breaker for 180 seconds         │ │
│    │     - Mark node as FAILED                          │ │
│    └─────────────────────────────────────────────────────┘ │
│                                                            │
│    Wait 0.5 seconds between batches                       │
└─────────────────────────────────────────────────────────────┘
```

### Phase 4: Success Tracking
```
Time: Throughout connection process
┌─────────────────────────────────────────────────────────────┐
│ 5. Connection Statistics Tracking                          │
│    For each node, track:                                   │
│    - connection_attempts: Total attempts made              │
│    - successful_connections: Successful connections        │ 
│    - failed_connections: Failed connections               │
│    - consecutive_failures: Failures in a row              │
│    - last_attempt_time: Timestamp of last attempt         │
│    - last_success_time: Timestamp of last success         │
│    - connection_start_time: When connection established    │
└─────────────────────────────────────────────────────────────┘
```

## 📊 Monitoring Flow

### Phase 1: Monitoring Initialization
```
Time: After connections are established
┌─────────────────────────────────────────────────────────────┐
│ 1. Adaptive Monitor Startup                                │
│    - Start with max 50 concurrent monitors                 │
│    - Assign monitoring levels based on priority:           │
│      • First 10 nodes: HIGH level (30s intervals)         │
│      • Next 40 nodes: NORMAL level (60s intervals)        │
│      • Remaining nodes: LOW level (300s intervals)        │
│    - Start monitoring semaphore (max 50 concurrent)        │
└─────────────────────────────────────────────────────────────┘
```

### Phase 2: Individual Node Monitoring
```
For each monitored node:
┌─────────────────────────────────────────────────────────────┐
│ 2. Node Monitoring Loop                                    │
│                                                            │
│    ┌─────────────────────────────────────────────────────┐ │
│    │ 2a. Monitoring Level Intervals                     │ │
│    │     CRITICAL: Every 5 seconds                      │ │
│    │     HIGH:     Every 30 seconds                     │ │
│    │     NORMAL:   Every 60 seconds                     │ │
│    │     LOW:      Every 300 seconds (5 minutes)        │ │
│    │     MINIMAL:  Every 600 seconds (10 minutes)       │ │
│    └─────────────────────────────────────────────────────┘ │
│                                                            │
│    ┌─────────────────────────────────────────────────────┐ │
│    │ 2b. Health Check Process                           │ │
│    │     - Check connection status                       │ │
│    │     - Send ping message (if needed)                │ │
│    │     - Verify response within timeout               │ │
│    │     - Update activity timestamp                     │ │
│    │     - Update consecutive success/failure count      │ │
│    └─────────────────────────────────────────────────────┘ │
│                                                            │
│    ┌─────────────────────────────────────────────────────┐ │
│    │ 2c. Adaptive Level Adjustment                      │ │
│    │     Upgrade to higher monitoring if:               │ │
│    │     - Errors detected (→ HIGH or CRITICAL)         │ │
│    │     - No activity for > 300 seconds (→ HIGH)       │ │
│    │                                                    │ │
│    │     Downgrade to lower monitoring if:              │ │
│    │     - 10+ consecutive successes (HIGH → NORMAL)    │ │
│    │     - 20+ consecutive successes (NORMAL → LOW)     │ │
│    │     - No errors for extended period                │ │
│    └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### Phase 3: Background Maintenance
```
Time: Continuous background tasks
┌─────────────────────────────────────────────────────────────┐
│ 3. Background Maintenance Tasks                            │
│                                                            │
│    ┌─────────────────────────────────────────────────────┐ │
│    │ 3a. Health Check Loop (every 120 seconds)          │ │
│    │     - Check subset of connections (max 10 at once) │ │
│    │     - Verify connection status                      │ │
│    │     - Remove failed connections from pool          │ │
│    │     - Update connection states                      │ │
│    └─────────────────────────────────────────────────────┘ │
│                                                            │
│    ┌─────────────────────────────────────────────────────┐ │
│    │ 3b. Rate Limiter Reset (every 1 second)            │ │
│    │     - Reset connection rate limiter                 │ │
│    │     - Allow up to 20 new connections               │ │
│    └─────────────────────────────────────────────────────┘ │
│                                                            │
│    ┌─────────────────────────────────────────────────────┐ │
│    │ 3c. Monitoring Adjustment (every 60 seconds)       │ │
│    │     - Review nodes with > 10 errors               │ │
│    │     - Bulk adjust monitoring levels if needed      │ │
│    │     - Log monitoring statistics                     │ │
│    └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## 📈 Subscription Management

### Selective MQTT Subscriptions
```
┌─────────────────────────────────────────────────────────────┐
│ Subscription Limits and Priority                           │
│                                                            │
│ Total subscription limit: 300 (for resource management)    │
│ Per-node topics: 3 (params/remote, otaurl, to-node)       │
│ Theoretical max nodes with full subscriptions: 100        │
│                                                            │
│ Priority system:                                           │
│ - Priority 1: Critical/High monitoring level nodes        │
│ - Priority 2: Normal monitoring level nodes               │
│ - Priority 3: Low/Minimal monitoring level nodes          │
│                                                            │
│ When at capacity:                                          │
│ - Remove lowest priority subscriptions first              │
│ - Maintain subscriptions for most important nodes         │
└─────────────────────────────────────────────────────────────┘
```

## ⏱️ Timing Examples

### Example: 100 Nodes Connection
```
Time 0s:     CLI startup, initialize pools
Time 1-3s:   Certificate discovery
Time 3s:     Start connecting batch 1 (nodes 1-25)
Time 4s:     Start connecting batch 2 (nodes 26-50) 
Time 5s:     Start connecting batch 3 (nodes 51-75)
Time 6s:     Start connecting batch 4 (nodes 76-100)
Time 7-15s:  Connections complete (depending on network)
Time 15s:    Start adaptive monitoring for connected nodes
Time 16s:    CLI ready for interactive use
```

### Example: 1000 Nodes Connection
```
Time 0s:     CLI startup, initialize pools
Time 1-5s:   Certificate discovery (more files to scan)
Time 5s:     Start connecting batch 1 (nodes 1-25)
Time 5.5s:   Start connecting batch 2 (nodes 26-50)
Time 6s:     Start connecting batch 3 (nodes 51-75)
Time 6.5s:   Start connecting batch 4 (nodes 76-100)
...          Continue with 20 connections/second rate limit
Time 55s:    Last batch starts (nodes 976-1000)
Time 65-90s: All connections complete
Time 90s:    Start adaptive monitoring (50 highest priority)
Time 91s:    CLI ready for interactive use
```

## 🚨 Error Handling Timeline

### Circuit Breaker Example
```
Node "ABC123" connection attempts:

Time 0s:     First attempt fails (timeout after 10s)
Time 12s:    Second attempt fails (with 2s backoff + 10s timeout)
Time 24s:    Circuit breaker opens (3 failures reached)
Time 24-204s: Node skipped (180s circuit breaker timeout)
Time 204s:   Circuit breaker resets, node eligible for retry
```

### Monitoring Level Escalation Example
```
Node "XYZ789" monitoring progression:

Time 0s:     Connected, assigned NORMAL level (60s intervals)
Time 60s:    Health check OK, stays NORMAL
Time 120s:   Health check fails, escalated to HIGH (30s intervals)
Time 150s:   Health check fails again, escalated to CRITICAL (5s intervals)
Time 155s:   Health check OK, stays CRITICAL
Time 160s:   Health check OK, 2 consecutive successes
Time 165s:   Health check OK, 3 consecutive successes, downgrade to HIGH
Time 195s:   Health check OK, after 10 successes, downgrade to NORMAL
```

## 📊 Resource Usage Patterns

### Memory Usage
- **Connection Pool**: ~1MB per 100 nodes
- **Monitoring System**: ~500KB per 50 monitored nodes  
- **Subscription Manager**: ~100KB per 100 subscriptions
- **Total for 1000 nodes**: ~15-20MB (vs 60-80MB in old system)

### CPU Usage
- **Connection Phase**: High during initial connection (30-90s)
- **Steady State**: Low (periodic health checks only)
- **Monitoring Overhead**: <5% CPU for 1000 nodes

### Network Usage
- **Connection Phase**: Burst of connection attempts
- **Steady State**: Minimal (health checks + actual MQTT traffic)
- **Rate Limited**: Maximum 20 connection attempts/second

This detailed flow ensures reliable, scalable operation while respecting AWS IoT limits and system resources.