# Configuration

The converter relies on several JSON files to map input fields to standardized variables and organize them into Zarr groups.

## 1. Variable Mapping (`fa_definitions.json`)

This file defines how FA field names are mapped to standard shortnames and how levels are parsed.

### Field Mapping
```json
"CLSTEMPERATURE": {
    "shortname": "2t",
    "unit": "Celsius",
    "formula": "k2c",
    "desc": "2m Temperature"
}
```
- `shortname`: The name used in the Zarr dataset.
- `formula`: Unit transformation applied during reading (e.g., `k2c` for Kelvin to Celsius, `percent` for 0-1 to 0-100%).

### Level Parsing
The `levels` section defines how field prefixes/suffixes correspond to vertical levels.
- `P`: Isobaric (Pressure) levels.
- `H`: Height levels.
- `S`: Model sigma levels.
- `CLS`: Surface diagnostics (2m, 10m).

### Skip List
You can ignore specific fields to save processing time and disk space:
```json
"skip_fields": [
    "SURFRAYT.*",
    "INTSURFGEOPOTENT"
]
```
Regex is supported.

## 2. Zarr Grouping (`zarr_groups.json`)

This file determines how variables are partitioned into different Zarr stores.

```json
"surface_3h": {
    "description": "3h Accumulations",
    "match": {
        "parameters": [ "RR3h" ]
    }
}
```

### Match Logic:
1.  **Level Type**: Group by `level_types` (isobaric, height, surface).
2.  **Parameters**: Explicitly specify variables (e.g., `RR3h`, `RR6h`).
3.  **Duration**: Group names ending in `_Nh` (e.g., `_3h`) will automatically trigger duration-based partitioning and time-slicing.

## 3. Visualization (`viz_config.json`)

Optional. Provides metadata (presets, colors, ranges) for frontend tools like MapLibre or specialized viewers.
- Variables in Zarr will have a `viz` attribute containing this configuration as a JSON string.
