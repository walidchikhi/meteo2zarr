"""Core NWP to Zarr conversion orchestrator."""

import logging
import os
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
import xarray as xr

from meteo2zarr.config import ConfigLoader
from meteo2zarr.core.dask_cluster import DaskClusterManager
from meteo2zarr.io import FAReader, GRIBReader, list_and_classify_files
from meteo2zarr.io.writer import ZarrGroupPartitioner, ZarrWriter
from meteo2zarr.processing.accumulations import AccumulationProcessor
from meteo2zarr.processing.derived import apply_unit_formula, compute_vector_direction, compute_vector_magnitude

logger = logging.getLogger("meteo2zarr.converter")


class NWPConverter:
    """High-performance NWP to Zarr Conversion Engine."""

    def __init__(
        self,
        output_dir: str | Path = "./zarr",
        config_dir: Optional[str | Path] = None,
        dask_workers: int = 4,
        dask_threads: int = 2,
        chunk_time: int = 6,
        write_threads: int = 4,
        read_threads: int = 16,
        dashboard_address: str = "0.0.0.0:8787",
        use_pyramids: bool = False,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.cfg = ConfigLoader(config_dir)
        self.dask_workers = dask_workers
        self.dask_threads = dask_threads
        self.chunk_time = chunk_time
        self.write_threads = write_threads
        self.read_threads = read_threads
        self.dashboard_address = dashboard_address
        self.use_pyramids = use_pyramids

        self.accum_processor = AccumulationProcessor(
            self.cfg.fa_defs.get("accumulations", {})
        )
        self.partitioner = ZarrGroupPartitioner(self.cfg)
        self.writer = ZarrWriter(use_pyramids=self.use_pyramids, n_threads=self.write_threads)

    def convert(
        self,
        input_dir: str | Path,
        model: str,
        run_date: datetime,
        fmt: Optional[str] = None,
        dt_hours: float = 1.0,
    ) -> bool:
        """Run complete conversion workflow for a given model run."""
        input_path = Path(input_dir)
        if not input_path.exists():
            print(f"[ERROR] Input directory does not exist: {input_path}")
            return False

        detected_fmt, files = list_and_classify_files(input_path, explicit_fmt=fmt)
        if not files:
            print(f"[ERROR] No valid data files found in directory: {input_path}")
            return False

        print("=" * 65)
        print(f"METEO2ZARR CONVERSION: {model.upper()} (Run: {run_date.strftime('%Y-%m-%d %H:00 UTC')})")
        print(f"Format: {detected_fmt.upper()} | Total Files: {len(files)} | Output: {self.output_dir}")
        print("=" * 65)

        try:
            # 1. Ingest Dataset with dedicated reader
            ds = self._ingest(files, detected_fmt)
            if ds is None or len(ds.data_vars) == 0:
                print("[ERROR] No variables were ingested.")
                return False

            # 2. Apply Meteorological Transformations (Decumulation & Sliding Windows)
            print("\n[3/4] Calculating precipitation decumulations and derived fields...")
            t_tr = time.perf_counter()
            ds = self._apply_transformations(ds, dt_hours)
            print(f"   [OK] Derived meteorology fields computed in {time.perf_counter() - t_tr:.2f}s")

            # 3. Partition into Groups
            grouped = self.partitioner.partition(ds)

            # 4. Write Grouped Zarr Stores
            run_str = run_date.strftime("%Y%m%d%H")
            run_out_dir = self.output_dir / f"{model}_{run_str}"
            self.writer.write_all(grouped, run_out_dir)

            print("\n" + "=" * 65)
            print(f"SUCCESS: All Zarr groups generated in: {run_out_dir}")
            print("=" * 65 + "\n")
            return True
        except Exception as e:
            logger.exception("Conversion failed: %s", e)
            print(f"\n[ERROR] Conversion failed: {e}")
            return False

    def _ingest(self, files: List[Path], fmt: str) -> Optional[xr.Dataset]:
        """Ingests raw files based on detected/configured format."""
        if fmt in ("fa", "lfa"):
            reader = FAReader(self.cfg, chunk_time=self.chunk_time)
            return reader.read_all(files, n_threads=self.read_threads)
        elif fmt in ("grib", "grib1", "grib2"):
            reader = GRIBReader(self.cfg, chunk_time=self.chunk_time)
            return reader.read_all(files, n_threads=self.read_threads)
        elif fmt in ("netcdf", "nc"):
            try:
                return xr.open_mfdataset(
                    [str(f) for f in files],
                    engine="netcdf4",
                    combine="by_coords",
                    chunks={"time": self.chunk_time},
                )
            except Exception as e:
                logger.error("NetCDF opening failed: %s", e)
                return None
        else:
            logger.error("Unsupported file format: %s", fmt)
            return None

    def _apply_transformations(self, ds: xr.Dataset, dt_hours: float) -> xr.Dataset:
        """Apply accumulations and derived meteorology variables."""
        # 1. Accumulations & Instantaneous Rates via lazy shift
        ds = self.accum_processor.compute_sliding_windows(ds, dt_hours=dt_hours)

        # 2. Derived vector fields (wind speed/dir)
        derived_defs = self.cfg.fa_defs.get("derived_fields", {})
        for out_var, info in derived_defs.items():
            recipe = info.get("recipe", {})
            rtype = recipe.get("type")
            srcs = recipe.get("sources", [])

            if len(srcs) == 2 and srcs[0] in ds and srcs[1] in ds:
                u, v = ds[srcs[0]], ds[srcs[1]]
                if rtype == "vector_magnitude":
                    ds[out_var] = compute_vector_magnitude(u, v)
                    ds[out_var].attrs.update(info)
                elif rtype == "vector_direction":
                    ds[out_var] = compute_vector_direction(u, v)
                    ds[out_var].attrs.update(info)

        return ds
