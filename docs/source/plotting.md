# Cartographic Plotting

`meteo2zarr` includes a high-performance cartographic rendering engine built on top of Matplotlib and Cartopy, optimized to render maps in less than 2 seconds using pre-cached local NaturalEarth geometries.

## Automatic Title and Filename Conventions

When saving with `-O` or `savefig=True`, filenames and titles follow clean, structured conventions:

- **Filename format**: `<store>_<subgroup>_<param>_<date>_<timestep>.png`  
  *Example*: `aladin_2026081900_surface_2t_2026081903_t03.png`
- **Title format (2-line layout)**:  
  ```text
  Store: <store> | Group: <group>
  Param: <param_description> [<unit>] | Validity: <datetime> (+<step>h)
  ```

---

## 1. Scalar Field Plots

```bash
# Plot with automatic naming and 2-line header
meteo2zarr plot output_zarr/aladin_2026081900 -f 2t --timestep 3 -O

# Shaded contour plot (contourf) with custom colormap
meteo2zarr plot output_zarr/aladin_2026081900 -f 2t --pm contourf -c turbo -O

# Centering colormap on 0 (ideal for anomalies or Celsius temperature around 0°C)
meteo2zarr plot output_zarr/aladin_2026081900 -f 2t -t -O

# Clamped range min/max
meteo2zarr plot output_zarr/aladin_2026081900 -f 2t -m "0,45" -O
```

---

## 2. Wind Vector Plots

```bash
# Plot meteorological wind barbs
meteo2zarr plot output_zarr/aladin_2026081900 --wU 10u --wV 10v --vpm barbs -s 15 -O

# Plot wind arrows (quivers) over scalar field (2t background)
meteo2zarr plot output_zarr/aladin_2026081900 -f 2t --wU 10u --wV 10v --vpm quiver -s 12 -O

# Streamlines (streamplot)
meteo2zarr plot output_zarr/aladin_2026081900 --wU 10u --wV 10v --vpm streamplot -O
```

---

## 3. Geographic Zooming

Zoom onto specific coordinate bounding boxes using the `--zoom` argument:

```bash
meteo2zarr plot output_zarr/aladin_2026081900 -f 2t --zoom "lonmin=-2, lonmax=12, latmin=30, latmax=40" -O
```

---

## 4. Python API Plotting

```python
import meteo2zarr as m2z

store = m2z.open("output_zarr/aladin_2026081900")

# Interactive display (plt.show())
store.plot(field="2t", timestep=0)

# Export with automatic naming in current folder
store.plot(field="2t", timestep=3, savefig=True)

# Export to specific directory with custom title
store.plot(
    field="tp_3h",
    timestep=3,
    group="surface_3h",
    title="Cumulative 3h Rain Forecast",
    savefig="./figures/my_custom_plot.png",
    dpi=200,
)
```
