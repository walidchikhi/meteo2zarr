"""End-to-End Real FA conversion, Math Integrity, Zero-diff, and CLI tests."""

import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
import numpy as np
import pytest

try:
    import epygram
    HAS_EPYGRAM = True
except ImportError:
    HAS_EPYGRAM = False

import meteo2zarr as m2z
from meteo2zarr.core.converter import NWPConverter

DATA_DIR = Path(__file__).parent / "data"
AROME_DATA = DATA_DIR / "arome"
ALADIN_DATA = DATA_DIR / "aladin"


@pytest.mark.skipif(not HAS_EPYGRAM, reason="epygram required for real FA integrity tests")
def test_arome_real_fa_conversion_and_math_zero_diff(tmp_path):
    """Test AROME real FA conversion, T2 unit conversion, and 3h/6h precipitation decumulation zero-diff."""
    print("\n>>> [1/4] Starting AROME End-to-End Conversion Test on Real FA Data...")
    conv = NWPConverter(output_dir=tmp_path, dask_workers=2, chunk_time=3)
    ok = conv.convert(
        input_dir=AROME_DATA,
        model="arome",
        run_date=datetime(2026, 8, 19, 0),
        fmt="fa",
    )
    assert ok is True, "AROME conversion failed!"
    print("    [OK] AROME conversion completed successfully.")

    store_path = tmp_path / "arome_2026081900"
    assert store_path.exists()
    store = m2z.open(store_path)

    # 1. Test Temperature T2m at timestep 3 (FA CLSTEMPERATURE [K] - 273.15 == Zarr T2 [C])
    print(">>> [2/4] Testing Temperature T2m Mathematical Identity (FA vs Zarr)...")
    zarr_t2 = store.readfield("t2", timestep=3, group="surface").values
    f3 = epygram.formats.resource(str(AROME_DATA / "FULLPOS_2026081900_0003"), "r")
    fa_t2_k = f3.readfield("CLSTEMPERATURE").data.astype(np.float32)
    fa_t2_c = fa_t2_k - np.float32(273.15)
    diff_t2 = np.max(np.abs(zarr_t2 - fa_t2_c))
    print(f"    [OK] T2m Absolute Max Difference = {diff_t2:.10f}")
    assert diff_t2 == 0.0, f"Non-zero diff in T2m: {diff_t2}"

    # 2. Test 3h Decumulated Precipitation at step 3h: FA(t=3) - FA(t=0)
    print(">>> [3/4] Testing 3h Precipitation Decumulation Formula [RR(t=3) - RR(t=0)]...")
    zarr_tp_3h = store.readfield("tp_3h", timestep=0, group="surface_3h").values
    f0 = epygram.formats.resource(str(AROME_DATA / "FULLPOS_2026081900_0000"), "r")
    fa_tp_3 = f3.readfield("SURFACCPLUIE").data.astype(np.float32)
    fa_tp_0 = f0.readfield("SURFACCPLUIE").data.astype(np.float32)
    expected_tp_3h = fa_tp_3 - fa_tp_0
    diff_tp_3h = np.max(np.abs(zarr_tp_3h - expected_tp_3h))
    print(f"    [OK] 3h Precipitation Max Difference = {diff_tp_3h:.10f}")
    assert diff_tp_3h == 0.0, f"Non-zero diff in 3h Precipitation: {diff_tp_3h}"

    # 3. Test 6h Decumulated Precipitation at step 6h: FA(t=6) - FA(t=0)
    print(">>> [4/4] Testing 6h Precipitation Decumulation Formula [RR(t=6) - RR(t=0)]...")
    zarr_tp_6h = store.readfield("tp_6h", timestep=0, group="surface_6h").values
    f6 = epygram.formats.resource(str(AROME_DATA / "FULLPOS_2026081900_0006"), "r")
    fa_tp_6 = f6.readfield("SURFACCPLUIE").data.astype(np.float32)
    expected_tp_6h = fa_tp_6 - fa_tp_0
    diff_tp_6h = np.max(np.abs(zarr_tp_6h - expected_tp_6h))
    print(f"    [OK] 6h Precipitation Max Difference = {diff_tp_6h:.10f}")
    assert diff_tp_6h == 0.0, f"Non-zero diff in 6h Precipitation: {diff_tp_6h}"


