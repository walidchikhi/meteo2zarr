# Declarative Configuration System: Multi-Model Unification

## The Core Philosophy

In operational meteorology and modern Full-Stack Web GIS applications (MapLibre GL, Leaflet, OpenLayers, Titiler), frontend and downstream analytics require strictly homogeneous data contracts:
- Identical canonical variable names (`shortname`).
- Identical physical units and unified standard coordinates.
- Predictable multi-dimensional array shapes.

However, raw meteorological models output heterogeneous keys and formats:
- AROME / ALADIN (FA format): uses internal Arpege/Accord keys like `CLSTEMPERATURE`, `SURFACCPLUIE`, `SURFPREC.EAU.CON`.
- GRIB1 / GRIB2 format: uses WMO numerical codes, edition-dependent keys, or shortnames like `2t`, `tp`, `10u`.

meteo2zarr solves this problem at the root through a declarative, 100% data-driven JSON architecture.  
You can map new parameters, apply mathematical formulas, create sliding window accumulations, and define custom storage partitions without writing a single line of Python code.

---

## Architecture: Input Mapping vs Storage Hierarchy

The conversion pipeline is divided into two distinct decoupled stages:

```text
+-----------------------------------------------------------------------------------+
| 1. INPUT SOURCES (FA, LFA, GRIB1, GRIB2)                                          |
|    - FA File   : CLSTEMPERATURE, SURFACCPLUIE, SURFPREC.EAU.CON                   |
|    - GRIB File : 2t (param 11), tp (param 61), 10u (param 33)                     |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| 2. NORMALIZATION & METADATA MAPPING (fa_definitions.json / grib_definitions.json)  |
|    - Maps raw field keys -> Canonical shortnames (e.g. CLSTEMPERATURE -> 2t)       |
|    - Applies physical unit transformations (e.g. k2c: Kelvin -> Celsius)          |
|    - Triggers sliding window decumulations (RR3h, RR6h, RR12h, RR24h)             |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| 3. STORAGE DISPATCHING & GROUP PARTITIONING (zarr_groups.json)                   |
|    - Matches variables by level type and duration (surface, isobaric, 3h, 6h)    |
|    - Groups arrays into independent Zarr sub-stores with optimized chunks         |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| 4. FINAL CLOUD-OPTIMIZED ZARR ARCHIVE                                             |
|    - surface.zarr       : 2t [Celsius], 10u [m s-1], 10v [m s-1], ps [hPa]       |
|    - surface_3h.zarr    : tp_3h [kg m-2], twatp_con_3h [kg m-2]                  |
|    - surface_6h.zarr    : tp_6h [kg m-2], twatp_con_6h [kg m-2]                  |
|    - alt_pressure.zarr  : t [Celsius], gh [gpm], u [m s-1] on isobaric levels     |
+-----------------------------------------------------------------------------------+
```

---

## Configuration Files Roles Comparison

| Configuration File | Scope & Role | What it controls |
| :--- | :--- | :--- |
| `fa_definitions.json` | FA/LFA Decoding & Normalization | Recognizes vertical prefixes (`CLS`, `P`, `H`, `V`), ignores unwanted fields (`skip_fields`), maps raw FA fieldnames to canonical `shortname`, assigns physical units and formulas (`k2c`, `pa2hpa`, `div98`). |
| `grib_definitions.json` | GRIB1/GRIB2 Decoding & Normalization | Maps GRIB shortnames, `grib1_param` IDs, and `grib2_key` tuples to the exact same canonical `shortname`, units, and formulas as `fa_definitions.json`. |
| `zarr_groups.json` | Zarr Store Partitioning & Chunking | Dispatches normalized variables into independent Zarr sub-groups (`surface`, `surface_3h`, `alt_pressure`, `alt_pv`) using level matching and parameter filtering. |

---

## Anatomy of a Parameter: 2-meter Temperature (2t)

Let us trace 2-meter Temperature through the entire configuration pipeline:

### 1. In fa_definitions.json (FA Source)
```json
{
  "levels": {
    "CLS": {
      "type": "surface",
      "unit": "2m",
      "description": "Constant Level Surface (2m diagnostics)"
    }
  },
  "fields": {
    "CLSTEMPERATURE": {
      "shortname": "2t",
      "unit": "Celsius",
      "formula": "k2c",
      "desc": "2m Temperature"
    }
  }
}
```

### 2. In grib_definitions.json (GRIB Source)
```json
{
  "fields": {
    "2t": {
      "shortname": "2t",
      "unit": "Celsius",
      "formula": "k2c",
      "desc": "2m Temperature",
      "grib1_param": "11",
      "grib2_key": "0.0.0"
    }
  }
}
```

