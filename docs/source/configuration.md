# Configuration System

`meteo2zarr` relies on a flexible, human-readable JSON/YAML configuration architecture located in `src/meteo2zarr/config/`.

## 1. Variable Mapping Definitions (`fa_definitions.json` / `grib_definitions.json`)

Controls how raw field IDs are normalized into shortnames, physical units, and standard CF metadata:

```json
{
  "fields": {
    "CLSTEMPERATURE": {
      "shortname": "2t",
      "unit": "Celsius",
      "formula": "k2c",
      "desc": "2m Temperature"
    },
    "SURFACCPLUIE": {
      "shortname": "tp",
      "unit": "kg m-2",
      "formula": "acc",
      "desc": "Total Precipitation Accumulation"
    }
  }
}
```

---

## 2. Sliding Window Decumulations (`accumulations`)

Defines which cumulative fields should automatically be decumulated into sliding temporal windows:

```json
{
  "accumulations": {
    "tp": ["3h", "6h", "12h", "24h"],
    "twatp_con": ["3h", "6h", "12h", "24h"],
    "twatp_gec": ["3h", "6h", "12h", "24h"]
  }
}
```

---

## 3. Custom Configuration Directory

You can override the built-in configurations at runtime by passing `--config /path/to/my_config`:

```bash
meteo2zarr convert --model aladin --run 2026081900 --input /data --config /home/user/custom_meteo2zarr_config
```
