"""Abstract base reader and format detector for NWP datasets."""

import abc
import logging
from pathlib import Path
from typing import List, Optional
import xarray as xr

from meteo2zarr.config import ConfigLoader

logger = logging.getLogger("meteo2zarr.io.base")


class BaseNWPReader(abc.ABC):
    """Abstract interface for format-specific NWP readers."""

    def __init__(self, cfg: Optional[ConfigLoader] = None, chunk_time: int = 6) -> None:
        self.cfg = cfg or ConfigLoader()
        self.chunk_time = chunk_time

    @abc.abstractmethod
    def read_one(self, file_path: Path) -> Optional[xr.Dataset]:
        """Read a single file into an xarray Dataset."""
        pass

    @abc.abstractmethod
    def read_all(self, files: List[Path], n_threads: int = 16) -> Optional[xr.Dataset]:
        """Read and combine multiple files into a single unified lazy Dataset."""
        pass


def detect_file_format(file_path: Path) -> str:
    """Inspect magic numbers or file extensions to detect NWP format."""
    path = Path(file_path)
    if not path.is_file():
        return "unknown"

    suffix = path.suffix.lower()
    if suffix in (".nc", ".nc4", ".netcdf"):
        return "netcdf"
    if suffix in (".grib", ".grb", ".grib1", ".grib2", ".grb1", ".grb2"):
        return "grib"

    # Check magic bytes
    try:
        with open(path, "rb") as f:
            header = f.read(16)
            if header.startswith(b"GRIB"):
                return "grib"
            if header.startswith(b"CDF") or header.startswith(b"\x89HDF"):
                return "netcdf"
    except Exception as e:
        logger.debug("Failed reading file header for %s: %s", path.name, e)

    # Check via epygram if available (FA format detector)
    try:
        import epygram
        if epygram.formats.guess(str(path)) in ("FA", "LFA"):
            return "fa"
    except Exception:
        pass

    return "unknown"


def list_and_classify_files(input_dir: Path, explicit_fmt: Optional[str] = None) -> tuple[str, List[Path]]:
    """Scan input directory, filter relevant files, and identify the dataset format."""
    all_files = sorted([p for p in input_dir.iterdir() if p.is_file()])
    if not all_files:
        return "none", []

    if explicit_fmt and explicit_fmt.lower() in ("fa", "lfa"):
        return "fa", all_files
    elif explicit_fmt and explicit_fmt.lower() in ("grib", "grib1", "grib2"):
        return "grib", all_files
    elif explicit_fmt and explicit_fmt.lower() in ("netcdf", "nc"):
        return "netcdf", all_files

    # Detect automatically using the first few files
    for sample in all_files[:5]:
        detected = detect_file_format(sample)
        if detected != "unknown":
            logger.info("Auto-detected input format: %s for %s", detected, input_dir)
            return detected, all_files

    # Default fallback: check if epygram can open
    try:
        import epygram
        if epygram.formats.guess(str(all_files[0])) in ("FA", "LFA"):
            return "fa", all_files
    except Exception:
        pass

    return "unknown", all_files
