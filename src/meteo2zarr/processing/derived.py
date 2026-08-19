"""Formulas and meteorological derived fields (wind vectors, potential temperature, etc.)."""

import logging
import numpy as np
import xarray as xr
from typing import Dict, Any

logger = logging.getLogger("meteo2zarr.processing.derived")


def compute_vector_magnitude(u: xr.DataArray, v: xr.DataArray) -> xr.DataArray:
    """Compute wind speed / vector magnitude: sqrt(u^2 + v^2)."""
    return np.sqrt(u ** 2 + v ** 2)


def compute_vector_direction(u: xr.DataArray, v: xr.DataArray) -> xr.DataArray:
    """Compute meteorological wind direction in degrees (0=North, 90=East)."""
    rad = np.arctan2(-u, -v)
    deg = np.degrees(rad)
    return (deg + 360.0) % 360.0


def apply_unit_formula(da: xr.DataArray, formula: str) -> xr.DataArray:
    """Convert physical units based on standard formula keys."""
    if not formula or formula.lower() in ("none", "null", ""):
        return da

    f = formula.lower()
    if f == "k2c":  # Kelvin to Celsius
        res = da - 273.15
        res.attrs.update(da.attrs)
        res.attrs["unit"] = "Celsius"
        return res
    elif f == "pa2hpa":  # Pascals to Hectopascals
        res = da / 100.0
        res.attrs.update(da.attrs)
        res.attrs["unit"] = "hPa"
        return res
    elif f == "percent":  # Fractional [0-1] to Percentage [0-100]
        # Only scale if max <= 1.05 to prevent double scaling
        max_val = float(da.max().compute()) if hasattr(da.data, "compute") else float(da.max())
        if max_val <= 1.05:
            res = da * 100.0
        else:
            res = da
        res.attrs.update(da.attrs)
        res.attrs["unit"] = "%"
        return res
    return da
