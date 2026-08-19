"""IO module with format detection and dedicated readers for FA, GRIB, and NetCDF."""

from meteo2zarr.io.base import BaseNWPReader, detect_file_format, list_and_classify_files
from meteo2zarr.io.fa import FAReader
from meteo2zarr.io.grib import GRIBReader

__all__ = [
    "BaseNWPReader",
    "detect_file_format",
    "list_and_classify_files",
    "FAReader",
    "GRIBReader",
]
