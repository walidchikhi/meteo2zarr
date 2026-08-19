# Frequently Asked Questions (FAQ)

### Q: Why is `meteo2zarr what` so much faster than legacy tools?
A: `meteo2zarr` reads the consolidated `.zmetadata` header stored at the root of the Zarr directory. It does not open or decode individual chunk files on disk.

### Q: Why are my plots rendering almost instantly?
A: Coastal and geopolitical shapefiles from *NaturalEarth* (`50m` resolution) are pre-fetched into your local cache directory (`~/.local/share/cartopy/`). No network requests are made during runtime.

### Q: Can I read custom or non-standard Zarr datasets?
A: Yes! `meteo2zarr.open()` auto-detects monolithic stores, grouped stores, and internal nested directories (like `run_YYYYMMDDHH`).
