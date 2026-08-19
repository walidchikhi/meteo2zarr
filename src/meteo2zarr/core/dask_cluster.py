"""Dask cluster and distributed client lifecycle management."""

import logging
import socket
from typing import Any, Optional

logger = logging.getLogger("meteo2zarr.core.dask")


def _get_host_ip() -> str:
    """Get the primary local IP address of this machine."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class DaskClusterManager:
    """Manages Dask LocalCluster lifecycle cleanly."""

    def __init__(
        self,
        n_workers: int = 4,
        threads_per_worker: int = 2,
        dashboard_address: str = "0.0.0.0:8787",
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
            "Starting Dask Cluster: %d workers, %d threads/worker, dashboard listening on %s",
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

        host_ip = _get_host_ip()
        dash_port = self.cluster.dashboard_link.split(":")[-1].split("/")[0]
        logger.info("=" * 60)
        logger.info("DASK DASHBOARD ACTIVE AT:")
        logger.info("   Local URL  : http://localhost:%s/status", dash_port)
        logger.info("   Network URL: http://%s:%s/status", host_ip, dash_port)
        logger.info("=" * 60)
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
