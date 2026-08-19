"""FA/LFA format reader using epygram and multiprocessing."""

import json
import logging
import os
import re
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import dask.array as da
import numpy as np
import xarray as xr

from meteo2zarr.config import ConfigLoader
from meteo2zarr.io.base import BaseNWPReader
from meteo2zarr.processing.derived import apply_unit_formula

logger = logging.getLogger("meteo2zarr.io.fa")


class FAMetaResolver:
    """Resolves FA field identifiers against fa_definitions.json."""

    def __init__(self, cfg: ConfigLoader) -> None:
        self.fields = cfg.fa_defs.get("fields", {})
        self.levels = cfg.fa_defs.get("levels", {})
        self.skip_fields = set(cfg.fa_defs.get("skip_fields", []))
        self.cfg = cfg

    def resolve(self, fa_id: str) -> Optional[Dict[str, Any]]:
        for pattern in self.skip_fields:
            if pattern in fa_id or re.search(pattern, fa_id):
                return None

        if fa_id in self.fields:
            m = self.fields[fa_id]
            return self._build(m, "surface", 0)

        level_type, level_val, suffix = self._parse_level(fa_id)
        norm = suffix.replace(".", "_")
        for fs, meta in self.fields.items():
            nfs = fs.replace(".", "_")
            if norm.endswith(nfs) or nfs == norm:
                return self._build(meta, level_type, level_val)

        return {
            "shortname": fa_id.lower().replace(".", "_"),
            "unit": "unknown",
            "formula": "None",
            "description": f"Field {fa_id}",
            "level_type": level_type,
            "level_value": level_val,
        }

    def _parse_level(self, fa_id: str) -> Tuple[str, float, str]:
        prefixes = sorted(self.levels.keys(), key=len, reverse=True)
        for prefix in prefixes:
            if not fa_id.startswith(prefix):
                continue
            info = self.levels[prefix]
            m = re.match(rf"{prefix}(\d+)(.*)", fa_id)
            if m:
                val = int(m.group(1)) * info.get("factor", 1)
                return info["type"], val, m.group(2)
            if prefix in ("CLS", "SURF"):
                suffix = fa_id[len(prefix):]
                ltype = info["type"]
                lval = 2.0 if ("TEMPERATURE" in fa_id or "HUMI" in fa_id) else (10.0 if "VENT" in fa_id else 0.0)
                return ltype, lval, suffix
        return "unknown", 0.0, fa_id

    def _build(self, meta: dict, level_type: str, level_val: float) -> dict:
        return {
            "shortname": meta["shortname"],
            "unit": meta.get("unit", "unknown"),
            "formula": meta.get("formula", "None"),
            "description": meta.get("desc", meta["shortname"]),
            "level_type": level_type,
            "level_value": level_val,
        }


def _read_fa_process_job(fa_path: Path, cfg: ConfigLoader) -> Optional[xr.Dataset]:
    """Isolated task executed inside a ProcessPool worker."""
    reader = FAReader(cfg=cfg)
    return reader.read_one(fa_path)


class FAReader(BaseNWPReader):
    """High-performance reader for FA / LFA meteorological files."""

    def __init__(self, cfg: Optional[ConfigLoader] = None, chunk_time: int = 6) -> None:
        super().__init__(cfg=cfg, chunk_time=chunk_time)
        self.resolver = FAMetaResolver(self.cfg)

    def read_one(self, fa_path: Path) -> Optional[xr.Dataset]:
        """Read a single FA file timestep into an xr.Dataset."""
        try:
            import epygram
            epygram.init_env()
        except ImportError:
            raise RuntimeError("epygram is required for FA format reading. Install via conda or pip.")

        warnings.filterwarnings("ignore", category=RuntimeWarning, module="numpy.ma.core")

        try:
            res = epygram.formats.resource(str(fa_path), "r")
            field_list = res.listfields()
            if not field_list:
                res.close()
                return None

            sample = res.readfield(field_list[0])
            validity_dt = sample.validity.get()

            lons, lats = sample.geometry.get_lonlat_grid()
            lat_1d = lats[:, 0] if not np.all(lats[:, 0] == lats[0, 0]) else lats[0, :]
            lon_1d = lons[0, :] if not np.all(lons[0, :] == lons[0, 0]) else lons[:, 0]

            data_vars: Dict[str, xr.DataArray] = {}

            for f_id in field_list:
                meta = self.resolver.resolve(f_id)
                if not meta:
                    continue

                field = res.readfield(f_id)
                data = field.getdata().astype(np.float32)

                var_key = meta["shortname"]
                if meta["level_type"] in ("isobaric", "height", "pv"):
                    if meta["level_value"] != 0 or meta["level_type"] == "isobaric":
                        var_key = f"{meta['shortname']}{int(meta['level_value'])}"

                arr = da.from_array(data[np.newaxis, ...], chunks=(1, -1, -1))
                da_ = xr.DataArray(
                    arr,
                    coords={"time": [validity_dt], "latitude": lat_1d, "longitude": lon_1d},
                    dims=["time", "latitude", "longitude"],
                    name=var_key,
                )
                da_ = apply_unit_formula(da_, meta["formula"])
                da_.attrs.update({
                    "units": meta["unit"],
                    "long_name": meta["description"],
                    "fa_name": f_id,
                    "level_type": meta["level_type"],
                    "level_value": meta["level_value"],
                    "shortname": meta["shortname"],
                })

                data_vars[var_key] = da_

            res.close()
            return xr.Dataset(data_vars) if data_vars else None

        except Exception as e:
            logger.warning("Error reading FA file %s: %s", fa_path.name, e)
            return None

    def read_all(self, files: List[Path], n_threads: int = 16) -> Optional[xr.Dataset]:
        """Read all FA files in parallel via ProcessPoolExecutor and concatenate on time."""
        results: Dict[Path, xr.Dataset] = {}
        t0 = time.perf_counter()
        total_files = len(files)
        workers_count = min(total_files, n_threads)

        logger.info("Reading %d FA files using %d parallel worker processes...", total_files, workers_count)
        
        completed_count = 0
        with ProcessPoolExecutor(max_workers=workers_count) as pool:
            future_to_path = {pool.submit(_read_fa_process_job, fp, self.cfg): fp for fp in files}
            for future in as_completed(future_to_path):
                fp = future_to_path[future]
                completed_count += 1
                try:
                    ds = future.result()
                    if ds is not None:
                        results[fp] = ds
                except Exception as e:
                    logger.warning("Worker failure on %s: %s", fp.name, e)

                if completed_count % 10 == 0 or completed_count == total_files:
                    logger.info("  Progress: %d/%d files read (%.1fs elapsed)", completed_count, total_files, time.perf_counter() - t0)

        logger.info("Parallel FA reading finished in %.2fs", time.perf_counter() - t0)
        if not results:
            return None

        datasets = [results[fp] for fp in sorted(results.keys())]
        logger.info("Merging %d time slices into unified dataset...", len(datasets))

        merged = xr.concat(datasets, dim="time", data_vars="all", compat="override", coords="minimal")
        merged = merged.sortby("time")
        _, idx = np.unique(merged.time.values, return_index=True)
        return merged.isel(time=idx)
