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
import zarr

logger = logging.getLogger("meteo2zarr.store")


def _format_time_coords(ds: xr.Dataset) -> List[str]:
    """Safely extract and format time coordinates from 0D scalar, 1D, or multi-D arrays."""
    for tk in ("time", "valid_time", "step", "forecast_time"):
        if tk in ds.coords:
            val = ds[tk].values
            if val.ndim == 0:
                return [str(val)[:19]]
            else:
                return [str(t)[:19] for t in val]
    return []


class MeteoZarr:
    """Convenience class to open, inspect, slice, and plot any meteo2zarr / Zarr store."""

    def __init__(self, path: Union[str, Path]) -> None:
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"Zarr store or directory not found: {self.path}")

        self.groups: Dict[str, xr.Dataset] = {}
        self._load()

    def _load(self) -> None:
        """Robust loader handling single stores, internal sub-groups, and multi-file stores."""
        # Case 1: Direct Zarr store (.zgroup / .zattrs / .zmetadata)
        if (self.path / ".zgroup").exists() or (self.path / ".zattrs").exists() or (self.path / ".zmetadata").exists():
            try:
                ds = xr.open_zarr(str(self.path), consolidated=True)
                if len(ds.data_vars) > 0:
                    self.groups[self.path.stem] = ds
            except Exception:
                pass

            # Check for internal nested Zarr groups (e.g. root.keys() -> ['run_2025102300', ...])
            try:
                zg = zarr.open(str(self.path), mode="r")
                if hasattr(zg, "group_keys"):
                    for subg in zg.group_keys():
                        try:
                            ds_sub = xr.open_zarr(str(self.path), group=subg, consolidated=True)
                            self.groups[subg] = ds_sub
                        except Exception:
                            try:
                                ds_sub = xr.open_zarr(str(self.path), group=subg, consolidated=False)
                                self.groups[subg] = ds_sub
                            except Exception:
                                pass
            except Exception:
                pass

        # Case 2: Multi-folder store directory (e.g. surface.zarr, alt_pressure.zarr)
        if not self.groups:
            zarr_folders = sorted(list(self.path.glob("*.zarr")))
            for zf in zarr_folders:
                try:
                    self.groups[zf.stem] = xr.open_zarr(str(zf), consolidated=True)
                except Exception:
                    try:
                        self.groups[zf.stem] = xr.open_zarr(str(zf), consolidated=False)
                    except Exception:
                        pass

        # Case 3: Fallback standard open
        if not self.groups:
            try:
                ds = xr.open_zarr(str(self.path), consolidated=False)
                self.groups[self.path.stem] = ds
            except Exception as e:
                raise ValueError(f"Could not open valid Zarr store at: {self.path} (error: {e})")

    def what(
        self,
        details: Optional[str] = None,
        sortfields: bool = False,
        stdout: bool = False,
        output_dir: Optional[Union[str, Path]] = None,
        verbose: bool = False,
    ) -> str:
        """Inspect dataset structure, groups, variables, levels, and times."""
        info_lines = []
        sep = "========================================================================"
        info_lines.append(sep)
        info_lines.append(f"METEO2ZARR INSPECTION: {self.path.name}")
        info_lines.append(sep)

        for gname, ds in self.groups.items():
            times = _format_time_coords(ds)
            var_names = list(ds.data_vars.keys())
            if sortfields:
                var_names = sorted(var_names)

            t_start = times[0] if times else "Static / None"
            t_end = times[-1] if times else "Static / None"
            lat_name = "latitude" if "latitude" in ds.coords else ("lat" if "lat" in ds.coords else None)
            lon_name = "longitude" if "longitude" in ds.coords else ("lon" if "lon" in ds.coords else None)
            lat_len = len(ds[lat_name]) if lat_name else 0
            lon_len = len(ds[lon_name]) if lon_name else 0

            info_lines.append(f"\nGroup: '{gname}' ({len(var_names)} variables, {len(times)} timesteps)")
            info_lines.append(f"  Time range  : {t_start} -> {t_end}")
            if (details in ("time", "times") or verbose) and times:
                if len(times) <= 15:
                    info_lines.append(f"  Timesteps ({len(times)}) : " + ", ".join(times))
                else:
                    info_lines.append(f"  Timesteps ({len(times)}) : " + ", ".join(times[:6]) + " ... " + ", ".join(times[-4:]))
            info_lines.append(f"  Grid size   : {lat_len} latitudes x {lon_len} longitudes")
            
            if details == "grid" and lat_name and lon_name:
                lats = ds[lat_name].values
                lons = ds[lon_name].values
                if len(lats) > 1 and len(lons) > 1:
                    info_lines.append(f"  Lat bounds  : [{lats[0]:.4f} .. {lats[-1]:.4f}] (step ~ {abs(lats[1]-lats[0]):.4f})")
                    info_lines.append(f"  Lon bounds  : [{lons[0]:.4f} .. {lons[-1]:.4f}] (step ~ {abs(lons[1]-lons[0]):.4f})")

            info_lines.append("  Variables   :")
            for vname in var_names:
                da = ds[vname]
                long_name = da.attrs.get("long_name", da.attrs.get("GRIB_name", vname))
                unit = da.attrs.get("units", da.attrs.get("unit", da.attrs.get("GRIB_units", "unknown")))
                ltype = da.attrs.get("level_type", da.attrs.get("GRIB_typeOfLevel", "surface"))
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
        """Extract a single meteorological DataArray."""
        target_ds = None

        if group:
            if group in self.groups and var_name in self.groups[group]:
                target_ds = self.groups[group]
        else:
            for gname, gds in self.groups.items():
                if var_name in gds:
                    target_ds = gds
                    break

        if target_ds is None:
            raise KeyError(f"Field '{var_name}' not found in any group.")

        da = target_ds[var_name]

        time_dim = "time" if "time" in da.dims else ("valid_time" if "valid_time" in da.dims else None)
        if timestep is not None and time_dim and da.sizes.get(time_dim, 0) > 1:
            if isinstance(timestep, int):
                da = da.isel({time_dim: timestep})
            else:
                da = da.sel({time_dim: timestep})

        return da

    def _resolve_group_for_field(self, var_name: str, group: Optional[str] = None) -> str:
        """Find the group name containing a given variable."""
        if group and group in self.groups:
            return group
        for gname, gds in self.groups.items():
            if var_name in gds:
                return gname
        return ""

    def generate_default_filename(
        self,
        var_name: str,
        group: str,
        da: xr.DataArray,
        timestep: int = 0,
        ext: str = "png",
    ) -> str:
        """Construct standard default plot filename: zarrStore_subgroups_parameters_date_timestep.png"""
        store_base = self.path.stem.replace(".zarr", "")
        subgroup_part = f"_{group}" if (group and group != store_base) else ""
        
        time_dim = "time" if "time" in da.coords else ("valid_time" if "valid_time" in da.coords else None)
        date_str = "static"
        if time_dim:
            val = str(da[time_dim].values)
            clean_dt = re.sub(r"[^0-9]", "", val)[:10]
            if clean_dt:
                date_str = clean_dt

        step_str = f"t{timestep:02d}"
        return f"{store_base}{subgroup_part}_{var_name}_{date_str}_{step_str}.{ext}"

    def generate_default_title(
        self,
        var_name: str,
        group: str,
        da: xr.DataArray,
        timestep: int = 0,
    ) -> str:
        """Construct standard default plot title: Store: <store> | Group: <group> | Parameter: <param> | Date: <date> | Validity: <val>"""
        store_base = self.path.name
        long_name = da.attrs.get("long_name", var_name)
        unit = da.attrs.get("units", da.attrs.get("unit", da.attrs.get("GRIB_units", "")))
        param_desc = f"{long_name} ({var_name})" if long_name != var_name else var_name
        if unit:
            param_desc += f" [{unit}]"

        time_dim = "time" if "time" in da.coords else ("valid_time" if "valid_time" in da.coords else None)
        val_time = str(da[time_dim].values)[:19] if time_dim else "Static"

        line1_parts = [f"Store: {store_base}"]
        if group and group != self.path.stem:
            line1_parts.append(f"Group: {group}")
        line1 = " | ".join(line1_parts)
        line2 = f"Param: {param_desc} | Validity: {val_time} (+{timestep:02d}h)"
        return line1 + chr(10) + line2

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
        savefig: Optional[Union[bool, str, Path]] = None,
        use_cartopy: bool = True,
        figsize: tuple = (11, 8),
        dpi: int = 150,
    ) -> Any:
        """Fast and rich cartographic plotter."""
        import matplotlib.pyplot as plt
        import matplotlib.colors as mcolors

        is_wind_vector = (wu is not None and wv is not None)
        if not field and not is_wind_vector:
            raise ValueError("Either `field` or both `wu` and `wv` must be provided.")

        da_scalar = None
        da_u = None
        da_v = None
        resolved_group = group or ""

        if is_wind_vector:
            da_u = self.readfield(wu, timestep=timestep, group=group)
            da_v = self.readfield(wv, timestep=timestep, group=group)
            resolved_group = self._resolve_group_for_field(wu, group)
            lat_k = "latitude" if "latitude" in da_u.coords else "lat"
            lon_k = "longitude" if "longitude" in da_u.coords else "lon"
            lats = da_u.coords[lat_k].values
            lons = da_u.coords[lon_k].values
            da_main = da_u
            param_tag = f"wind_{wu}_{wv}"
        else:
            da_scalar = self.readfield(field, timestep=timestep, group=group)
            resolved_group = self._resolve_group_for_field(field, group)
            lat_k = "latitude" if "latitude" in da_scalar.coords else "lat"
            lon_k = "longitude" if "longitude" in da_scalar.coords else "lon"
            lats = da_scalar.coords[lat_k].values
            lons = da_scalar.coords[lon_k].values
            da_main = da_scalar
            param_tag = field

        # Parse zoom
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
            else:
                lon_min, lon_max = float(np.nanmin(lons)), float(np.nanmax(lons))
                lat_min, lat_max = float(np.nanmin(lats)), float(np.nanmax(lats))
                # Only auto-extent for regional domains (not global)
                if abs(lon_max - lon_min) < 350:
                    ax.set_extent([lon_min, lon_max, lat_min, lat_max], crs=ccrs.PlateCarree())

            try:
                ax.coastlines(resolution="50m", color="black", linewidth=0.8)
                ax.add_feature(cfeature.BORDERS.with_scale("50m"), linestyle=":", edgecolor="black")
            except Exception:
                try:
                    ax.coastlines(resolution="110m", color="black", linewidth=0.8)
                except Exception:
                    pass

            try:
                gl = ax.gridlines(draw_labels=False, linestyle="--", alpha=0.5)
            except Exception:
                pass
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

            unit = da_scalar.attrs.get("units", da_scalar.attrs.get("unit", da_scalar.attrs.get("GRIB_units", "")))
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

        # Title: Use custom title if provided, otherwise standard structured title
        final_title = title if title is not None else self.generate_default_title(param_tag, resolved_group, da_main, timestep=timestep)
        ax.set_title(final_title, fontsize=11, pad=10)
        plt.tight_layout()

        # Handle savefig (custom filename vs default automatic naming)
        if savefig:
            if savefig is True:
                out_name = self.generate_default_filename(param_tag, resolved_group, da_main, timestep=timestep)
                out_file = Path(os.getcwd()) / out_name
            else:
                out_file = Path(savefig)
                if out_file.is_dir():
                    out_name = self.generate_default_filename(param_tag, resolved_group, da_main, timestep=timestep)
                    out_file = out_file / out_name

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
