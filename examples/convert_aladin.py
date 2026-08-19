#!/usr/bin/env python3
"""
Standalone script to convert a full NWP forecast suite (ALADIN / AROME / GRIB)
into cloud-native Zarr using the `meteo2zarr` library.
"""

from datetime import datetime
from pathlib import Path
from meteo2zarr import NWPConverter

def main():
    # 1. Define paths and parameters
    input_dir  = "/home/chikhi/tmp/zarr/input/r00"
    output_dir = "/home/chikhi/tmp/zarr/output_aladin_zarr"
    model_name = "aladin"
    run_date   = datetime(2026, 8, 19, 0, 0)   # 2026081900
    
    print(f"=== Starting NWP to Zarr Conversion")
    print(f"Input Directory : {input_dir}")
    print(f"Output Directory: {output_dir}")
    print(f"Model           : {model_name}")
    print(f"Run Date        : {run_date}")
    
    # 2. Instantiate high-performance converter
    converter = NWPConverter(
        output_dir=output_dir,
        dask_workers=4,       # Number of local Dask workers
        dask_threads=2,       # Threads per worker
        chunk_time=6,         # Time chunking size for visualization
        read_threads=8,       # Parallel reader processes for FA/GRIB
        write_threads=4,      # Threads for parallel Zarr compression
    )

    # 3. Execute conversion pipeline
    # (Auto-detects format, reads all timesteps, calculates 1h/3h/6h/12h/24h accumulations,
    # computes wind speed/dir, and writes consolidated Zarr store)
    success = converter.convert(
        input_dir=input_dir,
        model=model_name,
        run_date=run_date,
        dt_hours=1.0,         # 1-hour forecast timestep
    )

    if success:
        print("Conversion completed successfully!")
        print(f"Zarr store created at: {Path(output_dir) / f'{model_name}_{run_date.strftime(\"%Y%m%d%H\")}.zarr'}")
    else:
        print("Conversion failed. Check logs for details.")

if __name__ == "__main__":
    main()
