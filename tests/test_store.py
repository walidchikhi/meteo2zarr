import pytest
import numpy as np
import pandas as pd
import xarray as xr
from pathlib import Path
import meteo2zarr as m2z


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
    ds["t2"].attrs = {"units": "Celsius", "long_name": "2m Temperature", "level_type": "surface", "level": 2.0}

    store_dir = tmp_path / "model_run"
    store_dir.mkdir()
    surface_zarr = store_dir / "surface.zarr"
    ds.to_zarr(str(surface_zarr), consolidated=True)
    return store_dir


def test_open_and_what_default_file_generation(dummy_zarr_store, tmp_path):
    store = m2z.open(dummy_zarr_store)
    # Default: writes <store_name>.info in current working directory
    store.what(output_dir=tmp_path)

    info_file = tmp_path / f"{dummy_zarr_store.name}.info"
    assert info_file.exists()
    content = info_file.read_text()
    assert "METEO2ZARR INSPECTION: model_run" in content
    assert "2m Temperature" in content


def test_what_stdout_mode(dummy_zarr_store, capsys):
    store = m2z.open(dummy_zarr_store)
    out = store.what(stdout=True)
    captured = capsys.readouterr()
    assert "METEO2ZARR INSPECTION" in captured.out


def test_listfields_and_readfield(dummy_zarr_store):
    store = m2z.open(dummy_zarr_store)
    fields = store.listfields()
    assert "t2" in fields

    da = store.readfield("t2", timestep=0)
    assert da.shape == (10, 10)
    assert da.attrs["units"] == "Celsius"


def test_plot_and_savefig(dummy_zarr_store, tmp_path):
    store = m2z.open(dummy_zarr_store)
    out_png = tmp_path / "t2m_plot.png"
    fig, ax = store.plot("t2", timestep=0, savefig=out_png, use_cartopy=False)
    assert out_png.exists()
    assert out_png.stat().st_size > 0
