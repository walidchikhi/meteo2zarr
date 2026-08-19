import pytest
import numpy as np
import pandas as pd
import xarray as xr
from meteo2zarr.processing.accumulations import AccumulationProcessor
from meteo2zarr.processing.derived import (
    compute_vector_magnitude,
    compute_vector_direction,
    apply_unit_formula,
)


@pytest.fixture
def sample_precip_dataset():
    times = pd.date_range("2026-03-01 00:00", periods=5, freq="1h")
    # Cumulative precipitation: 0, 2, 5, 5, 10 mm
    tp_data = np.array([0.0, 2.0, 5.0, 5.0, 10.0])
    
    ds = xr.Dataset(
        data_vars={"tp": (["time"], tp_data)},
        coords={"time": times},
    )
    return ds


def test_sliding_window_accumulation(sample_precip_dataset):
    rules = {"tp": ["RR3h"]}
    processor = AccumulationProcessor(rules)
    res = processor.compute_sliding_windows(sample_precip_dataset, dt_hours=1.0)

    assert "tp_3h" in res.data_vars
    # 3-step shift diff of [0, 2, 5, 5, 10] with shift 3:
    # idx 3: tp[3] - tp[0] = 5 - 0 = 5
    # idx 4: tp[4] - tp[1] = 10 - 2 = 8
    assert res["tp_3h"].isel(time=3).values == 5.0
    assert res["tp_3h"].isel(time=4).values == 8.0


def test_vector_wind_calculations():
    u = xr.DataArray(np.array([3.0, 0.0, -3.0]))
    v = xr.DataArray(np.array([4.0, -5.0, 0.0]))

    ws = compute_vector_magnitude(u, v)
    np.testing.assert_allclose(ws.values, [5.0, 5.0, 3.0])

    wdir = compute_vector_direction(u, v)
    assert len(wdir) == 3


def test_unit_formulas():
    t_kelvin = xr.DataArray(np.array([273.15, 300.15]))
    t_celsius = apply_unit_formula(t_kelvin, "k2c")
    np.testing.assert_allclose(t_celsius.values, [0.0, 27.0])
