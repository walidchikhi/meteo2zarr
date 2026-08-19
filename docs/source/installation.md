# Installation

## Requirements

- **Python**: `>= 3.9` (recommended `3.10` or `3.11`)
- **Core Dependencies**: `xarray`, `zarr`, `dask`, `distributed`, `numpy`, `pandas`, `pyyaml`, `numcodecs`, `matplotlib`, `cartopy`
- **Optional NWP Engines**:
  - `epygram` (for FA / LFA format decoding)
  - `eccodes` / `cfgrib` (for GRIB1 / GRIB2 format decoding)

## Basic Installation via Pip

```bash
pip install meteo2zarr
```

## Installation with Full NWP Backends (Conda / Mamba recommended)

Because meteorological binaries (`libeccodes`, `gdal`, `geos`) require C libraries:

```bash
# Create dedicated conda environment
conda create -n meteo2zarr -c conda-forge python=3.10 eccodes cfgrib cartopy epygram
conda activate meteo2zarr

# Install meteo2zarr in editable mode or from PyPI
pip install meteo2zarr
```

## Installing for Development and Documentation

```bash
git clone https://github.com/walidchikhi/meteo2zarr.git
cd meteo2zarr
pip install -e ".[dev,docs]"
```
