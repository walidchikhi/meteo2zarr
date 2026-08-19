# NWP Conversion

The conversion engine transforms heterogeneous model output files into unified, partitioned, CF-compliant Zarr groups.

## CLI Usage

```bash
meteo2zarr convert \
  --model aladin \
  --run 2026081900 \
  --input /path/to/nwp/data \
  --output ./zarr_output \
  --fmt fa \
  --dask-workers 4 \
  --dask-threads 2 \
  --chunk-time 6 \
  --read-threads 16 \
  --write-threads 4
```

### CLI Parameters Reference

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `--model` | `str` | *Required* | NWP Model name (e.g. `arome`, `aladin`, `arpege`, `gfs`). |
| `--run` | `str` | *Required* | Model run timestamp in `YYYYMMDDHH` format (e.g. `2026081900`). |
| `--input` | `str` | *Required* | Directory containing the raw input files. |
| `--output` | `str` | `./zarr` | Destination directory for the generated Zarr store. |
| `--fmt` | `str` | `auto` | Force format: `fa`, `lfa`, `grib`, `grib1`, `grib2`, `netcdf`. |
| `--dt-hours` | `float` | `1.0` | Time delta between forecast steps (in hours). |
| `--dask-workers` | `int` | `4` | Number of parallel Dask worker processes. |
| `--dask-threads` | `int` | `2` | Number of threads per Dask worker. |
| `--chunk-time` | `int` | `6` | Time chunk dimension for Zarr storage. |
| `--read-threads` | `int` | `16` | Multiprocessing pool size for reading raw input files. |
| `--write-threads`| `int` | `4` | Thread pool size for writing Zarr groups concurrently. |
| `--dashboard-address` | `str` | `0.0.0.0:8787` | IP:Port to bind Dask monitoring dashboard. |

---

## Python API Usage

```python
from datetime import datetime
from meteo2zarr.core.converter import NWPConverter

converter = NWPConverter(
    output_dir="./output_zarr",
    dask_workers=4,
    dask_threads=2,
    chunk_time=6,
    read_threads=16,
    write_threads=4,
    dashboard_address="0.0.0.0:8787",
)

success = converter.convert(
    input_dir="/data/models/aladin/2026081900",
    model="aladin",
    run_date=datetime(2026, 8, 19, 0),
    fmt="fa",
    dt_hours=1.0,
)
```

---

## Partitioned Zarr Group Architecture

`meteo2zarr` automatically splits variables into optimized groups defined in `zarr_groups.json`:

- **`surface.zarr`**: Instantaneous 2D surface parameters (`t2`, `u10`, `v10`, `ps`, `q2`, `totcc`).
- **`surface_3h.zarr`**: 3-hour sliding window decumulated precipitation (`tp_3h`, `twatp_con_3h`, `twatp_gec_3h`).
- **`surface_6h.zarr`**: 6-hour sliding window decumulated precipitation.
- **`surface_12h.zarr`**: 12-hour sliding window decumulated precipitation.
- **`surface_24h.zarr`**: 24-hour daily accumulated precipitation.
- **`alt_pressure.zarr`**: Upper-air variables on standard pressure levels (`gh`, `t`, `r`, `u`, `v`, `w` at 1000, 925, 850, 700, 500, 300, 200 hPa).
- **`alt_pv.zarr`**: Potential vorticity levels (e.g. `pv=2` tropopause).
