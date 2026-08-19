import pytest
import numpy as np
import pandas as pd
import xarray as xr
from pathlib import Path
from meteo2zarr import open_zarr, MeteoZarr


@pytest.fixture
def dummy_zarr_store(tmp_path):
    times = pd.date_range("2026-08-19 00:00", periods=3, freq="1h")
    lats = np.linspace(30.0, 40.0, 10)
    lons = np.linspace(0.0, 10.0, 10)
    t2m = np.random.rand(3, 10, 10).astype(np.float32)

    ds = xr.Dataset(
        data_vars={"t2": (["time", "latitude", "longitude"], t2m)},
        coords={"time": times, "latitude": lats, "longitude": lons},
        attrs={"model": "test"},
    )
    ds["t2"].attrs = {"units": "Celsius", "long_name": "2m Temperature", "level_type": "surface"}

    store_dir = tmp_path / "model_run"
    store_dir.mkdir()
    surface_zarr = store_dir / "surface.zarr"
    ds.to_zarr(str(surface_zarr), consolidated=True)
    return store_dir


def test_open_and_what(dummy_zarr_store):
    store = open_zarr(dummy_zarr_store)
    info = store.what(verbose=False)

    assert "surface" in info
    assert "t2" in info["surface"]["variables"]
    assert info["surface"]["n_timesteps"] == 3


def test_listfields_and_readfield(dummy_zarr_store):
    store = open_zarr(dummy_zarr_store)
    fields = store.listfields()
    assert "t2" in fields

    da = store.readfield("t2", timestep=0)
    assert da.shape == (10, 10)
    assert da.attrs["units"] == "Celsius"


def test_plot_and_save(dummy_zarr_store, tmp_path):
    store = open_zarr(dummy_zarr_store)
    out_png = tmp_path / "t2m_plot.png"
    fig, ax = store.plot("t2", timestep=0, savefig=out_png)
    assert out_png.exists()
    assert out_png.stat().st_size > 0
