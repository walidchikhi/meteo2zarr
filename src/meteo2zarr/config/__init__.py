"""Configuration management and schema definitions for meteo2zarr."""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("meteo2zarr.config")

CONFIG_DIR = Path(__file__).parent


class ConfigLoader:
    """Loads and manages FA, GRIB and Zarr group definitions."""

    def __init__(self, config_dir: Optional[str | Path] = None) -> None:
        self.base_dir = Path(config_dir) if config_dir else CONFIG_DIR

        self.fa_defs: Dict[str, Any] = self._load(
            self.base_dir / "fa_definitions.json",
            {"fields": {}, "levels": {}, "derived_fields": {}, "accumulations": {}},
        )
        self.grib_defs: Dict[str, Any] = self._load(
            self.base_dir / "grib_definitions.json",
            {"fields": {}, "grib1_keys": {}, "grib2_keys": {}},
        )
        self.zarr_groups: Dict[str, Any] = self._load(
            self.base_dir / "zarr_groups.json",
            {"groups": {}},
        )

        logger.debug(
            "Loaded configs | FA fields: %d | GRIB fields: %d | Groups: %d",
            len(self.fa_defs.get("fields", {})),
            len(self.grib_defs.get("fields", {})),
            len(self.zarr_groups.get("groups", {})),
        )

    @staticmethod
    def _load(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning("Failed to parse config %s: %s, using fallback", path.name, e)
                return default
        logger.warning("Config file %s not found -> using default values", path.name)
        return default
