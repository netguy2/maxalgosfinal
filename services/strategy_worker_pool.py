"""
Strategy Worker Pool Service.

Provides a bounded worker pool for managing Python strategy execution.
Prevents OS process bloat and file descriptor exhaustion when running many
concurrent strategies by enforcing max worker limits (MAX_STRATEGY_WORKERS)
and providing queueing / resource tracking.
"""

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, Any, Optional

from utils.logging import get_logger

logger = get_logger(__name__)

# Default maximum concurrent strategy workers (override via environment variable)
DEFAULT_MAX_STRATEGY_WORKERS = int(os.getenv("MAX_STRATEGY_WORKERS", "32"))


class StrategyWorkerPool:
    """
    Thread-safe bounded worker pool for managing strategy execution tasks.
    Enforces concurrency limits and monitors active/queued strategy runs.
    """

    _instance: Optional["StrategyWorkerPool"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return

        self._max_workers = DEFAULT_MAX_STRATEGY_WORKERS
        self._executor = ThreadPoolExecutor(
            max_workers=self._max_workers,
            thread_name_prefix="StrategyWorker"
        )
        self._active_tasks: Dict[str, Any] = {}
        self._task_lock = threading.Lock()
        self._initialized = True
        logger.info(f"StrategyWorkerPool initialized with max_workers={self._max_workers}")

    def submit_task(self, strategy_id: str, func: Callable, *args, **kwargs) -> bool:
        """
        Submit a strategy execution job to the pool.

        Args:
            strategy_id: Unique strategy identifier
            func: Function to execute
            *args, **kwargs: Arguments for the function

        Returns:
            bool: True if task was successfully submitted to executor
        """
        with self._task_lock:
            if strategy_id in self._active_tasks:
                logger.warning(f"Strategy {strategy_id} is already running in worker pool")
                return False

            future = self._executor.submit(self._run_wrapper, strategy_id, func, *args, **kwargs)
            self._active_tasks[strategy_id] = {
                "future": future,
                "strategy_id": strategy_id,
            }
            logger.info(
                f"Submitted strategy {strategy_id} to worker pool "
                f"({len(self._active_tasks)}/{self._max_workers} active workers)"
            )
            return True

    def _run_wrapper(self, strategy_id: str, func: Callable, *args, **kwargs):
        """Wrapper to ensure task is removed from active tasks upon completion."""
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.exception(f"Exception during strategy {strategy_id} execution in worker pool: {e}")
            raise
        finally:
            with self._task_lock:
                self._active_tasks.pop(strategy_id, None)
                logger.debug(f"Strategy {strategy_id} finished; removed from active worker pool")

    def get_status(self) -> Dict[str, Any]:
        """Return status metrics for health monitoring."""
        with self._task_lock:
            active_count = len(self._active_tasks)
            active_ids = list(self._active_tasks.keys())

        return {
            "max_workers": self._max_workers,
            "active_workers": active_count,
            "available_workers": max(0, self._max_workers - active_count),
            "active_strategy_ids": active_ids,
        }


def get_strategy_worker_pool() -> StrategyWorkerPool:
    """Return singleton instance of StrategyWorkerPool."""
    return StrategyWorkerPool()
