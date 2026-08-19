# NWP Conversion Pipeline and Dask Engine

## 1. What does Dask do in `meteo2zarr`?

In Numerical Weather Prediction (NWP), converting 70+ forecast timesteps containing hundreds of 2D/3D meteorological fields quickly hits the limits of standard sequential Python:
- **Memory Saturation**: Storing tens of gigabytes of raw uncompressed floating-point grids directly in RAM causes Out-Of-Memory (OOM) crashes.
- **CPU Bottlenecks**: Computing vector wind speeds $\sqrt{u^2 + v^2}$, wind directions, and sliding-window precipitation decumulations $RR_{3\text{h}}(T) = \text{Acc}(T) - \text{Acc}(T-3\text{h})$ sequentially across 50 million grid points is slow.

### How Dask Solves This:
1. **Lazy Execution (Task Graphs)**: Data arrays are represented as lazy computational graphs. No actual computations or memory allocations happen until data is streamed to the Zarr compressor.
2. **Chunking & Memory Safety**: Multi-dimensional tensors are broken down into small, manageable chunk arrays (e.g. 6 timesteps x 100 x 100).
3. **Multi-Core / Multi-Process Parallelism**: Dask distributes the mathematical calculations across multiple worker processes simultaneously, taking full advantage of modern multi-core CPUs and HPC clusters.
4. **Live Visual Monitoring**: Dask provides an embedded real-time web dashboard (at `http://localhost:8787`) to monitor memory consumption, CPU saturation, and task progress live.

---

## 2. Complete Arguments Reference for `meteo2zarr convert`

The CLI command `meteo2zarr convert` provides a rich set of options to fine-tune parallel reading, distributed computation, and storage chunking:

```bash
meteo2zarr convert \
  --model aladin \
  --run 2026081900 \
  --input /data/models/aladin/2026081900 \
  --output ./zarr_output \
  --fmt fa \
  --dt-hours 1.0 \
  --dask-workers 4 \
  --dask-threads 2 \
  --chunk-time 6 \
  --read-threads 16 \
  --write-threads 4 \
  --config /path/to/custom_config \
  --dashboard-address 0.0.0.0:8787
```

### Detailed Breakdown of Every Argument:

| Argument | Type | Default | Detailed Description and Impact |
| :--- | :--- | :--- | :--- |
| **`--model`** | `str` | *Required* | **NWP Model Name** (`arome`, `aladin`, `arpege`, `gfs`). Determines the appropriate field mapping definitions, accumulation keys, and vertical coordinate rules. |
| **`--run`** | `str` | *Required* | **Model Run Timestamp** in `YYYYMMDDHH` format (e.g. `2026081900` for August 19, 2026 at 00:00 UTC). Used to tag the dataset time coordinates and generate the root folder name (`<model>_<run>`). |
| **`--input`** | `str` | *Required* | **Input Files Directory**. The directory path containing the raw FA or GRIB files for this forecast run. |
| **`--output`** | `str` | `./zarr` | **Destination Directory**. The parent directory where the generated Zarr store directory (`<model>_<run>`) will be created. |
| **`--fmt`** | `str` | `auto` | **Input Format Force Flag** (`fa`, `lfa`, `grib`, `grib1`, `grib2`, `auto`). When left to `auto`, `meteo2zarr` automatically inspects file headers and extensions to pick the right reader engine. |
| **`--dt-hours`** | `float` | `1.0` | **Forecast Timestep Frequency (Hours)**. The temporal resolution between consecutive forecast files (e.g. `1.0` for hourly output, `3.0` for 3-hourly). Used by the accumulation engine to convert hour windows into step shifts (`steps = hours / dt_hours`). |
| **`--dask-workers`** | `int` | `4` | **Number of Dask Worker Processes**. Sets the number of independent Python worker processes spawned by Dask for parallel data computation and compression. |
| **`--dask-threads`** | `int` | `2` | **Threads per Dask Worker**. Number of parallel threads allocated to each Dask worker. (Total computation threads = `workers * threads`). |
| **`--chunk-time`** | `int` | `6` | **Zarr Time Chunk Dimension**. Sets how many timesteps are stored together in a single Zarr chunk file on disk. A value of `6` balances fast time-series extraction and spatial slice retrieval. |
| **`--read-threads`** | `int` | `16` | **Multiprocessing Pool for Raw File Reading**. Size of the dedicated worker pool used to decode raw FA/GRIB files in parallel before handing arrays over to Dask. |
| **`--write-threads`**| `int` | `4` | **Concurrent Group Writer Threads**. Number of parallel threads used to write distinct Zarr groups (`surface`, `surface_3h`, `alt_pressure`, etc.) to disk simultaneously. |
| **`--config`** | `str` | `None` | **Custom Configuration Directory**. Path to a custom directory containing `fa_definitions.json`, `grib_definitions.json`, or `zarr_groups.json` to override defaults without modifying code. |
| **`--dashboard-address`** | `str` | `0.0.0.0:8787` | **Dask Web Dashboard Address**. The host IP and port to bind the Dask monitoring dashboard. Set to `":0"` to pick a random open port, or `None` to disable. |

---

## 3. Python API Equivalent

All CLI parameters directly map to the `NWPConverter` class and its `convert()` method:

```python
from datetime import datetime
from meteo2zarr.core.converter import NWPConverter

# 1. Initialize the converter with worker and cluster settings
converter = NWPConverter(
    output_dir="./output_zarr",
    dask_workers=4,
    dask_threads=2,
    chunk_time=6,
    read_threads=16,
    write_threads=4,
    dashboard_address="0.0.0.0:8787",
)

# 2. Execute the conversion
success = converter.convert(
    input_dir="/data/models/aladin/2026081900",
    model="aladin",
    run_date=datetime(2026, 8, 19, 0),
    fmt="fa",
    dt_hours=1.0,
    config_dir=None,  # Optional custom config directory
)

print(f"Conversion status: {success}")
```
