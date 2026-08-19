# Quickstart

Get up and running with `meteo2zarr` in less than 2 minutes.

## 1. Convert NWP Model Files to Zarr

Convert any operational model run (ALADIN, AROME, ARPEGE, GFS) into optimized Zarr stores:

```bash
# Convert ALADIN FA files
meteo2zarr convert --model aladin --run 2026081900 --input /path/to/fa_files --output ./output_zarr

# Convert AROME GRIB files
meteo2zarr convert --model arome --run 2025102200 --input /path/to/grib_files --output ./output_zarr
```

## 2. Inspect Dataset Contents (`what`)

Inspect all variables, time ranges, and spatial dimensions without loading large data arrays into RAM:

```bash
# Write report to ./aladin_2026081900.info
meteo2zarr what output_zarr/aladin_2026081900

# Print report directly to terminal
meteo2zarr what output_zarr/aladin_2026081900 -o
```

## 3. High-Performance Meteorological Plotting (`plot`)

```bash
# Plot 2m Temperature (t2)
meteo2zarr plot output_zarr/aladin_2026081900 -f t2 -O

# Plot Wind Barbs (10u, 10v)
meteo2zarr plot output_zarr/aladin_2026081900 --wU 10u --wV 10v -O
```

## 4. Python API Usage

```python
import meteo2zarr as m2z

# Open any Zarr store (single, nested, or partitioned groups)
store = m2z.open("output_zarr/aladin_2026081900")

# Inspect
store.what()

# Read field as xarray DataArray
t2 = store.readfield("t2", timestep=0)
print(f"Mean Temperature: {t2.values.mean():.2f} °C")

# Plot
store.plot("t2", timestep=0, savefig="t2_carte.png")
```
