"""Meteorological accumulation algorithms and sliding window computations."""

import logging
import re
from typing import Dict, List, Optional
import numpy as np
import pandas as pd
import xarray as xr

logger = logging.getLogger("meteo2zarr.processing.accumulations")


class AccumulationProcessor:
    """Handles precipitation decumulation and sliding accumulation windows."""

    def __init__(self, accum_rules: Optional[Dict[str, List[str]]] = None) -> None:
        self.accum_rules = accum_rules or {}

    def compute_sliding_windows(self, ds: xr.Dataset, dt_hours: float = 1.0) -> xr.Dataset:
        """Compute sliding window accumulations using time-aware coordinate matching.
        
        Formula:
            RR_N(T) = Acc(T) - Acc(T - N_hours)
            
        This method supports both uniform (e.g., fixed 1h or 3h) and non-uniform
        forecast timelines (e.g. 1h up to 48h, then 3h beyond 48h).
        """
        if not self.accum_rules or "time" not in ds.dims:
            return ds

        new_vars: Dict[str, xr.DataArray] = {}
        time_coord = ds["time"]

        for src_var, targets in self.accum_rules.items():
            matching_vars = []
            for v in ds.data_vars:
                if v == src_var:
                    matching_vars.append(v)
                elif v.startswith(src_var) and v[len(src_var):].replace(".", "").isdigit():
                    matching_vars.append(v)
                elif ds[v].attrs.get("shortname") == src_var:
                    matching_vars.append(v)

            for v in matching_vars:
                src = ds[v]

                for tgt in targets:
                    m = re.search(r"(\d+)", tgt)
                    if not m:
                        continue
                    hours = int(m.group(1))
                    delta = pd.Timedelta(hours=hours)

                    # Compute target timestamp: T - N hours
                    prev_times = time_coord.values - delta

                    # Check which timestamps have an exact matching predecessor (T - N hours)
                    # Reindex on exact datetime coordinates
                    prev_src = src.reindex(time=prev_times, method=None)
                    
                    # Align time coordinates for exact difference
                    prev_src["time"] = time_coord

                    diff = src - prev_src
                    diff = xr.where(diff < 0, 0.0, diff)

                    # Mask out any NaN / non-available initial windows
                    tgt_id = f"{v}_{hours}h"
                    da_tgt = diff.rename(tgt_id)
                    da_tgt.attrs.update({
                        "units": "kg m-2",
                        "long_name": f"{hours}h Accumulated Precipitation",
                        "shortname": src_var,
                        "level_type": src.attrs.get("level_type", "surface"),
                        "level": src.attrs.get("level", 0.0),
                        "acc_hours": hours,
                        "dt_hours": dt_hours,
                    })

                    new_vars[tgt_id] = da_tgt

        for name, da in new_vars.items():
            ds[name] = da

        return ds
