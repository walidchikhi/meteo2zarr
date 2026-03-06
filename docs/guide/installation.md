# Installation Guide

To run the NWP to Zarr converter on the HPC cluster, you need a Python 3.12+ environment with specific dependencies.

## Shared Virtual Environment

A pre-configured virtual environment is available on the shared filesystem. This environment is already patched to work across both login and compute nodes.

- **Path**: `/fennecData/home/pnt/metview/Prod/scr2/venv_zarr`
- **Python**: `3.12`

To test the environment:
```bash
./venv_zarr/bin/python3.12 -c "import numpy, xarray, zarr, dask; print('✅ Environment OK')"
```

## Creating a New Environment

If you need to create a new environment:

1.  **Initialize a venv** using a shared Python binary (e.g., from Miniconda):
    ```bash
    /fennecData/home/pnt/miniconda3/envs/chikhiw/bin/python3.12 -m venv my_nwp_venv
    ```

2.  **Install dependencies**:
    ```bash
    source my_nwp_venv/bin/activate
    pip install numpy xarray zarr dask[complete] epygram eccodes fsspec partd toolz cloudpickle locket
    ```

3.  **Patch for HPC**:
    If your environment fails on compute nodes because of local paths, ensure you are using absolute paths to a shared Python binary in the `bin/python3*` symlinks.

## Dependencies

| Library | Version | Purpose |
| :--- | :--- | :--- |
| `epygram` | Latest | Reading FA/LFA files |
| `xarray` | Latest | Data manipulation and Zarr interface |
| `zarr` | ^2.16 | Cloud-optimized storage format |
| `dask` | Latest | Parallel computation and streaming |
| `eccodes` | Latest | GRIB decoding (if needed) |
