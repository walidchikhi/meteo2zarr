# Reading and Slicing Data

The `MeteoZarr` class provides high-level slicing capabilities that return native, lazy `xarray.DataArray` structures with preserved geospatial coordinates and metadata attributes.

## Opening a Dataset

```python
import meteo2zarr as m2z

# Open any store (directory with partitioned groups or single .zarr archive)
store = m2z.open("/path/to/zarr_store")
```

## Listing Available Fields

```python
# List all variables across all groups
all_fields = store.listfields()
print(all_fields)
# ['2t', '10u', '10v', 'gh500', 'gh850', 'ps', 'r850', 't850', 'tp_3h', 'tp_6h', 'ws10']

# List variables in a specific group
surface_fields = store.listfields(group="surface")
```

## Extracting Fields with `readfield()`

```python
# Read 2m Temperature at timestep 0
t2_t0 = store.readfield("2t", timestep=0)
print(t2_t0.shape)  # (350, 350)
print(t2_t0.attrs["units"])  # 'Celsius'

# Read 3h accumulated precipitation at step 3h
tp_3h = store.readfield("tp_3h", timestep=0, group="surface_3h")

# Read entire time series (omitting timestep returns 3D array: time x lat x lon)
t2_series = store.readfield("2t")
print(t2_series.shape)  # (73, 350, 350)

# Slice by date string
t2_slice = store.readfield("2t", timestep="2026-08-19T06:00:00")
```
