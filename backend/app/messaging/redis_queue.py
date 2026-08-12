"""
Redis Task Queue Implementation
Provides Redis-based message queue functionality for task distribution and consumption.
"""

import json
import os
import threading
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

import structlog

from app.core.logging import get_logger

try:
    import redis
    from redis.connection import ConnectionPool
except ImportError:
    redis = None
    ConnectionPool = None

logger = get_logger(__name__)


class RedisTaskQueue:
    """Redis-based task queue for distributed task processing"""

    def __init__(self, redis_url: str | None = None, queue_name: str = "agentx_tasks"):
        """
        Initialize Redis task queue

        Args:
            redis_url: Redis connection URL (e.g., redis://localhost:6379/0)
            queue_name: Name of the Redis queue
        """
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.queue_name = queue_name
        self.redis_client = None
        self.connection_pool = None
        self._connected = False

        # Try to establish Redis connection
        self._connect()

    def _connect(self) -> bool:
        """Establish connection to Redis"""
        if redis is None:
            logger.warning("Redis not available. Install redis>=5.0.0")
            return False

        try:
            # Create connection pool for better performance
            self.connection_pool = ConnectionPool.from_url(self.redis_url)
            self.redis_client = redis.Redis(connection_pool=self.connection_pool)

            # Test connection
            self.redis_client.ping()
            self._connected = True
            logger.info(f"Connected to Redis at {self.redis_url}")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            self._connected = False
            return False

    def is_available(self) -> bool:
        """Check if Redis queue is available"""
        return self._connected and self.redis_client is not None

    def publish_task(self, task_data: dict[str, Any], priority: int = 0) -> bool:
        """
        Publish task to Redis queue

        Args:
            task_data: Task data dictionary
            priority: Task priority (higher = higher priority)

        Returns:
            True if task was published successfully
        """
        if not self.is_available():
            logger.warning("Redis not available, cannot publish task")
            return False

        try:
            # Add timestamp and priority to task
            task_data.update({"timestamp": datetime.utcnow().isoformat(), "priority": priority})

            # Serialize task data
            task_json = json.dumps(task_data, default=str)

            # Use Redis list with priority (LPUSH for FIFO)
            self.redis_client.lpush(self.queue_name, task_json)

            logger.info(
                f"Published task to queue {self.queue_name}: {task_data.get('task_id', 'unknown')}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to publish task: {e}")
            return False

    def consume_tasks(self, callback: Callable[[dict[str, Any]], None], timeout: int = 30) -> None:
        """
        Consume tasks from Redis queue

        Args:
            callback: Function to handle consumed tasks
            timeout: Timeout in seconds for blocking pop
        """
        if not self.is_available():
            logger.warning("Redis not available, cannot consume tasks")
            return

        logger.info(f"Starting task consumption from queue {self.queue_name}")

        try:
            while True:
                try:
                    # Use BRPOP for blocking consumption with timeout
                    result = self.redis_client.brpop(self.queue_name, timeout=timeout)

                    if result is not None:
                        # result is (queue_name, task_data) tuple
                        _, task_json = result

                        try:
                            task_data = json.loads(task_json)
                            logger.info(f"Consumed task: {task_data.get('task_id', 'unknown')}")

                            # Execute callback in separate thread to avoid blocking
                            threading.Thread(
                                target=self._execute_task, args=(callback, task_data), daemon=True
                            ).start()

                        except json.JSONDecodeError as e:
                            logger.error(f"Failed to parse task JSON: {e}")
                    else:
                        # Timeout occurred, continue loop
                        continue

                except redis.ConnectionError as e:
                    logger.error(f"Redis connection error: {e}")
                    # Try to reconnect
                    if not self._connect():
                        logger.error("Failed to reconnect to Redis, stopping consumption")
                        break

        except KeyboardInterrupt:
            logger.info("Task consumption stopped by user")
        except Exception as e:
            logger.error(f"Unexpected error in task consumption: {e}")

    def _execute_task(
        self, callback: Callable[[dict[str, Any]], None], task_data: dict[str, Any]
    ) -> None:
        """
        Execute task callback with error handling

        Args:
            callback: Task processing function
            task_data: Task data
        """
        redis_request_id = f"redis-{uuid.uuid4().hex[:12]}"
        task_id = task_data.get("task_id", "unknown")
        structlog.contextvars.bind_contextvars(
            request_id=redis_request_id,
            task_id=task_id,
        )
        try:
            callback(task_data)
        except Exception as e:
            logger.error(f"Error executing task {task_id}: {e}")
        finally:
            structlog.contextvars.clear_contextvars()

    def get_queue_length(self) -> int:
        """Get current queue length"""
        if not self.is_available():
            return 0

        try:
            return self.redis_client.llen(self.queue_name)
        except Exception as e:
            logger.error(f"Failed to get queue length: {e}")
            return 0

    def clear_queue(self) -> bool:
        """Clear all tasks from queue"""
        if not self.is_available():
            return False

        try:
            self.redis_client.delete(self.queue_name)
            logger.info(f"Cleared queue {self.queue_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to clear queue: {e}")
            return False

    def close(self) -> None:
        """Close Redis connection"""
        if self.connection_pool:
            self.connection_pool.disconnect()
        self._connected = False
        logger.info("Redis connection closed")


# Global queue instance
_redis_queue: RedisTaskQueue | None = None


def get_redis_queue() -> RedisTaskQueue | None:
    """Get or create global Redis queue instance"""
    global _redis_queue

    if _redis_queue is None:
        redis_url = os.getenv("REDIS_URL")
        if redis_url:
            _redis_queue = RedisTaskQueue(redis_url)
        else:
            logger.info("REDIS_URL not set, Redis queue disabled")

    return _redis_queue


def publish_task(task_data: dict[str, Any], priority: int = 0) -> bool:
    """
    Convenience function to publish task to Redis queue

    Args:
        task_data: Task data dictionary
        priority: Task priority (higher = higher priority)

    Returns:
        True if task was published successfully
    """
    queue = get_redis_queue()
    if queue:
        return queue.publish_task(task_data, priority)
    return False


def is_redis_available() -> bool:
    """Check if Redis queue is available"""
    queue = get_redis_queue()
    return queue is not None and queue.is_available()
