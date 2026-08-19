# Architecture and Performance

## 1. Dask Distributed Execution Model

The diagram below illustrates the end-to-end data processing workflow from raw NWP inputs to partitioned cloud-optimized Zarr archives:

```text
+-----------------------------------------------------------------------------------+
| 1. RAW NWP FILES                                                                  |
|    - FA / LFA Files (AROME / ALADIN / ARPEGE)                                     |
|    - GRIB1 / GRIB2 Files (WMO standard)                                           |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| 2. MULTIPROCESS PARALLEL READER POOL                                              |
|    - High-throughput multiprocessing pool (16 parallel workers)                  |
|    - Zero-lock parallel reading with EPyGrAM & ecCodes C-backends                 |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| 3. LAZY DASK MULTI-DIMENSIONAL ARRAYS                                             |
|    - Lazy memory-mapped datasets indexed by (time, level, lat, lon)                |
|    - Optimized 3D chunking layout along spatial and temporal axes                 |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| 4. DERIVED METEOROLOGY & ACCUMULATION ENGINE                                      |
|    - Vectorized sliding window decumulations (RR3h, RR6h, RR12h, RR24h)           |
|    - Unit transformations (k2c, pa2hpa, div98, percent)                           |
|    - Vector wind computations (speed, direction)                                  |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| 5. HIGH-PERFORMANCE BLOSC-ZSTD COMPRESSOR                                         |
|    - Blosc compression with Zstandard codec and byte-shuffle filtering            |
|    - Maximum compression ratio with high decompress throughput for web browsers   |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| 6. CONCURRENT PARTITIONED GROUP WRITER                                            |
|    - surface.zarr                                                                 |
|    - surface_3h.zarr / surface_6h.zarr / surface_12h.zarr / surface_24h.zarr      |
|    - alt_pressure.zarr / alt_pv.zarr                                              |
+-----------------------------------------------------------------------------------+
```

---

## 2. Benchmark Comparison (ALADIN 73 Forecast Timesteps)

The table below summarizes benchmark timings measured on real operational ALADIN runs (350x350 grid, 73 timesteps, 40+ variables):

| Operation | Legacy Tools (NetCDF / GRIB) | meteo2zarr | Speedup |
| :--- | :--- | :--- | :--- |
| Complete Conversion | 3 - 5 min | 20 - 25 seconds | ~10x faster |
| What Inspection | 4 - 8 seconds | 0.02 seconds | ~250x faster |
| Point Time-Series Slice | 10 - 15 seconds | 0.05 seconds | ~300x faster |
| Full Domain Plot | 5 - 10 seconds | 1.7 seconds | ~4x faster |
