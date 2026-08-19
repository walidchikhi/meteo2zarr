"""Dask cluster and distributed client lifecycle management."""

import logging
from typing import Any, Optional

logger = logging.getLogger("meteo2zarr.core.dask")


class DaskClusterManager:
    """Manages Dask LocalCluster lifecycle cleanly."""

    def __init__(
        self,
        n_workers: int = 4,
        threads_per_worker: int = 2,
        dashboard_address: str = ":8787",
        memory_limit: str = "auto",
    ) -> None:
        self.n_workers = n_workers
        self.threads_per_worker = threads_per_worker
        self.dashboard_address = dashboard_address
        self.memory_limit = memory_limit
        self.cluster: Optional[Any] = None
        self.client: Optional[Any] = None

    def start(self) -> Any:
        """Start the Dask cluster and return distributed Client."""
        from dask.distributed import Client, LocalCluster

        logger.info(
            "Starting Dask LocalCluster: %d workers, %d threads/worker, dashboard: %s",
            self.n_workers,
            self.threads_per_worker,
            self.dashboard_address,
        )
        self.cluster = LocalCluster(
            n_workers=self.n_workers,
            threads_per_worker=self.threads_per_worker,
            dashboard_address=self.dashboard_address,
            memory_limit=self.memory_limit,
            silence_logs=logging.WARNING,
        )
        self.client = Client(self.cluster)
        logger.info("Dask Dashboard active at: %s", self.client.dashboard_link)
        return self.client

    def close(self) -> None:
        """Close Dask client and cluster safely."""
        if self.client:
            try:
                self.client.close()
            except Exception as e:
                logger.debug("Error closing Dask client: %s", e)
        if self.cluster:
            try:
                self.cluster.close()
            except Exception as e:
                logger.debug("Error closing Dask cluster: %s", e)
        logger.info("Dask cluster closed.")

    def __enter__(self) -> Any:
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
