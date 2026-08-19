# Frequently Asked Questions (FAQ)

### Spatial Multiscale Pyramids Support
**Q: Does `meteo2zarr` support multiscale spatial pyramids for ultra-fast web map zooming?**  
**A:** Yes! The underlying Zarr and Xarray multi-group design is fully compatible with multiscale pyramids (downsampling pyramids with spatial stride $2\times2$, $4\times4$). You can generate downsampled spatial subgroups using standard Dask coarsening:
```python
# Downsample for web tile visualization
ds_coarse = ds.coarsen(y=2, x=2, boundary="trim").mean()
ds_coarse.to_zarr(store_path, group="surface/scale_2", mode="a")
```
This enables sub-millisecond tile fetching in MapLibre, Leaflet, or OpenLayers web applications.

---

### Test Suite and Coverage Quality
**Q: How is the reliability and mathematical accuracy of `meteo2zarr` tested?**  
**A:** `meteo2zarr` undergoes a strict, automated end-to-end test suite (`pytest`) on **real operational NWP model files** (AROME and ALADIN in FA format, and AROME in GRIB format):
- **Exact Mathematical Zero-Difference ($\Delta = 0.0$)**: Verified between raw binary fields (EPyGrAM/ecCodes) and converted Zarr stores.
- **Precipitation Decumulation Identity**: Verified that sliding window rain formulas `RR(t) - RR(t-N)` produce bit-identical results.
- **Code Coverage**: Over **91% coverage** on critical modules (`io/writer.py`, `processing/accumulations.py`, `io/grib.py`).