@pytest.mark.skipif(not HAS_EPYGRAM, reason="epygram required for real FA integrity tests")
def test_aladin_real_fa_conversion_and_math_zero_diff(tmp_path):
    """Test ALADIN real FA conversion, convective/large-scale decumulations zero-diff."""
    print("\n>>> [1/4] Starting ALADIN End-to-End Conversion Test on Real FA Data...")
    conv = NWPConverter(output_dir=tmp_path, dask_workers=2, chunk_time=3)
    ok = conv.convert(
        input_dir=ALADIN_DATA,
        model="aladin",
        run_date=datetime(2026, 8, 19, 0),
        fmt="fa",
    )
    assert ok is True, "ALADIN conversion failed!"
    print("    [OK] ALADIN conversion completed successfully.")

    store_path = tmp_path / "aladin_2026081900"
    assert store_path.exists()
    store = m2z.open(store_path)

    # 1. Test T2 at step 6
    print(">>> [2/4] Testing ALADIN T2m Identity (FA vs Zarr)...")
    zarr_t2 = store.readfield("t2", timestep=6, group="surface").values
    f6 = epygram.formats.resource(str(ALADIN_DATA / "FULLPOS_2026081900_0006"), "r")
    fa_t2_k = f6.readfield("CLSTEMPERATURE").data.astype(np.float32)
    fa_t2_c = fa_t2_k - np.float32(273.15)
    diff_t2 = np.max(np.abs(zarr_t2 - fa_t2_c))
    print(f"    [OK] ALADIN T2m Absolute Max Difference = {diff_t2:.10f}")
    assert diff_t2 == 0.0, f"Non-zero diff in ALADIN T2: {diff_t2}"

    # 2. Test Convective Precip 3h: SURFPREC.EAU.CON(t=3) - SURFPREC.EAU.CON(t=0)
    print(">>> [3/4] Testing ALADIN Convective 3h Decumulation [CON(t=3) - CON(t=0)]...")
    zarr_con_3h = store.readfield("twatp_con_3h", timestep=0, group="surface_3h").values
    f3 = epygram.formats.resource(str(ALADIN_DATA / "FULLPOS_2026081900_0003"), "r")
    f0 = epygram.formats.resource(str(ALADIN_DATA / "FULLPOS_2026081900_0000"), "r")
    fa_con_3 = f3.readfield("SURFPREC.EAU.CON").data.astype(np.float32)
    fa_con_0 = f0.readfield("SURFPREC.EAU.CON").data.astype(np.float32)
    diff_con_3h = np.max(np.abs(zarr_con_3h - (fa_con_3 - fa_con_0)))
    print(f"    [OK] ALADIN Convective 3h Max Difference = {diff_con_3h:.10f}")
    assert diff_con_3h == 0.0, f"Non-zero diff in ALADIN Convective 3h: {diff_con_3h}"

    # 3. Test Large Scale Precip 6h: SURFPREC.EAU.GEC(t=6) - SURFPREC.EAU.GEC(t=0)
    print(">>> [4/4] Testing ALADIN Large Scale 6h Decumulation [GEC(t=6) - GEC(t=0)]...")
    zarr_gec_6h = store.readfield("twatp_gec_6h", timestep=0, group="surface_6h").values
    fa_gec_6 = f6.readfield("SURFPREC.EAU.GEC").data.astype(np.float32)
    fa_gec_0 = f0.readfield("SURFPREC.EAU.GEC").data.astype(np.float32)
    diff_gec_6h = np.max(np.abs(zarr_gec_6h - (fa_gec_6 - fa_gec_0)))
    print(f"    [OK] ALADIN Large Scale 6h Max Difference = {diff_gec_6h:.10f}")
    assert diff_gec_6h == 0.0, f"Non-zero diff in ALADIN Large Scale 6h: {diff_gec_6h}"


def test_cli_convert_what_plot_commands(tmp_path):
    """Test CLI commands (convert, what, plot) via subprocess invocation."""
    print("\n>>> [1/3] Testing CLI 'meteo2zarr convert'...")
    cmd_conv = [
        sys.executable, "-m", "meteo2zarr.cli", "convert",
        "--model", "arome",
        "--run", "2026081900",
        "--input", str(AROME_DATA),
        "--output", str(tmp_path),
        "--fmt", "fa",
        "--dask-workers", "2",
    ]
    res_conv = subprocess.run(cmd_conv, capture_output=True, text=True)
    assert res_conv.returncode == 0, f"CLI convert failed: {res_conv.stderr}"
    print("    [OK] CLI convert executed successfully.")

    store_path = tmp_path / "arome_2026081900"

    print(">>> [2/3] Testing CLI 'meteo2zarr what'...")
    cmd_what = [
        sys.executable, "-m", "meteo2zarr.cli", "what",
        str(store_path),
        "-o"
    ]
    res_what = subprocess.run(cmd_what, capture_output=True, text=True)
    assert res_what.returncode == 0
    assert "METEO2ZARR INSPECTION: arome_2026081900" in res_what.stdout
    print("    [OK] CLI what executed successfully.")

    print(">>> [3/3] Testing CLI 'meteo2zarr plot' with auto-naming (-O)...")
    cmd_plot = [
        sys.executable, "-m", "meteo2zarr.cli", "plot",
        str(store_path),
        "-f", "t2",
        "--timestep", "3",
        "-O", str(tmp_path)
    ]
    res_plot = subprocess.run(cmd_plot, capture_output=True, text=True)
    assert res_plot.returncode == 0
    generated_pngs = list(tmp_path.glob("*.png"))
    assert len(generated_pngs) > 0
    print(f"    [OK] CLI plot generated figure: {generated_pngs[0].name}")
