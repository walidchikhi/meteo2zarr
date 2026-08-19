"""Interactive Reader, Inspector, and Plotter for Zarr Meteorological Datasets."""

import builtins
import io
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
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

    def what(
        self,
        details: Optional[str] = None,
        sortfields: bool = False,
        stdout: bool = False,
        output_dir: Optional[Union[str, Path]] = None,
        verbose: bool = False,
    ) -> str:
        """Inspect dataset structure, groups, variables, levels, and times.
        
        Like `epy_what`:
        - By default, writes `<zarr_name>.info` in current working directory (where command is run).
        - If `stdout=True` (-o / --stdout), prints to stdout rather than writing a file.
        """
        info_lines = []
        sep = "========================================================================"
        info_lines.append(sep)
        info_lines.append(f"METEO2ZARR INSPECTION: {self.path.name}")
        info_lines.append(sep)

        for gname, ds in self.groups.items():
            times = [str(t) for t in ds.time.values] if "time" in ds.coords else []
            var_names = list(ds.data_vars.keys())
            if sortfields:
                var_names = sorted(var_names)

            t_start = times[0][:19] if times else "None"
            t_end = times[-1][:19] if times else "None"
            lat_len = len(ds.latitude) if "latitude" in ds.coords else 0
            lon_len = len(ds.longitude) if "longitude" in ds.coords else 0

            info_lines.append(f"\nGroup: '{gname}' ({len(var_names)} variables, {len(times)} timesteps)")
            info_lines.append(f"  Time range  : {t_start} -> {t_end}")
            info_lines.append(f"  Grid size   : {lat_len} latitudes x {lon_len} longitudes")
            
            if details == "grid":
                if "latitude" in ds.coords and "longitude" in ds.coords:
                    lats = ds.latitude.values
                    lons = ds.longitude.values
                    info_lines.append(f"  Lat bounds  : [{lats[0]:.4f} .. {lats[-1]:.4f}] (step ~ {abs(lats[1]-lats[0]):.4f})")
                    info_lines.append(f"  Lon bounds  : [{lons[0]:.4f} .. {lons[-1]:.4f}] (step ~ {abs(lons[1]-lons[0]):.4f})")

            info_lines.append("  Variables   :")
            for vname in var_names:
                da = ds[vname]
                long_name = da.attrs.get("long_name", vname)
                unit = da.attrs.get("units", da.attrs.get("unit", "unknown"))
                ltype = da.attrs.get("level_type", "surface")
                lval = da.attrs.get("level_value", da.attrs.get("level", 0.0))
                
                line = f"    - {vname:<16} : {long_name} [{unit}] (type: {ltype}"
                if lval:
                    line += f", level: {lval}"
                line += ")"
                
                if details == "chunks":
                    line += f" | chunks: {da.encoding.get('chunks', list(da.shape))}"
                elif details == "compression":
                    line += f" | compressor: {da.encoding.get('compressor', 'default')}"

                info_lines.append(line)

        info_lines.append("\n" + sep)
        report_text = "\n".join(info_lines)

        if stdout:
            print(report_text)
        else:
            cwd = Path(output_dir) if output_dir else Path(os.getcwd())
            info_file_path = cwd / f"{self.path.name}.info"
            with builtins.open(info_file_path, "w", encoding="utf-8") as f:
                f.write(report_text + "\n")
            print(f"[OK] Info written to: {info_file_path}")

        return report_text

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
        field: Optional[str] = None,
        wu: Optional[str] = None,
        wv: Optional[str] = None,
        timestep: int = 0,
        group: Optional[str] = None,
        plot_method: str = "pcolormesh",
        colormap: str = "Spectral_r",
        minmax: Optional[Union[Tuple[float, float], str]] = None,
        levelsnumber: int = 50,
        center_cmap_on_0: bool = False,
        zoom: Optional[str] = None,
        vector_plot_method: str = "barbs",
        vectors_subsampling: int = 15,
        title: Optional[str] = None,
        savefig: Optional[Union[str, Path]] = None,
        use_cartopy: bool = True,
        figsize: tuple = (10, 7),
        dpi: int = 200,
    ) -> Any:
        """Rich cartographic and meteorological plotter inspired by epy_cartoplot."""
        import matplotlib.pyplot as plt
        import matplotlib.colors as mcolors

        # Determine if scalar or vector wind plot
        is_wind_vector = (wu is not None and wv is not None)
        if not field and not is_wind_vector:
            raise ValueError("Either `field` or both `wu` and `wv` must be provided.")

        da_scalar = None
        da_u = None
        da_v = None

        if is_wind_vector:
            da_u = self.readfield(wu, timestep=timestep, group=group)
            da_v = self.readfield(wv, timestep=timestep, group=group)
            lats = da_u.coords["latitude"].values
            lons = da_u.coords["longitude"].values
            da_main = da_u
        else:
            da_scalar = self.readfield(field, timestep=timestep, group=group)
            lats = da_scalar.coords["latitude"].values
            lons = da_scalar.coords["longitude"].values
            da_main = da_scalar

        # Parse zoom if provided ('lonmin=-5, lonmax=1.2, latmin=40.8, latmax=51')
        zoom_extent = None
        if zoom:
            m = re.findall(r"([a-zA-Z_]+)\s*=\s*([-+]?\d*\.?\d+)", zoom)
            z_dict = {k.lower(): float(v) for k, v in m}
            if all(k in z_dict for k in ("lonmin", "lonmax", "latmin", "latmax")):
                zoom_extent = [z_dict["lonmin"], z_dict["lonmax"], z_dict["latmin"], z_dict["latmax"]]

        # Parse minmax
        vmin, vmax = None, None
        if minmax:
            if isinstance(minmax, str):
                parts = [p.strip() for p in minmax.split(",")]
                vmin = float(parts[0]) if parts[0] != "None" else None
                vmax = float(parts[1]) if parts[1] != "None" else None
            elif isinstance(minmax, (list, tuple)):
                vmin, vmax = minmax[0], minmax[1]

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
            if zoom_extent:
                ax.set_extent(zoom_extent, crs=ccrs.PlateCarree())

            ax.coastlines(resolution="10m", color="black", linewidth=0.8)
            ax.add_feature(cfeature.BORDERS, linestyle=":", edgecolor="black")
            gl = ax.gridlines(draw_labels=True, linestyle="--", alpha=0.5)
            gl.top_labels = False
            gl.right_labels = False
            transform = ccrs.PlateCarree()
        else:
            fig, ax = plt.subplots(figsize=figsize)
            if zoom_extent:
                ax.set_xlim(zoom_extent[0], zoom_extent[1])
                ax.set_ylim(zoom_extent[2], zoom_extent[3])
            ax.set_xlabel("Longitude")
            ax.set_ylabel("Latitude")
            ax.grid(True, linestyle="--", alpha=0.5)
            transform = None

        # Norm / centering
        norm = None
        if center_cmap_on_0:
            if da_scalar is not None:
                max_abs = np.nanmax(np.abs(da_scalar.values))
                norm = mcolors.TwoSlopeNorm(vmin=-max_abs, vcenter=0.0, vmax=max_abs)

        # 1. Scalar Plot
        if da_scalar is not None:
            data = da_scalar.values
            kw = {"cmap": colormap, "vmin": vmin, "vmax": vmax}
            if norm:
                kw["norm"] = norm
            if transform:
                kw["transform"] = transform

            if plot_method == "contourf":
                mesh = ax.contourf(lons, lats, data, levels=levelsnumber, **kw)
            elif plot_method == "contour":
                mesh = ax.contour(lons, lats, data, levels=levelsnumber, **kw)
                ax.clabel(mesh, inline=True, fontsize=8)
            else:  # pcolormesh
                mesh = ax.pcolormesh(lons, lats, data, shading="auto", **kw)

            unit = da_scalar.attrs.get("units", da_scalar.attrs.get("unit", ""))
            cbar = plt.colorbar(mesh, ax=ax, orientation="vertical", pad=0.03, aspect=30)
            cbar.set_label(f"{field} ({unit})")

        # 2. Wind Vector Plot
        if is_wind_vector:
            u_val = da_u.values
            v_val = da_v.values
            speed = np.sqrt(u_val**2 + v_val**2)

            step = max(1, vectors_subsampling)
            sub_lons = lons[::step] if lons.ndim == 1 else lons[::step, ::step]
            sub_lats = lats[::step] if lats.ndim == 1 else lats[::step, ::step]
            sub_u = u_val[::step, ::step] if u_val.ndim == 2 else u_val
            sub_v = v_val[::step, ::step] if v_val.ndim == 2 else v_val

            if not field:
                # Plot background speed
                kw_bg = {"cmap": colormap, "shading": "auto"}
                if transform:
                    kw_bg["transform"] = transform
                mesh = ax.pcolormesh(lons, lats, speed, **kw_bg)
                cbar = plt.colorbar(mesh, ax=ax, orientation="vertical", pad=0.03, aspect=30)
                cbar.set_label("Wind Speed (m/s)")

            vec_kw = {"transform": transform} if transform else {}
            if vector_plot_method == "quiver":
                ax.quiver(sub_lons, sub_lats, sub_u, sub_v, color="black", **vec_kw)
            elif vector_plot_method == "streamplot":
                ax.streamplot(lons, lats, u_val, v_val, color="black", density=1.5, **vec_kw)
            else:  # barbs
                ax.barbs(sub_lons, sub_lats, sub_u, sub_v, length=5.5, color="black", **vec_kw)

        # Title
        time_str = str(da_main.time.values)[:19] if "time" in da_main.coords else ""
        def_title = f"{field or f'Wind ({wu}/{wv})'} | Valid: {time_str}"
        ax.set_title(title or def_title, fontsize=12, pad=10)
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


def open(path: Union[str, Path]) -> MeteoZarr:
    """Open a meteo2zarr dataset store."""
    return MeteoZarr(path)


# Alias
open_zarr = open
