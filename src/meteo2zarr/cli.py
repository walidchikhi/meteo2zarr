"""CLI interface for meteo2zarr."""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from meteo2zarr.core.converter import NWPConverter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("meteo2zarr.cli")


def main() -> None:
    """Entry point for the meteo2zarr CLI."""
    parser = argparse.ArgumentParser(
        prog="meteo2zarr",
        description="Convert Numerical Weather Prediction (NWP) model outputs to cloud-native Zarr stores.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Convert subcommand
    conv_parser = subparsers.add_parser("convert", help="Convert model run to Zarr")
    conv_parser.add_argument("--model", required=True, help="Model name (e.g. arome, aladin, arpege, gfs)")
    conv_parser.add_argument("--run", required=True, help="Run timestamp in YYYYMMDDHH format")
    conv_parser.add_argument("--input", required=True, help="Directory containing raw model output files")
    conv_parser.add_argument("--output", default="./zarr", help="Output directory for Zarr stores")
    conv_parser.add_argument("--config", default=None, help="Custom configuration directory")
    conv_parser.add_argument("--fmt", default=None, choices=["fa", "lfa", "grib", "grib1", "grib2", "netcdf"], help="Input file format")
    conv_parser.add_argument("--dt-hours", type=float, default=1.0, help="Timestep delta in hours for decumulation")
    conv_parser.add_argument("--dask-workers", type=int, default=4, help="Number of Dask workers")
    conv_parser.add_argument("--dask-threads", type=int, default=2, help="Threads per Dask worker")
    conv_parser.add_argument("--chunk-time", type=int, default=6, help="Chunk size for time dimension")
    conv_parser.add_argument("--read-threads", type=int, default=16, help="Threads/processes for reading input files")
    conv_parser.add_argument("--write-threads", type=int, default=4, help="Threads for writing Zarr store")
    conv_parser.add_argument("--dashboard-address", default=":8787", help="Dask dashboard address (e.g. :8787 or 0.0.0.0:3112)")
    conv_parser.add_argument("--pyramids", action="store_true", help="Generate multiscale pyramids (ndpyramid)")

    args = parser.parse_args()

    if args.command == "convert":
        try:
            run_date = datetime.strptime(args.run, "%Y%m%d%H")
        except ValueError:
            logger.error("Invalid run date format: %s. Expected YYYYMMDDHH (e.g. 2026030100)", args.run)
            sys.exit(1)

        converter = NWPConverter(
            output_dir=args.output,
            config_dir=args.config,
            dask_workers=args.dask_workers,
            dask_threads=args.dask_threads,
            chunk_time=args.chunk_time,
            read_threads=args.read_threads,
            write_threads=args.write_threads,
            dashboard_address=args.dashboard_address,
            use_pyramids=args.pyramids,
        )

        ok = converter.convert(
            input_dir=args.input,
            model=args.model,
            run_date=run_date,
            fmt=args.fmt,
            dt_hours=args.dt_hours,
        )
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
