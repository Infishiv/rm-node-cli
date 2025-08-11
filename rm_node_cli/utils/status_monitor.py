"""
Status monitoring utilities for the scalable RM-Node CLI.

Provides commands and utilities for monitoring the health and performance
of the connection pool and adaptive monitoring system.
"""

import click
import time
from typing import Dict, List
import json


class StatusMonitor:
    """Provides status monitoring capabilities for the CLI."""
    
    def __init__(self, manager):
        self.manager = manager
        
    def show_connection_status(self, detailed: bool = False):
        """Show connection pool status."""
        pool_stats = self.manager.connection_pool.get_connection_stats()
        connected_nodes = self.manager.connection_pool.get_connected_nodes()
        
        # Basic stats
        click.echo(click.style("\nConnection Pool Status", fg='blue', bold=True))
        click.echo(f"Connected nodes: {len(connected_nodes)}")
        click.echo(f"Pool configuration: {self.manager.connection_pool.config.max_concurrent_connections} max connections")
        click.echo(f"Rate limit: {self.manager.connection_pool.config.connection_rate_limit} connections/second")
        click.echo(f"Batch size: {self.manager.connection_pool.config.batch_size}")
        
        if detailed and pool_stats:
            click.echo(click.style("\nDetailed Node Statistics", fg='yellow', bold=True))
            
            # Group nodes by state
            states = {}
            for node_id, stats in pool_stats.items():
                state = stats['state']
                if state not in states:
                    states[state] = []
                states[state].append((node_id, stats))
                
            for state, nodes in states.items():
                click.echo(f"\n{state.upper()} ({len(nodes)} nodes):")
                if state == 'connected':
                    color = 'green'
                elif state == 'failed':
                    color = 'red'
                elif state == 'circuit_open':
                    color = 'magenta'
                else:
                    color = 'yellow'
                    
                for node_id, stats in nodes[:10]:  # Show first 10
                    uptime = f"{stats['uptime']:.1f}s" if stats['uptime'] > 0 else "N/A"
                    click.echo(click.style(
                        f"  {node_id}: {stats['attempts']} attempts, "
                        f"{stats['successful']} successful, uptime: {uptime}",
                        fg=color
                    ))
                    
                if len(nodes) > 10:
                    click.echo(f"  ... and {len(nodes) - 10} more")
                    
    def show_monitoring_status(self):
        """Show adaptive monitoring status."""
        monitoring_summary = self.manager.adaptive_monitor.get_monitoring_summary()
        
        click.echo(click.style("\nAdaptive Monitoring Status", fg='cyan', bold=True))
        click.echo(f"Total nodes: {monitoring_summary['total_nodes']}")
        click.echo(f"Active monitors: {monitoring_summary['active_monitors']}")
        click.echo(f"Nodes with errors: {monitoring_summary['nodes_with_errors']}")
        
        # Show level distribution
        if monitoring_summary['level_distribution']:
            click.echo("\nMonitoring levels:")
            for level, count in monitoring_summary['level_distribution'].items():
                click.echo(f"  {level}: {count} nodes")
                
        # Show error nodes
        if monitoring_summary['error_nodes']:
            click.echo(click.style("\nNodes with Errors", fg='red', bold=True))
            for error_node in monitoring_summary['error_nodes']:
                click.echo(f"  {error_node['node_id']}: {error_node['error_count']} errors, "
                          f"level: {error_node['level']}")
                          
    def show_subscription_status(self):
        """Show subscription manager status."""
        sub_summary = self.manager.subscription_manager.get_subscription_summary()
        
        click.echo(click.style("\n📺 Subscription Status", fg='magenta', bold=True))
        click.echo(f"Total subscriptions: {sub_summary['total_subscriptions']}")
        click.echo(f"Utilization: {sub_summary['utilization']}")
        click.echo(f"Nodes with subscriptions: {sub_summary['nodes_with_subscriptions']}")
        click.echo(f"Average topics per node: {sub_summary['average_topics_per_node']:.1f}")
        
    def show_performance_metrics(self):
        """Show performance metrics."""
        click.echo(click.style("\n⚡ Performance Metrics", fg='green', bold=True))
        
        # Connection pool metrics
        pool_stats = self.manager.connection_pool.get_connection_stats()
        if pool_stats:
            total_attempts = sum(stats['attempts'] for stats in pool_stats.values())
            total_successful = sum(stats['successful'] for stats in pool_stats.values())
            success_rate = (total_successful / total_attempts * 100) if total_attempts > 0 else 0
            
            click.echo(f"Overall success rate: {success_rate:.1f}%")
            click.echo(f"Total connection attempts: {total_attempts}")
            click.echo(f"Successful connections: {total_successful}")
            
        # Monitoring metrics
        monitoring_stats = self.manager.adaptive_monitor.monitoring_stats
        click.echo(f"Total monitoring events: {monitoring_stats['total_events']}")
        click.echo(f"Error events: {monitoring_stats['error_events']}")
        
        if monitoring_stats['total_events'] > 0:
            error_rate = monitoring_stats['error_events'] / monitoring_stats['total_events'] * 100
            click.echo(f"Error rate: {error_rate:.1f}%")
            
    def export_status_json(self, filename: str = None):
        """Export status to JSON file."""
        if not filename:
            filename = f"rm_node_status_{int(time.time())}.json"
            
        status = {
            "timestamp": time.time(),
            "connection_pool": {
                "stats": self.manager.connection_pool.get_connection_stats(),
                "connected_nodes": self.manager.connection_pool.get_connected_nodes(),
                "config": {
                    "max_concurrent_connections": self.manager.connection_pool.config.max_concurrent_connections,
                    "connection_rate_limit": self.manager.connection_pool.config.connection_rate_limit,
                    "batch_size": self.manager.connection_pool.config.batch_size,
                    "circuit_breaker_threshold": self.manager.connection_pool.config.circuit_breaker_threshold,
                    "circuit_breaker_timeout": self.manager.connection_pool.config.circuit_breaker_timeout,
                }
            },
            "adaptive_monitoring": self.manager.adaptive_monitor.get_monitoring_summary(),
            "subscriptions": self.manager.subscription_manager.get_subscription_summary()
        }
        
        try:
            with open(filename, 'w') as f:
                json.dump(status, f, indent=2)
            click.echo(click.style(f"✓ Status exported to {filename}", fg='green'))
            return filename
        except Exception as e:
            click.echo(click.style(f"✗ Error exporting status: {str(e)}", fg='red'))
            return None
            
    def show_recommendations(self):
        """Show recommendations for optimization."""
        click.echo(click.style("\nOptimization Recommendations", fg='blue', bold=True))
        
        # Analyze connection pool
        pool_stats = self.manager.connection_pool.get_connection_stats()
        if pool_stats:
            failed_nodes = [node_id for node_id, stats in pool_stats.items() 
                           if stats['state'] == 'failed']
            circuit_open_nodes = [node_id for node_id, stats in pool_stats.items() 
                                 if stats['state'] == 'circuit_open']
                                 
            if len(failed_nodes) > 10:
                click.echo(f"{len(failed_nodes)} nodes failed - consider investigating network issues")
                
            if len(circuit_open_nodes) > 5:
                click.echo(f"{len(circuit_open_nodes)} nodes have circuit breaker open - "
                          "consider increasing circuit breaker timeout")
                          
        # Analyze monitoring
        monitoring_summary = self.manager.adaptive_monitor.get_monitoring_summary()
        if monitoring_summary['nodes_with_errors'] > monitoring_summary['total_nodes'] * 0.1:
            click.echo("High error rate in monitoring - consider adjusting monitoring levels")
            
        # Analyze subscriptions
        sub_summary = self.manager.subscription_manager.get_subscription_summary()
        utilization = float(sub_summary['utilization'].rstrip('%'))
        if utilization > 80:
            click.echo("High subscription utilization - consider increasing max_subscriptions")
        elif utilization < 20:
            click.echo("Low subscription utilization - you could increase monitoring coverage")
            
        click.echo("For more optimization tips, see the documentation")
        
    def show_all_status(self, detailed: bool = False):
        """Show comprehensive status overview."""
        click.echo(click.style("=" * 60, fg='blue'))
        click.echo(click.style("🚀 RM-Node CLI Scalable Status Overview", fg='blue', bold=True))
        click.echo(click.style("=" * 60, fg='blue'))
        
        self.show_connection_status(detailed)
        self.show_monitoring_status()
        self.show_subscription_status()
        self.show_performance_metrics()
        self.show_recommendations()
        
        click.echo(click.style("\n" + "=" * 60, fg='blue'))