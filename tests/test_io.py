import pytest
from pathlib import Path
from meteo2zarr.io.base import detect_file_format, list_and_classify_files
from meteo2zarr.io.fa import FAMetaResolver
from meteo2zarr.config import ConfigLoader


def test_format_detection_by_extension(tmp_path):
    nc_file = tmp_path / "test.nc"
    nc_file.touch()
    assert detect_file_format(nc_file) == "netcdf"

    grib_file = tmp_path / "test.grib2"
    grib_file.touch()
    assert detect_file_format(grib_file) == "grib"


def test_list_and_classify_directory(tmp_path):
    f1 = tmp_path / "file_001.nc"
    f2 = tmp_path / "file_002.nc"
    f1.touch()
    f2.touch()

    fmt, files = list_and_classify_files(tmp_path)
    assert fmt == "netcdf"
    assert len(files) == 2


def test_fa_meta_resolver():
    cfg = ConfigLoader()
    resolver = FAMetaResolver(cfg)

    # Test surface temperature field
    meta = resolver.resolve("CLSTEMPERATURE")
    assert meta is not None
    assert meta["shortname"] in ("t2", "2t")
    assert meta["formula"] == "k2c"

    # Test 10m wind field
    meta_wind = resolver.resolve("CLSVENT.ZONAL")
    assert meta_wind is not None
    assert meta_wind["shortname"] in ("u10", "10u")
