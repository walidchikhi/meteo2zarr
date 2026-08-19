"""Interactive Reader, Inspector, and Plotter for Zarr Meteorological Datasets."""

import io
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
            ds = xr.open_zarr(str(self.path), consolidated=True)
            grp_name = self.path.stem
            self.groups[grp_name] = ds
        else:
            zarr_folders = sorted(list(self.path.glob("*.zarr")))
            if not zarr_folders:
                raise ValueError(f"No .zarr stores found in {self.path}")
            for zf in zarr_folders:
                grp_name = zf.stem
                self.groups[grp_name] = xr.open_zarr(str(zf), consolidated=True)

    def what(self, write_info: bool = True, verbose: bool = True) -> Dict[str, Any]:
        """Inspect dataset structure, groups, variables, levels, and times.
        
        Writes summary into `<zarr_name>.info` file alongside the Zarr store.
        """
        summary = {}
        info_lines = []
        
        sep = "=" * 70
        info_lines.append(sep)
        info_lines.append(f"METEO2ZARR INSPECTION: {self.path.name}")
        info_lines.append(sep)

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

            t_start = times[0][:19] if times else "None"
            t_end = times[-1][:19] if times else "None"
            lat_len = len(ds.latitude) if "latitude" in ds.coords else 0
            lon_len = len(ds.longitude) if "longitude" in ds.coords else 0

            summary[gname] = {
                "variables": vars_info,
                "n_timesteps": len(times),
                "time_range": (t_start, t_end),
                "grid": {"latitudes": lat_len, "longitudes": lon_len},
            }

            info_lines.append(f"\nGroup: '{gname}' ({len(vars_info)} variables, {len(times)} timesteps)")
            info_lines.append(f"  Time range: {t_start} -> {t_end}")
            info_lines.append(f"  Grid size : {lat_len} x {lon_len}")
            info_lines.append("  Variables :")
            for vname, vmeta in vars_info.items():
                info_lines.append(f"    - {vname:<16} : {vmeta['long_name']} [{vmeta['units']}] (lvl {vmeta['level']})")

        info_lines.append("\n" + sep)
        report_text = "\n".join(info_lines)

        # 1. Print to terminal if verbose
        if verbose:
            print(report_text)

        # 2. Write <store_name>.info file
        if write_info:
            info_file_path = self.path.parent / f"{self.path.name}.info"
            with open(info_file_path, "w", encoding="utf-8") as f:
                f.write(report_text + "\n")
            if verbose:
                print(f"[OK] Info written to: {info_file_path}")

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
        use_cartopy: bool = True,
        figsize: tuple = (10, 7),
        dpi: int = 200,
    ) -> Any:
        """Plot a 2D spatial map of a variable.
        
        Shows interactively with plt.show() if savefig is None,
        or saves to disk if savefig is provided.
        """
        import matplotlib.pyplot as plt

        da = self.readfield(var_name, timestep=timestep, group=group)
        data = da.values
        lats = da.coords["latitude"].values
        lons = da.coords["longitude"].values

        has_cartopy = False
        if use_cartopy:
            try:
                import cartopy.crs as ccrs
                import cartopy.feature as cfeature
                has_cartopy = True
            except ImportError:
                has_cartopy = False

        if has_cartopy:
            fig, ax = plt.subplots(figsize=figsize, subplot_kw={"projection": ccrs.PlateCarree()})
            mesh = ax.pcolormesh(lons, lats, data, cmap=cmap, shading="auto", transform=ccrs.PlateCarree())
            ax.coastlines(resolution="10m", color="black", linewidth=0.8)
            ax.add_feature(cfeature.BORDERS, linestyle=":", edgecolor="black")
            gl = ax.gridlines(draw_labels=True, linestyle="--", alpha=0.5)
            gl.top_labels = False
            gl.right_labels = False
        else:
            fig, ax = plt.subplots(figsize=figsize)
            mesh = ax.pcolormesh(lons, lats, data, cmap=cmap, shading="auto")
            ax.set_xlabel("Longitude")
            ax.set_ylabel("Latitude")
            ax.grid(True, linestyle="--", alpha=0.5)

        unit = da.attrs.get("units", da.attrs.get("unit", ""))
        cbar = plt.colorbar(mesh, ax=ax, orientation="vertical", pad=0.03, aspect=30)
        cbar.set_label(f"{var_name} ({unit})")

        time_str = str(da.time.values)[:19] if "time" in da.coords else ""
        long_name = da.attrs.get("long_name", var_name)
        plot_title = title or f"{long_name} | Valid: {time_str}"
        ax.set_title(plot_title, fontsize=12, pad=10)
        plt.tight_layout()

        if savefig:
            out_file = Path(savefig)
            out_file.parent.mkdir(parents=True, exist_ok=True)
            plt.savefig(str(out_file), dpi=dpi, bbox_inches="tight")
            print(f"[OK] Figure saved to: {out_file}")
            plt.close(fig)
        else:
            plt.show()

        return fig, ax


def open_zarr(path: Union[str, Path]) -> MeteoZarr:
    """Convenience factory function to open a meteo2zarr store."""
    return MeteoZarr(path)
