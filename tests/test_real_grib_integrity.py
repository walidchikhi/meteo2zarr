"""End-to-End Real GRIB conversion, Math Integrity, Zero-diff, and Plotting tests."""

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
import numpy as np
import pytest

try:
    import eccodes
    HAS_ECCODES = True
except ImportError:
    HAS_ECCODES = False

import meteo2zarr as m2z
from meteo2zarr.core.converter import NWPConverter

DATA_DIR = Path(__file__).parent / "data"
GRIB_DATA = DATA_DIR / "grib"


@pytest.mark.skipif(not HAS_ECCODES, reason="eccodes required for real GRIB integrity tests")
def test_grib_real_conversion_and_math_zero_diff(tmp_path):
    """Test GRIB conversion, unit formula (2t Kelvin->Celsius), and wind vector extraction."""
    print("\n>>> [1/4] Starting GRIB End-to-End Conversion Test on Real GRIB Data...")
    conv = NWPConverter(output_dir=tmp_path, dask_workers=2, chunk_time=3)
    ok = conv.convert(
        input_dir=GRIB_DATA,
        model="arome",
        run_date=datetime(2025, 10, 22, 0),
        fmt="grib",
    )
    assert ok is True, "GRIB conversion failed!"
    print("    [OK] GRIB conversion completed successfully.")

    store_path = tmp_path / "arome_2025102200"
    assert store_path.exists()
    store = m2z.open(store_path)

    # Inspect the store
    info = store.what(stdout=True)
    assert "2t" in info
    assert "10u" in info
    assert "10v" in info

    # Test mathematical identity with ecCodes
    grb_file_3 = GRIB_DATA / "grib_2025102200_0003"
    with open(grb_file_3, "rb") as f:
        while True:
            gid = eccodes.codes_grib_new_from_file(f)
            if gid is None:
                break
            sname = eccodes.codes_get(gid, "shortName")
            vals = eccodes.codes_get_values(gid).reshape(400, 400).astype(np.float32)

            if sname == "2t":
                print(">>> [2/4] Testing GRIB 2t Temperature Identity (GRIB vs Zarr)...")
                z_val = store.readfield("2t", timestep=3).values
                expected = vals - np.float32(273.15)
                diff = np.max(np.abs(z_val - expected))
                print(f"    [OK] GRIB 2t Absolute Max Difference = {diff:.10f}")
                assert diff == 0.0, f"Non-zero diff in GRIB 2t: {diff}"

            elif sname == "10u":
                print(">>> [3/4] Testing GRIB 10u Wind Identity (GRIB vs Zarr)...")
                z_val = store.readfield("10u", timestep=3).values
                diff = np.max(np.abs(z_val - vals))
                print(f"    [OK] GRIB 10u Absolute Max Difference = {diff:.10f}")
                assert diff == 0.0, f"Non-zero diff in GRIB 10u: {diff}"

            elif sname == "10v":
                print(">>> [4/4] Testing GRIB 10v Wind Identity (GRIB vs Zarr)...")
                z_val = store.readfield("10v", timestep=3).values
                diff = np.max(np.abs(z_val - vals))
                print(f"    [OK] GRIB 10v Absolute Max Difference = {diff:.10f}")
                assert diff == 0.0, f"Non-zero diff in GRIB 10v: {diff}"

            eccodes.codes_release(gid)

    # Test plotting wind vector from GRIB store
    out_wind = tmp_path / "grib_wind.png"
    fig, ax = store.plot(wu="10u", wv="10v", timestep=3, savefig=out_wind, use_cartopy=True)
    assert out_wind.exists()
    assert out_wind.stat().st_size > 0