### 3. In zarr_groups.json (Destination Group)
```json
{
  "groups": {
    "surface": {
      "description": "Paramètres de surface (Niveau 0, 2m, 10m)",
      "match": {
        "level_types": ["surface", "height"],
        "exclude": ["RR3h", "RR6h", "RR12h", "RR24h"]
      }
    }
  }
}
```

### Final Result in Zarr:
Regardless of input format:
- Group: `surface`
- Array Name: `2t`
- Attributes: `{"long_name": "2m Temperature", "units": "Celsius", "level_type": "surface", "level": 2.0}`
- Values: Converted from Kelvin to Celsius via formula `T_celsius = T_kelvin - 273.15`.

---

## Understanding RR3h, RR6h and Accumulations: Where and How are they Declared?

A common question is: **Where does `RR3h` come from, what does it contain, and where is it declared?**

### 1. The Physical Need for Decumulations
In NWP models (AROME, ALADIN), precipitation fields (`SURFACCPLUIE`, `SURFPREC.EAU.CON`, `tp`) are cumulative quantities integrated since run inception (`t = 0`):

```text
Accumulated_Rain(T) = Total precipitation from step 0 to step T
```

Meteorologists need decumulated rainfall over specific sliding intervals, for instance the last 3 hours:

```text
Rain_3h(T) = Accumulated_Rain(T) - Accumulated_Rain(T - 3h)
```

### 2. Where are the accumulation rules declared?
In `fa_definitions.json` and `grib_definitions.json` under the `"accumulations"` block:
```json
{
  "accumulations": {
    "tp": ["RR3h", "RR6h", "RR12h", "RR24h"],
    "twatp_con": ["RR3h", "RR6h", "RR12h", "RR24h"],
    "twatp_gec": ["RR3h", "RR6h", "RR12h", "RR24h"]
  }
}
```
Here, `"RR3h"`, `"RR6h"`, `"RR12h"`, `"RR24h"` are **accumulation interval triggers** specifying that for each declared base parameter, the processor must generate:
- `<var>_3h` (e.g. `tp_3h`, `twatp_con_3h`) with metadata attribute `acc_hours = 3`.
- `<var>_6h` (e.g. `tp_6h`, `twatp_con_6h`) with metadata attribute `acc_hours = 6`.

### 3. How does zarr_groups.json route them?
In `zarr_groups.json`, group routing uses the pattern matching rule:
```json
{
  "surface_3h": {
    "description": "Cumuls 3h (Précipitations)",
    "match": {
      "parameters": ["RR3h"]
    }
  },
  "surface_6h": {
    "description": "Cumuls 6h (Précipitations)",
    "match": {
      "parameters": ["RR6h"]
    }
  }
}
```
When `meteo2zarr` generates the 3h decumulated fields, `writer.py` automatically routes any variable generated from the `"RR3h"` rule into `surface_3h.zarr`, while the base instantaneous fields remain in `surface.zarr` (due to `"exclude": ["RR3h", "RR6h", ...]`).

---

## Unit Formulas and Mathematical Transforms Engine

### Where are the formulas located?
The formulas are defined in `src/meteo2zarr/processing/derived.py` within `apply_unit_formula()`.

### Built-in Formulas:

| Formula Key | Operation | Usage |
| :--- | :--- | :--- |
| `k2c` | `X - 273.15` | Kelvin to Celsius |
| `pa2hpa` | `X / 100.0` | Pascals to Hectopascals |
| `div98` | `X / 9.80665` | Geopotential to Geopotential Height (gpm) |
| `percent` | `X * 100.0` | Fraction [0, 1] to Percentage [0, 100%] |
| `none` / `None` | `X` | Direct physical values |

---

## Adding a Custom Parameter and Formula (Step-by-Step)

### Step 1: Register a new formula in processing/derived.py (if not existing)
```python
# In src/meteo2zarr/processing/derived.py
elif f == "joule2kwh":
    res = da / 3.6e6
    res.attrs.update(da.attrs)
    res.attrs["unit"] = "kWh m-2"
    return res
```

### Step 2: Declare parameter in fa_definitions.json and/or grib_definitions.json
```json
"SURFRAYT.SOLA.DE": {
  "shortname": "ssrd",
  "unit": "kWh m-2",
  "formula": "joule2kwh",
  "desc": "Surface Solar Radiation Downwards"
}
```

### Step 3: Add Decumulations (Optional)
```json
"accumulations": {
  "ssrd": ["RR3h", "RR6h", "RR24h"]
}
```

### Step 4: Run Conversion
```bash
meteo2zarr convert --model aladin --run 2026081900 --input /data --output ./zarr_out
```
