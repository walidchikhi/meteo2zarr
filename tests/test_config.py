from meteo2zarr.config import ConfigLoader


def test_config_loader_default():
    loader = ConfigLoader()
    assert "fields" in loader.fa_defs
    assert "fields" in loader.grib_defs
    assert "groups" in loader.zarr_groups
    assert len(loader.fa_defs["fields"]) > 0
    assert len(loader.grib_defs["fields"]) > 0
