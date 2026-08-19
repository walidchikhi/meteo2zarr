"""CLI interface for meteo2zarr."""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from meteo2zarr.core.converter import NWPConverter
from meteo2zarr.core.store import open as open_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("meteo2zarr.cli")


def main() -> None:
    """Entry point for the meteo2zarr CLI."""
    parser = argparse.ArgumentParser(
        prog="meteo2zarr",
        description="Convert and analyze Numerical Weather Prediction (NWP) Zarr stores.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. Convert subcommand
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
    conv_parser.add_argument("--dashboard-address", default="0.0.0.0:8787", help="Dask dashboard address (e.g. 0.0.0.0:8787)")
    conv_parser.add_argument("--pyramids", action="store_true", help="Generate multiscale pyramids (ndpyramid)")

    # 2. What (inspect) subcommand matching epy_what semantics
    what_parser = subparsers.add_parser("what", help="Ask what's inside a Zarr resource (similar to epy_what)")
    what_parser.add_argument("store", help="Name of the Zarr folder or file to be processed.")
    what_parser.add_argument("-d", "--details", default=None, help="Get some details about each field. E.g. 'grid', 'chunks', or 'compression'.")
    what_parser.add_argument("-s", "--sortfields", action="store_true", help="Sort fields with regards to their name.")
    what_parser.add_argument("-o", "--stdout", action="store_true", help="Redirects output to standard output (rather than file).")
    what_parser.add_argument("-v", "--verbose", action="store_true", help="Run verbosely.")

    # 3. Plot subcommand
    plot_parser = subparsers.add_parser("plot", help="Plot a 2D variable from a Zarr store")
    plot_parser.add_argument("store", help="Path to .zarr file or multi-group Zarr directory")
    plot_parser.add_argument("--var", required=True, help="Variable name to plot (e.g. 2t, tp, ws10)")
    plot_parser.add_argument("--timestep", type=int, default=0, help="Timestep index (default: 0)")
    plot_parser.add_argument("--group", default=None, help="Specific Zarr group (optional)")
    plot_parser.add_argument("--cmap", default="Spectral_r", help="Matplotlib colormap")
    plot_parser.add_argument("--savefig", default=None, help="Path to save output plot image (PNG/PDF)")

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

    elif args.command == "what":
        store = open_store(args.store)
        store.what(
            details=args.details,
            sortfields=args.sortfields,
            stdout=args.stdout,
            verbose=args.verbose,
        )

    elif args.command == "plot":
        store = open_store(args.store)
        store.plot(
            var_name=args.var,
            timestep=args.timestep,
            group=args.group,
            cmap=args.cmap,
            savefig=args.savefig,
        )


if __name__ == "__main__":
    main()
