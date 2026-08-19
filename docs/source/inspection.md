# Store Inspection (`what`)

The `what` utility provides instantaneous dataset introspection without reading gigabytes of tensor data into RAM. It reads consolidated metadata dictionaries (`.zmetadata`) in sub-milliseconds.

## CLI Usage

```bash
# Default mode: writes <store_name>.info in the current working directory
meteo2zarr what output_zarr/aladin_2026081900

# Print directly to stdout without writing a file (-o / --stdout)
meteo2zarr what output_zarr/aladin_2026081900 -o

# Sort variables alphabetically (-s / --sortfields)
meteo2zarr what output_zarr/aladin_2026081900 -s -o

# Inspect detailed grid coordinates (-d grid)
meteo2zarr what output_zarr/aladin_2026081900 -d grid -o

# Inspect chunk dimensions on disk (-d chunks)
meteo2zarr what output_zarr/aladin_2026081900 -d chunks -o

# Inspect compression codecs (-d compression)
meteo2zarr what output_zarr/aladin_2026081900 -d compression -o
```

---

## Python API Usage

```python
import meteo2zarr as m2z

store = m2z.open("output_zarr/aladin_2026081900")

# Write report file: ./aladin_2026081900.info
store.what()

# Print to stdout
report_text = store.what(stdout=True, details="grid", sortfields=True)
```

---

## Sample Inspection Output

```text
========================================================================
METEO2ZARR INSPECTION: aladin_2026081900
========================================================================

Group: 'surface' (12 variables, 73 timesteps)
  Time range  : 2026-08-19T00:00:00 -> 2026-08-22T00:00:00
  Grid size   : 350 latitudes x 350 longitudes
  Lat bounds  : [22.0000 .. 42.0000] (step ~ 0.0573)
  Lon bounds  : [-9.0000 .. 15.0000] (step ~ 0.0688)
  Variables   :
    - 2t               : 2m Temperature [Celsius] (type: surface, level: 2.0)
    - 10u              : 10m U-Wind [m s-1] (type: surface, level: 10.0)
    - 10v              : 10m V-Wind [m s-1] (type: surface, level: 10.0)
    - ps               : Surface Pressure [hPa] (type: surface, level: 0.0)
    - totcc            : Total Cloud Cover [%] (type: surface, level: 0.0)

Group: 'surface_3h' (3 variables, 70 timesteps)
  Time range  : 2026-08-19T03:00:00 -> 2026-08-22T00:00:00
  Grid size   : 350 latitudes x 350 longitudes
  Variables   :
    - tp_3h            : 3h Accumulated Precipitation [kg m-2] (type: surface)
========================================================================
```
