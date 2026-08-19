"""Optimized Zarr streaming writer and group partitioner."""

import json
import logging
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional
import numcodecs
import numpy as np
import xarray as xr

from meteo2zarr.config import ConfigLoader

logger = logging.getLogger("meteo2zarr.io.writer")

COMPRESSOR = numcodecs.Blosc(cname="zstd", clevel=3, shuffle=numcodecs.Blosc.SHUFFLE)


class ZarrGroupPartitioner:
    """Partitions unified dataset variables into structured groups defined in zarr_groups.json."""

    def __init__(self, cfg: ConfigLoader) -> None:
        self.groups_config = cfg.zarr_groups.get("groups", {})

    def partition(self, ds: xr.Dataset) -> Dict[str, xr.Dataset]:
        if not self.groups_config:
            return {"surface": ds}

        assigned: Dict[str, List[str]] = {g: [] for g in self.groups_config}
        all_vars = set(ds.data_vars)

        for gname, gcfg in self.groups_config.items():
            match = gcfg.get("match", {})
            exclude = set(match.get("exclude", []))

            ghours = None
            mg = re.search(r"(\d+)h", gname)
            if mg:
                ghours = int(mg.group(1))

            for vname in list(all_vars):
                if vname in exclude:
                    continue

                matched = False
                vhours = ds[vname].attrs.get("acc_hours")
                if ghours is not None and vhours == ghours:
                    matched = True

                if not matched and vname in match.get("parameters", []):
                    matched = True

                if not matched:
                    ltype = ds[vname].attrs.get("level_type", "")
                    if ltype in match.get("level_types", []):
                        if vhours is None or ghours is not None:
                            matched = True

                if not matched and match.get("all"):
                    matched = True

                if matched:
                    assigned[gname].append(vname)

        assigned_all = {v for vs in assigned.values() for v in vs}
        unassigned = all_vars - assigned_all

        if unassigned:
            fallback = "others" if "others" in assigned else "surface" if "surface" in assigned else next(iter(assigned), None)
            if fallback:
                assigned[fallback].extend(list(unassigned))

        result: Dict[str, xr.Dataset] = {}
        for gname, vars_ in assigned.items():
            if not vars_:
                continue
            gds = ds[vars_]
            mg = re.search(r"(\d+)h", gname)
            if mg:
                hours = int(mg.group(1))
                dts = [gds[v].attrs.get("dt_hours", 1.0) for v in gds.data_vars if "dt_hours" in gds[v].attrs]
                dt = dts[0] if dts else 1.0
                steps = round(hours / dt)
                if steps < gds.sizes["time"]:
                    gds = gds.isel(time=slice(steps, None))

            result[gname] = gds
            logger.info("  Group '%s': %d variables", gname, len(gds.data_vars))

        return result


class ZarrWriter:
    """Writes partitioned datasets to cloud-optimized Zarr stores in parallel."""

    def __init__(self, use_pyramids: bool = False, n_threads: int = 4) -> None:
        self.use_pyramids = use_pyramids
        self.n_threads = n_threads

    def write_all(self, group_datasets: Dict[str, xr.Dataset], run_dir: Path) -> None:
        run_dir.mkdir(parents=True, exist_ok=True)
        t0 = time.perf_counter()

        for gname, gds in group_datasets.items():
            self._write_group(gname, gds, run_dir)

        logger.info("Zarr writing completed in %.1fs", time.perf_counter() - t0)

    def _write_group(self, group_name: str, ds: xr.Dataset, run_dir: Path) -> None:
        output_path = run_dir / f"{group_name}.zarr"
        tmp_path = output_path.with_suffix(".zarr.tmp")
        if tmp_path.exists():
            shutil.rmtree(tmp_path)

        ny = ds.dims.get("latitude", 256)
        nx = ds.dims.get("longitude", 256)
        nt = ds.dims.get("time", 1)

        ds = ds.chunk({"time": nt, "latitude": min(256, ny), "longitude": min(256, nx)})

        enc = {}
        for v in ds.data_vars:
            enc[v] = {"compressor": COMPRESSOR}

        ds.to_zarr(
            str(tmp_path),
            mode="w",
            encoding=enc,
            consolidated=True,
        )

        if output_path.exists():
            shutil.rmtree(output_path)
        tmp_path.rename(output_path)

        size_mb = sum(f.stat().st_size for f in output_path.rglob("*") if f.is_file()) / 1e6
        logger.info("  Group '%s' saved: %d vars x %d steps -> %.1f MB", group_name, len(ds.data_vars), nt, size_mb)
