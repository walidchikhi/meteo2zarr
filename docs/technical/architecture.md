# Architecture

The internal logic is implemented in `core_hpc.py`, optimized for the shared-storage and multi-node environment of an HPC cluster.

## 1. Parallel Reading Phase

Traditional `epygram` usage is not thread-safe. To maximize performance, we use a `ProcessPoolExecutor` to read multiple FA files in parallel.

- **Process Isolation**: Each FA file is opened and read by a separate sub-process.
- **Batched Loading**: Files are processed in chunks (defined by `--read-threads`) to stay within memory limits.
- **Conversion**: Field values are converted to standardized units (e.g., Kelvin to Celsius) and cast to `float32` immediately to reduce memory footprint.

## 2. Dask Integration

Once the data is read into memory as NumPy arrays, it is wrapped into a **Dask Dataset**.

- **Lazy Operations**: Most transformations (renaming, attribute assignment) are lazy.
- **Streaming Write**: The `ZarrWriter` uses Dask's `.to_zarr()` with `compute=True` to stream data to disk.
- **Chunking Strategy**: 
    - **Time**: `-1` (all time steps in one chunk) for fast time-series access.
    - **Spatial**: `256 x 256` tiles, optimized for web map display and TiTiler.

## 3. Memory Management

Converting large NWP runs (e.g., 50+ leadtimes with 100+ variables) can easily exceed 64GB of RAM.

- **Manual Garbage Collection**: The system calls `gc.collect()` and deletes large intermediate buffers (`del src`) after critical phases.
- **Minimal Loading**: Accumulation fields are loaded and processed one-by-one to avoid keeping multiple 4D arrays in memory simultaneously.
- **Locking**: `locket` is used to synchronize access to the local cache and prevent race conditions during Dask graph construction.

## 4. Slurm / Dask Orchestration

The system does **not** rely on a persistent Dask cluster. Instead:
1.  A Slurm job is submitted.
2.  The job starts a **Local Dask Cluster** within its allocated resources (nodes/CPUs).
3.  Computations are executed locally on the allocated compute node.
4.  The Dask dashboard is exposed for real-time monitoring.
