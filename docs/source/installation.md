# Installation

## Requirements

- Python: >= 3.9 (recommended 3.10 or 3.11)
- Core Dependencies: `xarray`, `zarr`, `dask`, `distributed`, `numpy`, `pandas`, `pyyaml`, `numcodecs`, `matplotlib`, `cartopy`
- Optional NWP Engines:
  - `epygram` (for FA / LFA format decoding)
  - `eccodes` (for GRIB1 / GRIB2 format decoding)

---

## 1. Installation via Python Virtual Environment (venv)

This is the standard and recommended installation method:

```bash
# Create and activate virtual environment
python3 -m venv meteo2zarr_env
source meteo2zarr_env/bin/activate

# Install meteo2zarr
pip install meteo2zarr
```

### System Libraries (Debian / Ubuntu / HPC Linux):
If compiling or binding NWP decoders (`eccodes`, `cartopy`, `epygram`) inside `venv`:
```bash
sudo apt-get update && sudo apt-get install -y libeccodes-dev libgeos-dev libproj-dev
pip install eccodes cartopy epygram
```

---

## 2. Alternative Installation via Conda / Mamba

For standalone environments with pre-compiled C-binaries:

```bash
# Create dedicated conda environment
conda create -n meteo2zarr -c conda-forge python=3.10 eccodes cartopy epygram
conda activate meteo2zarr

# Install meteo2zarr
pip install meteo2zarr
```

---

## 3. Development and Documentation Build

To contribute or build the documentation locally:

```bash
git clone https://github.com/walidchikhi/meteo2zarr.git
cd meteo2zarr
python3 -m venv dev_env
source dev_env/bin/activate
pip install -e ".[dev,docs]"
```
