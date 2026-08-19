"""GRIB1 and GRIB2 format reader using eccodes / cfgrib."""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import dask.array as dsa
import numpy as np
import pandas as pd
import xarray as xr

from meteo2zarr.config import ConfigLoader
from meteo2zarr.io.base import BaseNWPReader
from meteo2zarr.processing.derived import apply_unit_formula

logger = logging.getLogger("meteo2zarr.io.grib")


class GRIBReader(BaseNWPReader):
    """High-performance multi-threaded GRIB1 / GRIB2 reader based on eccodes."""

    def __init__(self, cfg: Optional[ConfigLoader] = None, chunk_time: int = 6) -> None:
        super().__init__(cfg=cfg, chunk_time=chunk_time)
        self.grib_defs = self.cfg.grib_defs.get("fields", {})
        self.g1_map = self.cfg.grib_defs.get("grib1_keys", {})
        self.g2_map = self.cfg.grib_defs.get("grib2_keys", {})
        self.skip_sn = set(self.cfg.grib_defs.get("skip_shortnames", []))
        self.ltype_map = {
            "isobaricInhPa": "isobaric",
            "heightAboveGround": "height",
            "surface": "surface",
            "meanSea": "meanSea",
            "potentialVorticity": "pv",
            "entireAtmosphere": "atmosphere",
            "theta": "theta",
        }

    def read_one(self, file_path: Path) -> Optional[xr.Dataset]:
        return self.read_all([file_path])

    def read_all(self, files: List[Path], n_threads: int = 8) -> Optional[xr.Dataset]:
        try:
            import eccodes
        except ImportError:
            raise RuntimeError("eccodes is required for GRIB reading. Install via conda or pip.")

        buckets: Dict[tuple, Dict[str, Any]] = {}
        for fpath in sorted(files):
            self._read_single_grib(fpath, buckets)

        if not buckets:
            logger.warning("No GRIB messages decoded from %d files", len(files))
            return None

        return self._build_dataset(buckets)

    def _read_single_grib(self, fpath: Path, buckets: Dict[tuple, Dict[str, Any]]) -> None:
        import eccodes

        try:
            f = open(str(fpath), "rb")
        except OSError as e:
            logger.warning("Failed to open %s: %s", fpath.name, e)
            return

        try:
            while True:
                msg = eccodes.codes_grib_new_from_file(f)
                if msg is None:
                    break
                try:
                    self._process_message(msg, buckets)
                finally:
                    eccodes.codes_release(msg)
        finally:
            f.close()

    def _process_message(self, msg: Any, buckets: Dict[tuple, Dict[str, Any]]) -> None:
        import eccodes

        edition = eccodes.codes_get(msg, "edition", ktype=int)
        sn_grib = None
        if edition == 2:
            disc = eccodes.codes_get(msg, "discipline", ktype=int)
            cat = eccodes.codes_get(msg, "parameterCategory", ktype=int)
            num = eccodes.codes_get(msg, "parameterNumber", ktype=int)
            sn_grib = self.g2_map.get(f"{disc}.{cat}.{num}")
        else:
            param = str(eccodes.codes_get(msg, "indicatorOfParameter", ktype=int))
            sn_grib = self.g1_map.get(param)

        if not sn_grib:
            try:
                sn_grib = eccodes.codes_get(msg, "shortName", ktype=str)
            except Exception:
                return

        if not sn_grib or sn_grib in self.skip_sn:
            return

        field_def = self.grib_defs.get(sn_grib)
        if not field_def:
            return

        shortname_std = field_def["shortname"]
        formula = field_def.get("formula", "None")
        units_std = field_def.get("unit", "unknown")
        desc_std = field_def.get("desc", sn_grib)

        try:
            ltype_grib = eccodes.codes_get(msg, "typeOfLevel", ktype=str)
            level_val = eccodes.codes_get(msg, "level", ktype=int)
        except Exception:
            ltype_grib = "surface"
            level_val = 0

        ltype_std = self.ltype_map.get(ltype_grib, "surface")

        try:
            date_int = eccodes.codes_get(msg, "dataDate", ktype=int)
            time_int = eccodes.codes_get(msg, "dataTime", ktype=int)
            step_h = str(eccodes.codes_get(msg, "stepRange", ktype=str))
            step_end = int(step_h.split("-")[-1]) if step_h else 0

            base_time = pd.Timestamp(
                year=date_int // 10000,
                month=(date_int % 10000) // 100,
                day=date_int % 100,
                hour=time_int // 100,
                minute=time_int % 100,
            )
            valid_time = base_time + pd.Timedelta(hours=step_end)
        except Exception:
            valid_time = pd.Timestamp("1970-01-01")

        try:
            values = eccodes.codes_get_values(msg).astype(np.float32)
            ni = eccodes.codes_get(msg, "Ni", ktype=int)
            nj = eccodes.codes_get(msg, "Nj", ktype=int)
            lats_flat = eccodes.codes_get_array(msg, "latitudes")
            lons_flat = eccodes.codes_get_array(msg, "longitudes")
            arr = values.reshape(nj, ni)
            lats_2d = lats_flat.reshape(nj, ni)
            lons_2d = lons_flat.reshape(nj, ni)
        except Exception:
            return

        lat_1d = lats_2d[:, 0]
        lon_1d = lons_2d[0, :]

        # Unit conversion formula
        arr_da = xr.DataArray(arr)
        arr = apply_unit_formula(arr_da, formula).values

        key = (shortname_std, ltype_std, level_val)
        if key not in buckets:
            buckets[key] = {
                "times": [],
                "arrays": [],
                "lat": lat_1d,
                "lon": lon_1d,
                "units": units_std,
                "desc": desc_std,
                "ltype": ltype_std,
                "level": level_val,
            }
        buckets[key]["times"].append(valid_time)
        buckets[key]["arrays"].append(arr)

    def _build_dataset(self, buckets: Dict[tuple, Dict[str, Any]]) -> xr.Dataset:
        data_vars: Dict[str, xr.DataArray] = {}

        for key, b in buckets.items():
            sn_std, ltype_std, lv = key
            lats, lons = b["lat"], b["lon"]

            if ltype_std in ("isobaric", "pv") and lv > 0:
                var_name = f"{sn_std}{lv}"
            elif lv > 0 and str(lv) not in sn_std:
                var_name = f"{sn_std}{lv}"
            else:
                var_name = sn_std

            times_sorted = sorted(set(b["times"]))
            nt = len(times_sorted)
            time_idx = {t: i for i, t in enumerate(times_sorted)}

            ny, nx = len(lats), len(lons)
            arr_3d = np.full((nt, ny, nx), np.nan, dtype=np.float32)

            for t, a in zip(b["times"], b["arrays"]):
                arr_3d[time_idx[t]] = a

            da = xr.DataArray(
                dsa.from_array(arr_3d, chunks=(min(nt, self.chunk_time), ny, nx)),
                dims=("time", "latitude", "longitude"),
                coords={
                    "time": pd.DatetimeIndex(times_sorted),
                    "latitude": lats.astype(np.float64),
                    "longitude": lons.astype(np.float64),
                },
                name=var_name,
                attrs={
                    "units": b["units"],
                    "long_name": b["desc"],
                    "level_type": ltype_std,
                    "level": float(lv),
                    "shortname": sn_std,
                },
            )
            data_vars[var_name] = da

        ds = xr.Dataset(data_vars)
        return ds.sortby("time")
