# Configuration System: Multi-Model Unification

One of the central goals of **`meteo2zarr`** is to decouple the conversion logic from the underlying model formats. In meteorological workflows and modern **Web GIS / Web visualization applications**, frontend applications expect standardized variable names, identical physical units, and homogeneous dimensions regardless of whether the forecast originated from **AROME**, **ALADIN**, **ARPEGE**, or **GFS**, and whether the raw format was **FA** or **GRIB**.

All conversion behaviors, variable mappings, formula conversions, sliding window accumulations, and storage hierarchies are fully managed via **declarative JSON configuration files** located in `src/meteo2zarr/config/`.

---

## 1. Role of Configuration Files: `fa_definitions.json` / `grib_definitions.json` vs `zarr_groups.json`

| Configuration File | Primary Role | When to Modify |
| :--- | :--- | :--- |
| **`fa_definitions.json` / `grib_definitions.json`** | **Input Decoding & Normalization**: Maps model-specific raw field keys (e.g. `SURFACCPLUIE`, `2t`) to canonical meteorological shortnames (`tp`, `2t`), physical units, and unit transformations (`k2c`, `pa2hpa`, `percent`). | When adding a new meteorological parameter, changing a unit formula, or adjusting sliding window accumulation intervals. |
| **`zarr_groups.json`** | **Output Storage Architecture**: Defines how normalized variables are partitioned into optimized Zarr sub-groups (`surface.zarr`, `surface_3h.zarr`, `alt_pressure.zarr`, etc.) with specific chunking schemes. | When organizing variables into logical groups or tuning Zarr chunk dimensions for web access and analytics. |

---

## 2. Input Definition File Example (`grib_definitions.json`)

Here is an extract of `grib_definitions.json`:

```json
{
  "fields": {
    "2t": {
      "shortname": "2t",
      "unit": "Celsius",
      "formula": "k2c",
      "desc": "2m Temperature"
    },
    "10u": {
      "shortname": "10u",
      "unit": "m s-1",
      "formula": "none",
      "desc": "10m U-Wind Component"
    },
    "10v": {
      "shortname": "10v",
      "unit": "m s-1",
      "formula": "none",
      "desc": "10m V-Wind Component"
    },
    "tp": {
      "shortname": "tp",
      "unit": "kg m-2",
      "formula": "acc",
      "desc": "Total Precipitation"
    }
  },
  "accumulations": {
    "tp": ["3h", "6h", "12h", "24h"]
  }
}
```

---

## 3. Storage Hierarchy File Example (`zarr_groups.json`)

```json
{
  "groups": {
    "surface": {
      "description": "Instantaneous 2D surface parameters",
      "members": ["2t", "10u", "10v", "ps", "q2", "totcc", "ws10"],
      "chunks": {
        "time": 6,
        "y": 100,
        "x": 100
      }
    },
    "surface_3h": {
      "description": "3-hour sliding window decumulated fields",
      "members": ["tp_3h", "twatp_con_3h", "twatp_gec_3h"],
      "chunks": {
        "time": 6,
        "y": 100,
        "x": 100
      }
    },
    "surface_6h": {
      "description": "6-hour sliding window decumulated fields",
      "members": ["tp_6h", "twatp_con_6h", "twatp_gec_6h"],
      "chunks": {
        "time": 6,
        "y": 100,
        "x": 100
      }
    },
    "alt_pressure": {
      "description": "Upper-air variables on isobaric pressure levels",
      "members": ["gh", "t", "r", "u", "v", "w"],
      "chunks": {
        "time": 3,
        "level": 1,
        "y": 100,
        "x": 100
      }
    }
  }
}
```

---

## 4. Step-by-Step: Adding Custom Variables, Groups, and Formulas (Zero Code Modification)

Because the pipeline is entirely data-driven, you can customize your conversions without modifying a single line of Python code:

### Step 1: Add a New Parameter in `fa_definitions.json` or `grib_definitions.json`
To ingest surface solar radiation (e.g. `SURFRAYT SOLA` in FA):
```json
"SURFRAYT SOLA": {
  "shortname": "ssrd",
  "unit": "J m-2",
  "formula": "acc",
  "desc": "Surface Solar Radiation Downwards"
}
```

### Step 2: Add Sliding Window Accumulations (Optional)
If you want automatic 3h and 6h decumulations for this new parameter:
```json
"accumulations": {
  "ssrd": ["3h", "6h", "24h"]
}
```

### Step 3: Assign the Variable to a Zarr Group in `zarr_groups.json`
Add `"ssrd"` to the `"surface"` group members:
```json
"surface": {
  "members": ["2t", "10u", "10v", "ssrd", ...]
}
```
And add `"ssrd_3h"` to `"surface_3h"`.

### Step 4: Run Conversion with Custom Config Directory
You can keep custom configs in any external directory and pass them via `--config`:
```bash
meteo2zarr convert --model arome --run 2026081900 --input /path/to/data --config /my/custom/config_dir
```

---

## 5. Supported Input Formats

- ✅ **FA (ARPEGE / ALADIN / AROME)**: Via high-performance multiprocessing `EPyGrAM` backend.
- ✅ **LFA (AROME Surfex)**: Fully supported.
- ✅ **GRIB1 / GRIB2 (WMO Standard)**: Via parallel `ecCodes` message decoding.
- ℹ️ *Note: NetCDF4 files are currently not in scope as meteorological operational streams rely on FA and GRIB.*
