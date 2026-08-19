"""Interactive Reader, Inspector, and Plotter for Zarr Meteorological Datasets."""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import numpy as np
import xarray as xr

logger = logging.getLogger("meteo2zarr.store")


class MeteoZarr:
    """Convenience class to open, inspect, slice, and plot meteo2zarr stores."""

    def __init__(self, path: Union[str, Path]) -> None:
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"Zarr store or directory not found: {self.path}")

        self.groups: Dict[str, xr.Dataset] = {}
        self._load()

    def _load(self) -> None:
        """Loads single store or all nested group stores."""
        if (self.path / ".zgroup").exists() or (self.path / ".zattrs").exists() or (self.path / ".zmetadata").exists():
            # Single Zarr store
            ds = xr.open_zarr(str(self.path), consolidated=True)
            grp_name = self.path.stem
            self.groups[grp_name] = ds
        else:
            # Multi-group directory (e.g., surface.zarr, alt_pressure.zarr)
            zarr_folders = sorted(list(self.path.glob("*.zarr")))
            if not zarr_folders:
                raise ValueError(f"No .zarr stores found in {self.path}")
            for zf in zarr_folders:
                grp_name = zf.stem
                self.groups[grp_name] = xr.open_zarr(str(zf), consolidated=True)

    def what(self, verbose: bool = True) -> Dict[str, Any]:
        """Inspect and print dataset structure, groups, variables, levels, and times."""
        summary = {}
        for gname, ds in self.groups.items():
            times = [str(t) for t in ds.time.values] if "time" in ds.coords else []
            vars_info = {}
            for v in ds.data_vars:
                da = ds[v]
                vars_info[v] = {
                    "long_name": da.attrs.get("long_name", v),
                    "units": da.attrs.get("units", da.attrs.get("unit", "unknown")),
                    "level_type": da.attrs.get("level_type", "surface"),
                    "level": da.attrs.get("level", 0.0),
                    "shape": list(da.shape),
                }

            summary[gname] = {
                "variables": vars_info,
                "n_timesteps": len(times),
                "time_range": (times[0], times[-1]) if times else ("None", "None"),
                "grid": {
                    "latitudes": len(ds.latitude) if "latitude" in ds.coords else 0,
                    "longitudes": len(ds.longitude) if "longitude" in ds.coords else 0,
                },
            }

        if verbose:
            print("=" * 65)
            print(f"METEO2ZARR INSPECTION: {self.path.name}")
            print("=" * 65)
            for gname, info in summary.items():
                print(f"\nGroup: '{gname}' ({len(info['variables'])} variables, {info['n_timesteps']} timesteps)")
                print(f"  Time range: {info['time_range'][0]} -> {info['time_range'][1]}")
                print(f"  Grid size : {info['grid']['latitudes']} x {info['grid']['longitudes']}")
                print("  Variables :")
                for vname, vmeta in info["variables"].items():
                    print(f"    - {vname:<16} : {vmeta['long_name']} [{vmeta['units']}]")
            print("=" * 65)

        return summary

    def listfields(self, group: Optional[str] = None) -> List[str]:
        """Return list of all variable names available."""
        if group:
            if group not in self.groups:
                raise KeyError(f"Group '{group}' not found. Available: {list(self.groups.keys())}")
            return list(self.groups[group].data_vars.keys())
        
        all_vars = []
        for gds in self.groups.values():
            all_vars.extend(list(gds.data_vars.keys()))
        return sorted(list(set(all_vars)))

    def readfield(
        self,
        var_name: str,
        timestep: Optional[Union[int, str]] = None,
        group: Optional[str] = None,
    ) -> xr.DataArray:
        """Extract a single meteorological DataArray by name and optional timestep."""
        target_ds = None
        if group:
            if group in self.groups and var_name in self.groups[group]:
                target_ds = self.groups[group]
        else:
            for gds in self.groups.values():
                if var_name in gds:
                    target_ds = gds
                    break

        if target_ds is None:
            raise KeyError(f"Field '{var_name}' not found in any group.")

        da = target_ds[var_name]

        if timestep is not None:
            if isinstance(timestep, int):
                da = da.isel(time=timestep)
            else:
                da = da.sel(time=timestep)

        return da

    def plot(
        self,
        var_name: str,
        timestep: int = 0,
        group: Optional[str] = None,
        cmap: str = "Spectral_r",
        title: Optional[str] = None,
        savefig: Optional[Union[str, Path]] = None,
        figsize: tuple = (10, 7),
        dpi: int = 200,
    ) -> Any:
        """Plot a 2D spatial map of a given variable and save to file if requested."""
        import matplotlib.pyplot as plt

        da = self.readfield(var_name, timestep=timestep, group=group)
        data = da.values
        lats = da.coords["latitude"].values
        lons = da.coords["longitude"].values

        fig, ax = plt.subplots(figsize=figsize)
        mesh = ax.pcolormesh(lons, lats, data, cmap=cmap, shading="auto")
        
        unit = da.attrs.get("units", da.attrs.get("unit", ""))
        cbar = plt.colorbar(mesh, ax=ax, orientation="vertical", pad=0.03, aspect=30)
        cbar.set_label(f"{var_name} ({unit})")

        time_str = str(da.time.values)[:16] if "time" in da.coords else ""
        long_name = da.attrs.get("long_name", var_name)
        plot_title = title or f"{long_name} | Valid: {time_str}"
        ax.set_title(plot_title, fontsize=12, pad=10)
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")
        ax.grid(True, linestyle="--", alpha=0.5)

        plt.tight_layout()

        if savefig:
            out_file = Path(savefig)
            out_file.parent.mkdir(parents=True, exist_ok=True)
            plt.savefig(str(out_file), dpi=dpi, bbox_inches="tight")
            print(f"[OK] Figure saved to: {out_file}")

        return fig, ax


def open_zarr(path: Union[str, Path]) -> MeteoZarr:
    """Convenience factory function to open a meteo2zarr store."""
    return MeteoZarr(path)
