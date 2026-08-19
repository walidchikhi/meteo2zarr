# Store Inspection (`what`)

The `what` utility provides instantaneous dataset introspection without reading gigabytes of tensor data into RAM. It reads consolidated metadata dictionaries (`.zmetadata`) in sub-milliseconds.

## CLI Usage

```bash
# Default mode: writes <store_name>.info in the current working directory
meteo2zarr what output_zarr/aladin_2026081900

# Print directly to stdout without writing a file (-o / --stdout)
meteo2zarr what output_zarr/aladin_2026081900 -o

# Display the exact list of available timesteps (-d time)
meteo2zarr what output_zarr/aladin_2026081900 -d time -o

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

# Print to stdout with full list of timesteps
store.what(stdout=True, details="time")
```

---

## Sample Inspection Output with Timesteps (`-d time`)

```text
========================================================================
METEO2ZARR INSPECTION: aladin_2026081900
========================================================================

Group: 'surface' (3 variables, 10 timesteps)
  Time range     : 2026-08-19T00:00:00 -> 2026-08-19T09:00:00
  Timesteps (10) : 2026-08-19T00:00:00, 2026-08-19T01:00:00, 2026-08-19T02:00:00, 2026-08-19T03:00:00, 2026-08-19T04:00:00, 2026-08-19T05:00:00, 2026-08-19T06:00:00, 2026-08-19T07:00:00, 2026-08-19T08:00:00, 2026-08-19T09:00:00
  Grid size      : 350 latitudes x 350 longitudes
  Variables      :
    - t2               : 2m Temperature [Celsius] (type: surface)
    - twatp_con        : Convective Precip [kg m-2] (type: surface)
    - twatp_gec        : Large Scale Precip [kg m-2] (type: surface)

Group: 'surface_3h' (2 variables, 7 timesteps)
  Time range     : 2026-08-19T03:00:00 -> 2026-08-19T09:00:00
  Timesteps (7)  : 2026-08-19T03:00:00, 2026-08-19T04:00:00, 2026-08-19T05:00:00, 2026-08-19T06:00:00, 2026-08-19T07:00:00, 2026-08-19T08:00:00, 2026-08-19T09:00:00
  Grid size      : 350 latitudes x 350 longitudes
  Variables      :
    - twatp_con_3h     : 3h Accumulated Precipitation [kg m-2] (type: surface)
    - twatp_gec_3h     : 3h Accumulated Precipitation [kg m-2] (type: surface)
========================================================================
```
