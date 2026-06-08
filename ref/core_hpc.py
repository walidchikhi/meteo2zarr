"""
core_hpc.py  —  NWP → Zarr  |  Dask Lazy Streaming  (v3)
==========================================================

Stratégie principale : Dask lazy + écriture streaming

Usage:
  python core_hpc.py \\
      --model arome --run 2025010900 \\
      --input /scratch/nwp/arome/2025010900 \\
      --output /scratch/zarr \\
      --config /path/to/configs \\
      --dask-workers 8 --chunk-time 6
"""
#!/usr/bin/env python3.12

import os
import sys
import gc
import re
import json
import time
import shutil
import logging
import argparse
import traceback
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed

import numpy as np
import pandas as pd
import xarray as xr
import dask
import dask.array as da
import dask.array as dsa
from dask.distributed import Client, LocalCluster
import zarr
import numcodecs


try:
    import epygram
    epygram.init_env()
    HAS_EPYGRAM = True
except ImportError:
    HAS_EPYGRAM = False

try:
    import cfgrib
    HAS_CFGRIB = True
except ImportError:
    HAS_CFGRIB = False

try:
    import rioxarray  # noqa: F401
    HAS_RIO = True
except ImportError:
    HAS_RIO = False

try:
    from ndpyramid import pyramid_coarsen
    HAS_PYRAMID = True
except ImportError:
    HAS_PYRAMID = False


LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("nwp_converter")

COMPRESSOR = numcodecs.Blosc(cname="zstd", clevel=3, shuffle=numcodecs.Blosc.SHUFFLE)

# Types de niveaux GRIB à scanner
GRIB_LEVEL_TYPES = [
    "isobaricInhPa",
    "heightAboveGround",
    "surface",
    "meanSea",
    "potentialVorticity",
    "entireAtmosphere",
    "theta",
]


# CHARGEMENT DES CONFIGURATIONS

class ConfigLoader:
    """Charge et expose toutes les tables de définition JSON."""

    def __init__(self, config_dir: Optional[str] = None):
        base = Path(config_dir) if config_dir else Path(__file__).parent

        self.fa_defs     = self._load(base / "fa_definitions.json",
                                      {"fields": {}, "levels": {},
                                       "derived_fields": {}, "accumulations": {}})
        self.grib_defs   = self._load(base / "grib_definitions.json",
                                      {"fields": {}, "grib1_keys": {}, "grib2_keys": {}})
        self.zarr_groups = self._load(base / "zarr_groups.json", {"groups": {}})
        self.colormap    = self._load(base / "colormap_config.json", {"zarr_viz": {}})

        logger.info(
            f" Config chargée — FA: {len(self.fa_defs['fields'])} champs  "
            f"| GRIB: {len(self.grib_defs['fields'])} champs  "
            f"| Groupes Zarr: {len(self.zarr_groups.get('groups', {}))}  "
            f"| Colormaps: {len(self.colormap.get('zarr_viz', {}))}"
        )

    @staticmethod
    def _load(path: Path, default: dict) -> dict:
        if path.exists():
            with open(path) as f:
                return json.load(f)
        logger.warning(f"⚠  Config absente: {path.name} → valeurs par défaut")
        return default

    def get_viz(self, shortname: str) -> Optional[dict]:
        """Retourne la config de visualisation pour un shortname."""
        viz = self.colormap.get("zarr_viz", {}).get(shortname)
        if not viz:
            base = re.sub(r"\d+", "", shortname)
            viz = self.colormap.get("zarr_viz", {}).get(base)
        return viz


# RÉSOLUTION DE MÉTADONNÉES FA

class FAMetaResolver:
    """
    Résout les métadonnées d'un identifiant de champ FA/LFA
    en utilisant fa_definitions.json (équivalent table GRIB pour FA).
    """

    def __init__(self, cfg: ConfigLoader):
        self.fields      = cfg.fa_defs.get("fields", {})
        self.levels      = cfg.fa_defs.get("levels", {})
        self.skip_fields = set(cfg.fa_defs.get("skip_fields", []))
        self.cfg         = cfg

    def resolve(self, fa_id: str) -> Optional[Dict[str, Any]]:
        """
        Retourne un dict avec shortname, unit, formula, level_type,
        level_value, description, viz — ou None si non reconnu.
        """
        # 0. Skip fields (support exact match or regex)
        for pattern in self.skip_fields:
            if pattern in fa_id or re.search(pattern, fa_id):
                return None

        # 1. Match exact (champs de surface nommés explicitement)
        if fa_id in self.fields:
            m = self.fields[fa_id]
            return self._build(m, "surface", 0)

        # 2. Décomposition préfixe de niveau + suffixe de champ
        level_type, level_val, suffix = self._parse_level(fa_id)

        # 3. Match du suffixe dans la table des champs
        norm = suffix.replace(".", "_")
        for fs, meta in self.fields.items():
            nfs = fs.replace(".", "_")
            if norm.endswith(nfs) or nfs == norm:
                return self._build(meta, level_type, level_val)

        # 4. Fallback if not recognized: keep it with a generic shortname
        return {
            "shortname":   fa_id.lower().replace(".", "_"),
            "unit":        "unknown",
            "formula":     "None",
            "description": f"Original field {fa_id}",
            "level_type":  level_type,
            "level_value": level_val,
            "viz":         None,
        }

    def _parse_level(self, fa_id: str) -> Tuple[str, float, str]:
        """Extrait le type de niveau, la valeur et le suffixe de champ."""
        prefixes = sorted(self.levels.keys(), key=len, reverse=True)
        for prefix in prefixes:
            if not fa_id.startswith(prefix):
                continue
            info = self.levels[prefix]
            m = re.match(rf"{prefix}(\d+)(.*)", fa_id)
            if m:
                val = int(m.group(1)) * info.get("factor", 1)
                return info["type"], val, m.group(2)
            # Préfixes sans valeur numérique (CLS, SURF)
            if prefix in ("CLS", "SURF"):
                suffix = fa_id[len(prefix):]
                ltype  = info["type"]
                lval   = 2.0 if "TEMPERATURE" in fa_id or "HUMI" in fa_id else \
                         10.0 if "VENT" in fa_id else 0.0
                return ltype, lval, suffix
        return "unknown", 0.0, fa_id

    def _build(self, meta: dict, level_type: str, level_val: float) -> dict:
        sn  = meta["shortname"]
        viz = self.cfg.get_viz(sn)
        return {
            "shortname":   sn,
            "unit":        meta["unit"],
            "formula":     meta.get("formula", "None"),
            "description": meta.get("desc", sn),
            "level_type":  level_type,
            "level_value": level_val,
            "viz":         viz,
        }


# FORMULES PHYSIQUES

def apply_formula_lazy(da: xr.DataArray, formula: str) -> xr.DataArray:
    """
    Applique une formule physique sur un DataArray Dask (lazy).
    L'opération est enregistrée dans le graph Dask, pas calculée.
    """
    if not formula or formula in ("None", "none", ""):
        return da
    if formula == "k2c":
        return da - 273.15
    if formula == "div98":
        return da / 9.80665
    if formula == "percent":
        # On ne peut pas tester max() sur un lazy array sans déclencher compute()
        # → on applique × 100 si les attrs indiquent que c'est en 0-1
        return xr.where(da <= 1.0, da * 100.0, da)
    if formula == "acc":
        return da   # cumulé brut, sera décumulé plus tard
    logger.debug(f"  Formule inconnue '{formula}', ignorée")
    return da


def apply_formula_np(arr: np.ndarray, formula: str) -> np.ndarray:
    """
    Applique une formule physique sur un tableau numpy (eccodes reader).
    """
    if not formula or formula in ("None", "none", "", "acc"):
        return arr
    if formula == "k2c":
        return arr - 273.15
    if formula == "div98":
        return arr / 9.80665
    if formula == "percent":
        mask = arr <= 1.0
        result = arr.copy()
        result[mask] = arr[mask] * 100.0
        return result
    logger.debug(f"  Formule numpy inconnue '{formula}', ignorée")
    return arr


def _read_fa_job(fa_path: Path, cfg: ConfigLoader) -> Optional[xr.Dataset]:
    """Job de lecture FA isolé pour ProcessPool (évite les Segfaults de threads epygram)."""
    # On instancie un reader local au process
    reader = FAReader(cfg)
    return reader.read_one(fa_path)


# LECTEURS PAR FORMAT  (retournent tous un xr.Dataset lazy)

class FAReader:
    """
    Lecteur de fichiers FA/LFA via epygram.
    Chaque fichier = 1 échéance → retourne xr.Dataset(time=1, lat, lon).
    FA n'est pas lazy nativement → on lit tout mais 1 fichier à la fois.
    La lecture multi-fichiers est parallélisée via ThreadPool.
    """

    def __init__(self, cfg: ConfigLoader):
        self.resolver = FAMetaResolver(cfg)
        self.cfg      = cfg

    def read_one(self, fa_path: Path) -> Optional[xr.Dataset]:
        """Lit UN fichier FA, retourne Dataset(time=1) ou None."""
        if not HAS_EPYGRAM:
            raise RuntimeError("epygram non installé — pip install epygram")
        try:
            res        = epygram.formats.resource(str(fa_path), "r")
            field_list = res.listfields()

            # Temps de validité depuis le premier champ lisible
            sample      = res.readfield(field_list[0])
            validity_dt = sample.validity.get()

            data_vars: Dict[str, xr.DataArray] = {}

            for f_id in field_list:
                meta = self.resolver.resolve(f_id)
                if not meta:
                    continue

                field = res.readfield(f_id)
                data  = field.getdata().astype(np.float32)

                # Grille lat/lon
                lons, lats = field.geometry.get_lonlat_grid()
                lat_1d = lats[:, 0] if not np.all(lats[:, 0] == lats[0, 0]) else lats[0, :]
                lon_1d = lons[0, :] if not np.all(lons[0, :] == lons[0, 0]) else lons[:, 0]

                var_key = meta["shortname"]
                if meta["level_type"] in ("isobaric", "height", "pv"):
                    # On évite le niveau 0 (surface) s'il est déjà explicite
                    if meta["level_value"] != 0 or meta["level_type"] == "isobaric":
                        var_key = f"{meta['shortname']}{int(meta['level_value'])}"

                # Wrap en DataArray Dask (1 échéance)
                arr = da.from_array(data[np.newaxis, ...], chunks=(1, -1, -1))
                da_ = xr.DataArray(
                    arr,
                    coords={"time": [validity_dt], "latitude": lat_1d, "longitude": lon_1d},
                    dims=["time", "latitude", "longitude"],
                    name=var_key,
                )
                da_ = apply_formula_lazy(da_, meta["formula"])
                da_.attrs.update({
                    "units":       meta["unit"],
                    "long_name":   meta["description"],
                    "fa_name":     f_id,
                    "level_type":  meta["level_type"],
                    "level_value": meta["level_value"],
                    "shortname":   meta["shortname"],
                })
                if meta.get("viz"):
                    da_.attrs["viz"] = json.dumps(meta["viz"])

                data_vars[var_key] = da_

            res.close()
            if not data_vars:
                logger.warning(f"  ⚠  Aucun champ reconnu dans {fa_path.name}")
                return None
            return xr.Dataset(data_vars)

        except Exception as e:
            logger.warning(f"  ⚠  Lecture FA {fa_path.name}: {e}")
            return None

    def read_all(self, files: List[Path], n_threads: int = 16) -> Optional[xr.Dataset]:
        """
        Lit tous les fichiers FA en parallèle (ThreadPool).
        Retourne un Dataset lazy avec dim time = nb échéances.
        """
        results: Dict[Path, xr.Dataset] = {}

        # epygram FA reading is NOT thread-safe (Segfaults observed). 
        # But ProcessPoolExecutor (multi-processing) is safe because each process has its own address space.
        t_read = time.perf_counter()
        with ProcessPoolExecutor(max_workers=min(len(files), n_threads)) as pool:
            # On utilise une fonction wrapper statique pour faciliter le pickling
            future_to_path = {pool.submit(_read_fa_job, fp, self.cfg): fp for fp in files}
            for future in as_completed(future_to_path):
                fp = future_to_path[future]
                try:
                    ds = future.result()
                    if ds is not None:
                        results[fp] = ds
                except Exception as e:
                    logger.warning(f"  ⚠  {fp.name}: {e}")
        
        logger.debug(f"  Reading took {time.perf_counter()-t_read:.1f}s")

        if not results:
            return None

        datasets = [results[fp] for fp in sorted(results.keys())]
        logger.info(f"  📂 FA: {len(datasets)} fichiers lus")

        # Concat temporel lazy
        merged = xr.concat(datasets, dim="time", data_vars="all", compat="override", coords="minimal")
        merged = merged.sortby("time")
        _, idx = np.unique(merged.time.values, return_index=True)
        return merged.isel(time=idx)


class GRIBReader:
    """
    Lecteur GRIB1/GRIB2 via eccodes (lecture directe des messages).
    
    Pour chaque fichier GRIB, on lit les messages un par un avec eccodes,
    on les organise par (shortname, typeOfLevel, level), et on construit
    des DataArrays xarray avec les dimensions (time, [level,] lat, lon).
    
    Avantages vs cfgrib :
      - Aucun problème de conflits d'unités CF
      - Contrôle total sur chaque message
      - Compatible GRIB1 et GRIB2
    """

    def __init__(self, cfg: ConfigLoader, chunk_time: int = 6):
        self.cfg        = cfg
        self.grib_defs  = cfg.grib_defs.get("fields", {})
        self.ltype_map  = cfg.grib_defs.get("level_type_map", {})
        self.g2_map     = cfg.grib_defs.get("grib2_param_map", {})
        self.g1_map     = cfg.grib_defs.get("grib1_param_map", {})
        self.skip_sn    = set(cfg.grib_defs.get("skip_shortnames", []))
        self.chunk_time = chunk_time

    # ------------------------------------------------------------------ #
    # Public                                                               #
    # ------------------------------------------------------------------ #
    def read_all(self, files: List[Path]) -> Optional[xr.Dataset]:
        """Lit un ou plusieurs fichiers GRIB et retourne un Dataset xarray."""
        try:
            import eccodes
        except ImportError:
            raise RuntimeError("eccodes non installé — pip install eccodes")

        # Structures de collecte :
        # key = (shortname_std, level_type_std, level_value)
        # value = dict: valid_time (pd.Timestamp) -> np.ndarray (lat, lon)
        buckets: Dict[tuple, Dict] = {}
        lats = lons = None

        for fpath in files:
            self._read_file(fpath, buckets)

        if not buckets:
            logger.warning("  ⚠  Aucune donnée GRIB lue (eccodes)")
            return None

        return self._build_dataset(buckets)

    # ------------------------------------------------------------------ #
    # Private : lecture eccodes                                            #
    # ------------------------------------------------------------------ #
    def _read_file(self, fpath: Path, buckets: Dict[tuple, Dict]):
        import eccodes

        try:
            f = open(str(fpath), "rb")
        except OSError as e:
            logger.warning(f"  ⚠ Impossible d'ouvrir {fpath.name}: {e}")
            return

        n_msg = n_kept = 0
        try:
            while True:
                msg = eccodes.codes_grib_new_from_file(f)
                if msg is None:
                    break
                n_msg += 1
                try:
                    self._process_message(msg, buckets)
                    n_kept += 1
                except Exception as e:
                    logger.warning(f"  ⛔ Message {n_msg} ignoré: {e}")
                finally:
                    eccodes.codes_release(msg)
        finally:
            f.close()

        logger.info(f"  📖 {fpath.name}: {n_kept}/{n_msg} messages conservés, buckets={len(buckets)}")

    def _process_message(self, msg, buckets: Dict[tuple, Dict]):
        import eccodes

        # -------- 1. Identification du paramètre --------
        edition = eccodes.codes_get(msg, "edition", ktype=int)

        if edition == 2:
            disc = eccodes.codes_get(msg, "discipline", ktype=int)
            cat  = eccodes.codes_get(msg, "parameterCategory", ktype=int)
            num  = eccodes.codes_get(msg, "parameterNumber", ktype=int)
            g2key = f"{disc}.{cat}.{num}"
            sn_grib = self.g2_map.get(g2key)
            if not sn_grib:
                # Essai via shortName eccodes
                try:
                    sn_grib = eccodes.codes_get(msg, "shortName", ktype=str)
                except Exception:
                    return
        else:  # GRIB1
            try:
                param = str(eccodes.codes_get(msg, "indicatorOfParameter", ktype=int))
                sn_grib = self.g1_map.get(param)
                if not sn_grib:
                    sn_grib = eccodes.codes_get(msg, "shortName", ktype=str)
            except Exception:
                return

        if not sn_grib:
            return

        # Cherche la définition
        field_def = self.grib_defs.get(sn_grib)
        if field_def:
            shortname_std = field_def["shortname"]
            formula       = field_def.get("formula", "None")
            units_std     = field_def.get("unit", "unknown")
            desc_std      = field_def.get("desc", sn_grib)
        else:
            # Champ non mappé → on skip
            return

        # Skip si dans la liste d'exclusion
        if shortname_std in self.skip_sn or sn_grib in self.skip_sn:
            return

        # -------- 2. Level type & valeur --------
        try:
            ltype_grib = eccodes.codes_get(msg, "typeOfLevel", ktype=str)
            level_val  = eccodes.codes_get(msg, "level", ktype=int)
        except Exception:
            ltype_grib = "surface"
            level_val  = 0

        ltype_std = self.ltype_map.get(ltype_grib, "surface")

        # Pour les niveaux hauteur (heightAboveGround), on intègre la hauteur
        # dans le nom pour distinguer 2t de u10v, etc.
        # Ex : "2t" (niveau 2m), "10u" (niveau 10m) → on conserve le shortname
        # Pour isobaricInhPa, on crée une dimension 'level' dans DataArray

        # -------- 3. Temps (valid_time ou step) --------
        try:
            # dataDate + dataTime (HHMM)
            date_int = eccodes.codes_get(msg, "dataDate", ktype=int)  # YYYYMMDD
            time_int = eccodes.codes_get(msg, "dataTime", ktype=int)  # HHMM
            step_h   = eccodes.codes_get(msg, "stepRange", ktype=str)
            # stepRange peut être "0" ou "0-3" pour des cumuls
            # On extrait le temps d'échéance (fin du range)
            step_end = int(step_h.split("-")[-1]) if step_h else 0

            base_time = pd.Timestamp(
                year=date_int // 10000,
                month=(date_int % 10000) // 100,
                day=date_int % 100,
                hour=time_int // 100,
                minute=time_int % 100,
            )
            valid_time = base_time + pd.Timedelta(hours=step_end)
        except Exception:
            valid_time = pd.Timestamp("1970-01-01")

        # -------- 4. Grille (lat/lon + valeurs) --------
        try:
            values = eccodes.codes_get_values(msg).astype("float32")
            ni = eccodes.codes_get(msg, "Ni", ktype=int)
            nj = eccodes.codes_get(msg, "Nj", ktype=int)
            # Latitudes et longitudes (uniquement si grille régulière)
            lats_flat = eccodes.codes_get_array(msg, "latitudes")
            lons_flat = eccodes.codes_get_array(msg, "longitudes")
        except Exception as e:
            raise ValueError(f"Impossible de lire les valeurs: {e}")

        # Reshape en (nj, ni)
        try:
            arr = values.reshape(nj, ni)
            lats_2d = lats_flat.reshape(nj, ni)
            lons_2d = lons_flat.reshape(nj, ni)
        except Exception:
            # Grille non régulière ou taille incohérente
            raise ValueError("Reshape impossible")

        # Coordonnées 1D (on prend la 1ère ligne/colonne → grille lon/lat-régulière)
        lat_1d = lats_2d[:, 0]
        lon_1d = lons_2d[0, :]

        # -------- 5. Application de la formule --------
        arr = apply_formula_np(arr, formula)

        # -------- 6. Remplacement dans les buckets --------
        bucket_key = (shortname_std, ltype_std, level_val)
        if bucket_key not in buckets:
            buckets[bucket_key] = {
                "times": [],
                "arrays": [],
                "lat": lat_1d,
                "lon": lon_1d,
                "units": units_std,
                "desc": desc_std,
                "ltype": ltype_std,
                "level": level_val,
                "accum_formula": formula == "acc",
            }
        b = buckets[bucket_key]
        b["times"].append(valid_time)
        b["arrays"].append(arr)

    # ------------------------------------------------------------------ #
    # Private : construction Dataset xarray                                #
    # ------------------------------------------------------------------ #
    def _build_dataset(self, buckets: Dict[tuple, Dict]) -> xr.Dataset:
        import dask.array as dsa

        data_vars: Dict[str, xr.DataArray] = {}

        # On itère directement sur chaque bucket (un bucket = une variable 3D unique)
        for key, b in buckets.items():
            sn_std, ltype_std, lv = key
            lats  = b["lat"]
            lons  = b["lon"]
            units = b["units"]
            desc  = b["desc"]
            
            # Naming logic : on aplatit le niveau dans le nom pour Titiler (3D uniquement)
            # - isobaric/pv : t + 850 -> t850
            # - surface/height : 2t -> 2t (pas de suffixe si déjà présent), t + 2 -> t2
            if ltype_std in ("isobaric", "pv") and lv > 0:
                var_name = f"{sn_std}{lv}"
            elif lv > 0 and str(lv) not in sn_std:
                var_name = f"{sn_std}{lv}"
            else:
                var_name = sn_std

            # Axe temps unifié pour ce bucket
            times_sorted = sorted(set(b["times"]))
            nt = len(times_sorted)
            time_idx = {t: i for i, t in enumerate(times_sorted)}

            ny, nx = len(lats), len(lons)
            arr_3d = np.full((nt, ny, nx), np.nan, dtype="float32")
            
            for t, a in zip(b["times"], b["arrays"]):
                arr_3d[time_idx[t]] = a

            da = xr.DataArray(
                dsa.from_array(arr_3d, chunks=(min(nt, self.chunk_time), ny, nx)),
                dims=("time", "latitude", "longitude"),
                coords={
                    "time":      np.array([t.value // 10**9 for t in times_sorted], dtype="float64"),
                    "latitude":  lats.astype("float64"),
                    "longitude": lons.astype("float64"),
                },
                name=var_name,
            )

            # Métadonnées
            da.attrs = {
                "units":      units,
                "long_name":  f"{desc} (lvl {lv})" if lv > 0 else desc,
                "level_type": ltype_std,
                "level":      float(lv),
                "shortname":  var_name,
            }
            # Encodage du temps
            da.coords["time"].attrs = {
                "units":         "seconds since 1970-01-01 00:00:00",
                "standard_name": "time",
                "long_name":     "Valid time",
                "axis":          "T",
            }
            viz = self.cfg.get_viz(sn_std)
            if viz:
                da.attrs["viz"] = json.dumps(viz)
            
            # Gestion des collisions de noms (rare mais possible)
            if var_name in data_vars:
                logger.warning(f"  ⚠ Collision de nom variable: {var_name} (ltype={ltype_std}, lv={lv})")
                var_name = f"{var_name}_{ltype_std}"
            
            data_vars[var_name] = da

        logger.info(f"  📂 GRIB (eccodes): {len(data_vars)} variables (flat levels)")

        # Merge en un seul Dataset
        ds_list = [da.to_dataset() for da in data_vars.values()]
        try:
            merged = xr.merge(ds_list, compat="override", join="outer")
        except Exception as e:
            logger.error(f"  ❌ Erreur merge GRIB: {e}")
            merged = ds_list[0] if ds_list else xr.Dataset()

        return merged

        logger.info(f"  📂 GRIB (eccodes): {len(data_vars)} variables")

        # Merge en un seul Dataset (compat=override pour différents niveaux)
        ds_list = []
        for sn, da in data_vars.items():
            ds_list.append(da.to_dataset())
        try:
            merged = xr.merge(ds_list, compat="override", join="outer")
        except Exception:
            merged = ds_list[0] if ds_list else xr.Dataset()

        return merged


class NetCDFReader:
    """Lecteur NetCDF lazy via xarray + Dask."""

    def __init__(self, cfg: ConfigLoader, chunk_time: int = 6):
        self.cfg        = cfg
        self.chunk_time = chunk_time

    def read_all(self, files: List[Path]) -> Optional[xr.Dataset]:
        str_files = [str(f) for f in files]
        try:
            if len(files) == 1:
                ds = xr.open_dataset(
                    str_files[0],
                    engine="netcdf4",
                    chunks={"time": self.chunk_time},
                )
            else:
                ds = xr.open_mfdataset(
                    str_files,
                    engine="netcdf4",
                    combine="by_coords",
                    parallel=True,
                    chunks={"time": self.chunk_time},
                )
            logger.info(f"  📂 NetCDF: {len(ds.data_vars)} variables, "
                        f"time={ds.dims.get('time', '?')}")
            return ds
        except Exception as e:
            logger.error(f"  ❌ Lecture NetCDF: {e}")
            return None


# CHAMPS DÉRIVÉS (lazy — construits dans le graph Dask)

class DerivedFieldsBuilder:
    """
    Ajoute les champs dérivés au Dataset de façon LAZY.
    Aucun calcul n'est déclenché ici : tout est enregistré dans le graph Dask.
    """

    def __init__(self, cfg: ConfigLoader):
        self.derived_defs = cfg.fa_defs.get("derived_fields", {})
        self.cfg          = cfg

    def build(self, ds: xr.Dataset) -> xr.Dataset:
        # 1. Dérivés déclarés dans fa_definitions.json (ws, wdir, ws10, gust...)
        ds = self._from_definitions(ds)
        # 2. Vent tous niveaux générique (u850, v850 → ws850; u20, v20 → ws20, etc.)
        ds = self._all_levels_wind(ds)
        return ds

    def _from_definitions(self, ds: xr.Dataset) -> xr.Dataset:
        for name, info in self.derived_defs.items():
            recipe  = info["recipe"]
            sn      = info["shortname"]
            sources = recipe["sources"]

            if not all(s in ds for s in sources):
                continue

            if recipe["type"] == "vector_magnitude":
                u = ds[sources[0]]
                v = ds[sources[1]]
                result = (u ** 2 + v ** 2) ** 0.5
            elif recipe["type"] == "vector_direction":
                u = ds[sources[0]]
                v = ds[sources[1]]
                result = (270.0 - xr.apply_ufunc(
                    np.degrees, xr.apply_ufunc(np.arctan2, v, u, dask="parallelized"),
                    dask="parallelized",
                )) % 360.0
            elif recipe["type"] == "accumulation":
                # Somme de plusieurs composantes (ex: tp = twatp_con + twatp_gec)
                result = sum(ds[s] for s in sources)
            else:
                continue

            result      = result.rename(sn)
            result.attrs.update({"units": info["unit"], "long_name": info["desc"], "shortname": sn})
            viz = self.cfg.get_viz(sn)
            if viz:
                result.attrs["viz"] = json.dumps(viz)
            ds[sn] = result

        return ds

    def _all_levels_wind(self, ds: xr.Dataset) -> xr.Dataset:
        """Génère ws{lev}, wdir{lev} pour tous les niveaux (isobarique, H, PV) où u/v sont présents."""
        for var in list(ds.data_vars):
            # Cherche u{lev}, ex: u850, u20, u0.5
            m = re.match(r"^u(\d+\.?\d*)$", var)
            if not m:
                continue
            lev  = m.group(1)
            u, v = f"u{lev}", f"v{lev}"
            if v not in ds:
                continue

            ws   = (ds[u] ** 2 + ds[v] ** 2) ** 0.5
            wdir = (270.0 - xr.apply_ufunc(
                np.degrees, xr.apply_ufunc(np.arctan2, ds[v], ds[u], dask="parallelized"),
                dask="parallelized",
            )) % 360.0

            ws_name, wd_name = f"ws{lev}", f"wdir{lev}"
            
            # Récupération niveau/type depuis u
            ltype = ds[u].attrs.get("level_type", "unknown")
            lunit = "hPa" if ltype == "isobaric" else "m" if ltype == "height" else "PVU"

            ws.attrs.update({"units": "m s-1",  "long_name": f"Wind Speed ({lev} {lunit})",
                             "level_type": ltype, "shortname": ws_name})
            wdir.attrs.update({"units": "degrees", "long_name": f"Wind Dir ({lev} {lunit})",
                               "level_type": ltype, "shortname": wd_name})

            for sn_, da_ in [(ws_name, ws), (wd_name, wdir)]:
                viz = self.cfg.get_viz(sn_)
                if viz:
                    da_.attrs["viz"] = json.dumps(viz)
            ds[ws_name] = ws
            ds[wd_name] = wdir

        return ds


# ═════════════════════════════════════════════════════════════════════════════
# CUMULS / DÉCUMULAGE  (chargement minimal : 1-2 variables seulement)
# ═════════════════════════════════════════════════════════════════════════════

class AccumulationProcessor:
    """
    Calcule les cumuls glissants (RR3h, RR6h, RR12h, RR24h, cumuls neige...).

    Stratégie mémoire :
      → On charge UNIQUEMENT la variable source (ex: "twatp") en RAM
      → np.diff vectorisé sur l'axe time (toutes les échéances d'un coup)
      → Le résultat est immédiatement converti en Dask array et ré-inséré
      → La variable source est libérée (del + gc)

    Coût RAM = nx × ny × n_timesteps × 4B × 2  (src + diff)
    Ex AROME: 400×400 × 48 × 4 × 2 ≈ 600 MB par variable source
    """

    def __init__(self, cfg: ConfigLoader):
        # Fusionne les définitions de cumuls FA et GRIB
        fa_accum   = cfg.fa_defs.get("accumulations", {})
        grib_accum = cfg.grib_defs.get("accumulations", {})
        # GRIB en priorité car les shortnames ont déjà été normalisés
        self.acc_defs = {**fa_accum, **grib_accum}
        self.cfg      = cfg

    def process(self, ds: xr.Dataset, dt_hours: float = 1.0) -> xr.Dataset:
        """
        Ajoute les variables de cumul au Dataset.
        Les variables sources sont chargées, traitées, puis libérées.
        """
        if not self.acc_defs:
            return ds

        new_vars: Dict[str, xr.DataArray] = {}

        for src_var, targets in self.acc_defs.items():
            if src_var not in ds:
                logger.debug(f"  Cumul: source '{src_var}' absente, skip")
                continue

            logger.info(f"  📈 Calcul cumuls depuis '{src_var}' "
                        f"→ {targets} (chargement {src_var} uniquement)")

            # ── Chargement minimal : uniquement cette variable ─────────────
            t0  = time.perf_counter()
            src = ds[src_var].load().values.astype(np.float32)  # (T, Y, X)
            logger.info(f"     '{src_var}' chargé en {time.perf_counter()-t0:.1f}s "
                        f"({src.nbytes/1e6:.0f} MB)")

            for tgt in targets:
                m = re.search(r"(\d+)", tgt)
                if not m:
                    continue
                hours    = int(m.group(1))
                steps    = max(1, round(hours / dt_hours))

                if steps >= src.shape[0]:
                    logger.warning(f"  ⚠  {tgt}: {steps} pas > {src.shape[0]} éch., skip")
                    continue

                # Identifiant interne unique (ex: tp_3h, tp_6h)
                # pour éviter les collisions si on a plusieurs cumuls pour la même source
                # Le nom final dans le Zarr sera "tp" dans le dossier surface_3h/
                tgt_id = f"{src_var}_{hours}h"

                # Décumulage vectorisé : RR_N(T) = Acc(T) - Acc(T - N)
                diff          = np.empty_like(src)
                diff[:steps]  = np.nan
                diff[steps:]  = np.maximum(src[steps:] - src[:-steps], 0.0)

                # Ré-encapsulation en Dask array
                diff_dask = da.from_array(diff, chunks=(6, -1, -1))
                da_tgt    = xr.DataArray(
                    diff_dask,
                    coords=ds[src_var].coords,
                    dims=ds[src_var].dims,
                    name=tgt_id,
                    attrs={
                        "units":      "kg m-2",
                        "long_name":  f"Précipitation cumulée sur {hours}h",
                        "shortname":  src_var,   # On garde le nom de base ici
                        "level_type": "surface",
                        "acc_hours":  hours,
                        "dt_hours":   dt_hours,
                    },
                )
                viz = self.cfg.get_viz(src_var)
                if viz:
                    da_tgt.attrs["viz"] = json.dumps(viz)

                new_vars[tgt_id] = da_tgt
                logger.info(f"     ✓ {tgt_id} calculé (attr acc_hours={hours})")

            # ── Libération mémoire ──────────────────────────────────────────
            del src
            gc.collect()

        if new_vars:
            ds = ds.assign(new_vars)

        return ds


# ═════════════════════════════════════════════════════════════════════════════
# PARTITION EN GROUPES ZARR  (zarr_groups.json)
# ═════════════════════════════════════════════════════════════════════════════

class ZarrGroupPartitioner:
    """
    Répartit les variables d'un Dataset dans les groupes Zarr
    définis par zarr_groups.json.
    """

    def __init__(self, cfg: ConfigLoader):
        self.groups_config = cfg.zarr_groups.get("groups", {})

    def partition(self, ds: xr.Dataset) -> Dict[str, xr.Dataset]:
        """
        Retourne un dict {group_name: xr.Dataset} selon zarr_groups.json.
        Les variables non matchées vont dans le groupe 'surface' par défaut.
        """
        assigned: Dict[str, List[str]] = {g: [] for g in self.groups_config}
        all_vars = set(ds.data_vars)

        for gname, gcfg in self.groups_config.items():
            match   = gcfg.get("match", {})
            exclude = set(match.get("exclude", []))

            # Match par durée (3h, 6h, etc.) - Priorité haute pour les groupes spécifiques
            ghours = None
            mg = re.search(r"(\d+)h", gname)
            if mg:
                ghours = int(mg.group(1))

            for vname in list(all_vars):
                if vname in exclude:
                    continue

                matched = False

                # 1. Match par durée cumulée (si le groupe est dédié à une durée)
                vhours = ds[vname].attrs.get("acc_hours")
                if ghours is not None and vhours == ghours:
                    matched = True

                # 2. Match par nom explicite
                if not matched and vname in match.get("parameters", []):
                    matched = True

                # 3. Match par level_type dans les attributs
                if not matched:
                    ltype = ds[vname].attrs.get("level_type", "")
                    if ltype in match.get("level_types", []):
                        # On évite que les cumuls (vhours != None) aillent dans 
                        # le groupe surface générique (ghours == None)
                        if vhours is None or ghours is not None:
                            matched = True

                # 4. Catch-all
                if not matched and match.get("all"):
                    matched = True

                if matched:
                    assigned[gname].append(vname)

        # Variables non assignées → groupe "surface" (ou premier groupe)
        assigned_all = {v for vs in assigned.values() for v in vs}
        unassigned   = all_vars - assigned_all

        if unassigned:
            fallback = "others" if "others" in assigned else "surface" if "surface" in assigned else next(iter(assigned), None)
            if fallback:
                assigned[fallback].extend(list(unassigned))
                logger.info(f"  ⚠ {len(unassigned)} var. non matchées → groupe '{fallback}'")

        # Construction des sous-datasets
        result: Dict[str, xr.Dataset] = {}
        for gname, vars_ in assigned.items():
            if not vars_:
                continue
                
            gds = ds[vars_]
            
            # Renommage des accumulations pour garder le nom original
            # ex: tp_3h -> tp dans le groupe surface_3h
            mg = re.search(r"(\d+)h", gname)
            if mg:
                hours = int(mg.group(1))
                rename_map = {}
                for v in gds.data_vars:
                    if gds[v].attrs.get("acc_hours") == hours:
                        rename_map[v] = gds[v].attrs.get("shortname", v)
                if rename_map:
                    gds = gds.rename(rename_map)
                    logger.info(f"   ✓ Renommage {gname}: {list(rename_map.keys())} → {list(rename_map.values())}")

            # Slicing temporel pour les groupes à durée (ex: 3h commence à H03)
            # On suppose un pas de temps dt_hours (attribut présent dans les DataArrays de cumul)
            if mg:
                hours = int(mg.group(1))
                # On cherche le max dt_hours parmi les variables du groupe (souvent 1.0)
                dts = [gds[v].attrs.get("dt_hours", 1.0) for v in gds.data_vars if "dt_hours" in gds[v].attrs]
                dt = dts[0] if dts else 1.0
                steps = round(hours / dt)
                
                if steps < gds.sizes["time"]:
                    gds = gds.isel(time=slice(steps, None))
                    logger.info(f"   ✓ Troncature {gname}: commence à l'indice {steps} (H{hours})")
                else:
                    logger.warning(f"   ⚠ Troncature {gname} impossible: {steps} pas >= {gds.sizes['time']} éch.")
            
            result[gname] = gds
            logger.info(f"   ✓ Groupe '{gname}': {len(gds.data_vars)} variables")

        return result


# ═════════════════════════════════════════════════════════════════════════════
# ÉCRITURE ZARR (streaming Dask)
# ═════════════════════════════════════════════════════════════════════════════

class ZarrWriter:
    """
    Écrit chaque groupe en Zarr de façon streaming (Dask compute au vol).
    - Chunking optimisé TiTiler/MapLibre : time=-1, spatial 256×256
    - Écriture atomique (tmp → rename)
    - Option pyramide multiscale
    """

    CHUNK_SPATIAL = 256   # pixels, tuile WebGL standard

    def __init__(self, use_pyramids: bool = False, n_threads: int = 4):
        self.use_pyramids = use_pyramids
        self.n_threads    = n_threads

    def write_all(self, group_datasets: Dict[str, xr.Dataset], run_dir: Path):
        """Écrit tous les groupes en parallèle (ThreadPool)."""
        t0 = time.perf_counter()
        errors = []
        with ThreadPoolExecutor(max_workers=self.n_threads) as pool:
            futs = {
                pool.submit(self._write_group, gname, gds, run_dir): gname
                for gname, gds in group_datasets.items()
            }
            for fut in as_completed(futs):
                gname = futs[fut]
                try:
                    fut.result()
                except Exception as e:
                    logger.error(f"  ❌ Écriture '{gname}': {e}")
                    errors.append(f"{gname}: {e}")

        if errors:
            raise RuntimeError(f"Échec de {len(errors)} groupes Zarr: {', '.join(errors)}")

        logger.info(f"  ✅ Écriture Zarr terminée en {time.perf_counter()-t0:.1f}s")

    def _write_group(self, group_name: str, ds: xr.Dataset, run_dir: Path):
        """Écrit un groupe Zarr unique."""
        ds  = self._harmonize_coords(ds)
        ds  = self._clean(ds)
        ds  = self._clean_time(ds)
        ds  = self._rechunk(ds)

        if HAS_RIO:
            try:
                ds = ds.rio.write_crs("EPSG:4326")
            except Exception:
                pass

        enc = self._encoding(ds)

        output_path = run_dir / f"{group_name}.zarr"
        tmp_path    = output_path.with_suffix(".zarr.tmp")
        if tmp_path.exists():
            shutil.rmtree(tmp_path)

        if self.use_pyramids and HAS_PYRAMID:
            self._write_pyramid(ds, enc, tmp_path)
        else:
            # Écriture Dask streaming : Dask calcule par chunks et écrit
            ds.to_zarr(
                str(tmp_path),
                mode="w",
                encoding=enc,
                consolidated=True,
                compute=True,
                zarr_format=2,  # Force v2 pour compatibilité TiTiler et éviter bugs Zarr v3
            )

        if output_path.exists():
            shutil.rmtree(output_path)
        tmp_path.rename(output_path)

        # Stats
        size_mb = sum(f.stat().st_size for f in output_path.rglob("*") if f.is_file()) / 1e6
        n_vars  = len(ds.data_vars)
        n_time  = ds.dims.get("time", "?")
        logger.info(f"  ✓ '{group_name}': {n_vars} vars × {n_time} éch. → {size_mb:.1f} MB")

    def _write_pyramid(self, ds: xr.Dataset, enc: dict, path: Path):
        """Génère les niveaux de zoom 1× 2× 4× 8× pour TiTiler multiscale."""
        if not HAS_PYRAMID:
            raise RuntimeError("ndpyramid non installé")
        pyr = pyramid_coarsen(ds, factors=[2, 4, 8], dims=["latitude", "longitude"])
        pyr.to_zarr(str(path), mode="w", consolidated=True)

    def _rechunk(self, ds: xr.Dataset) -> xr.Dataset:
        """
        Chunking optimal pour visualisation web :
          - time = toute la timeline (accès timeline MapLibre = 1 lecture)
          - spatial = 256×256 (tuile TiTiler = 1 lecture)
        """
        ny = ds.dims.get("latitude",  ds.dims.get("lat", 256))
        nx = ds.dims.get("longitude", ds.dims.get("lon", 256))
        nt = ds.dims.get("time", 1)

        cy = min(self.CHUNK_SPATIAL, ny)
        cx = min(self.CHUNK_SPATIAL, nx)

        return ds.chunk({"time": nt, "latitude": cy, "longitude": cx})

    @staticmethod
    def _clean(ds: xr.Dataset) -> xr.Dataset:
        """Nettoyage encodage et valeurs aberrantes."""
        for v in ds.data_vars:
            ds[v].encoding = {}
            if ds[v].dtype.kind == "f":
                ds[v] = ds[v].where(ds[v] < 1e30)
        return ds

    @staticmethod
    def _clean_time(ds: xr.Dataset) -> xr.Dataset:
        """Force un temps propre sans pollution cfgrib/CF en le reconstruisant à partir de zéro."""
        if "time" in ds.coords:
            try:
                import pandas as pd
                # 1. On extrait les valeurs brutes et on les convertit en datetime64[ns] propre
                # Si GRIB decode_times=False, on a des int. Si decode_times=True, on a des datetime.
                # pd.to_datetime gère les deux si on l'aide un peu.
                raw_vals = ds.time.values
                if raw_vals.dtype.kind in ('i', 'f'):
                    # Cas numérique (decode_times=False) : on suppose que c'est des heures (GRIB standard)
                    # ou on tente de lire l'unité pour être sûr.
                    # Mais le plus simple pour GRIB arpege/arome est d'utiliser le valid_time si présent
                    # Sinon on fait au mieux.
                    clean_times = pd.to_datetime(raw_vals, unit='h', origin='1970-01-01')
                else:
                    clean_times = pd.to_datetime(raw_vals)
                
                # 2. On remplace la coordonnée par une version "float hours since ref"
                # C'est le format le plus stable pour Zarr/NetCDF
                ref = pd.Timestamp("1970-01-01")
                hours_since = (clean_times - ref).total_seconds() / 3600.0
                
                # On réassigne comme vecteur float64
                ds = ds.assign_coords(time=np.array(hours_since, dtype='float64'))
                
                # 3. On WIPE tout l'encodage et les attrs pour repartir sur du propre
                ds.time.encoding = {
                    "units": "hours since 1970-01-01 00:00:00",
                    "calendar": "proleptic_gregorian",
                    "dtype": "float64"
                }
                ds.time.attrs = {
                    "units": "hours since 1970-01-01 00:00:00",
                    "standard_name": "time",
                    "long_name": "time",
                    "axis": "T"
                }
            except Exception as e:
                logger.debug(f"  ⚠ Impossible de nettoyer le temps: {e}")
        return ds

    @staticmethod
    def _harmonize_coords(ds: xr.Dataset) -> xr.Dataset:
        """Normalise les noms de coordonnées → latitude/longitude."""
        rn = {}
        for alt, std in [("lon", "longitude"), ("x", "longitude"),
                         ("lat", "latitude"),  ("y", "latitude")]:
            if alt in ds.coords and std not in ds.coords:
                rn[alt] = std
        if rn:
            ds = ds.rename(rn)
        return ds

    @staticmethod
    def _encoding(ds: xr.Dataset) -> dict:
        enc = {}
        for v in ds.data_vars:
            enc[v] = {"compressor": COMPRESSOR, "dtype": "float32"}
        # Le temps est déjà géré par _clean_time via ds.time.encoding
        return enc


# ═════════════════════════════════════════════════════════════════════════════
# CONVERTISSEUR PRINCIPAL
# ═════════════════════════════════════════════════════════════════════════════

class NWPConverter:
    """
    Point d'entrée unique pour la conversion NWP → Zarr.

    Formats supportés : FA, LFA, GRIB1, GRIB2, NetCDF
    Tables utilisées  : fa_definitions.json, zarr_groups.json, colormap_config.json

    Pipeline complet :
      Lecture lazy → Normalisation → Dérivés lazy → Cumuls (RAM min.) →
      Partition groupes → Écriture Zarr streaming
    """

    def __init__(
        self,
        output_dir:    str,
        config_dir:    Optional[str] = None,
        use_pyramids:  bool          = False,
        dask_workers:  int           = 4,
        dask_threads:  int           = 2,
        chunk_time:    int           = 6,
        write_threads: int           = 4,
        read_threads:  int           = 16,
        dashboard_address: str       = ":8787",
    ):
        self.output_dir    = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.use_pyramids  = use_pyramids
        self.dask_workers  = dask_workers
        self.dask_threads  = dask_threads
        self.chunk_time    = chunk_time
        self.write_threads = write_threads
        self.read_threads  = read_threads
        self.dashboard_address = dashboard_address

        # Chargement des tables
        self.cfg = ConfigLoader(config_dir)

        # Composants du pipeline
        self.derived_builder = DerivedFieldsBuilder(self.cfg)
        self.acc_processor   = AccumulationProcessor(self.cfg)
        self.partitioner     = ZarrGroupPartitioner(self.cfg)
        self.writer          = ZarrWriter(use_pyramids, write_threads)

        # Lecteurs
        self.fa_reader  = FAReader(self.cfg)
        self.grib_reader = GRIBReader(self.cfg, chunk_time)
        self.nc_reader   = NetCDFReader(self.cfg, chunk_time)

    # ── API publique ──────────────────────────────────────────────────────────

    def convert(
        self,
        input_dir:  str,
        model:      str,
        run_date:   datetime,
        fmt:        Optional[str] = None,
        dt_hours:   float         = 1.0,
    ) -> bool:
        """
        Convertit un run complet en Zarr.

        Args:
            input_dir : dossier des fichiers du run
            model     : nom du modèle ('arome', 'aladin', ...)
            run_date  : datetime du run
            fmt       : forcer format ('fa', 'grib', 'grib1', 'grib2', 'netcdf')
            dt_hours  : pas de temps en heures (pour le décumulage)
        """
        t_start  = time.perf_counter()
        src      = Path(input_dir)
        run_dir  = self._get_run_dir(model, run_date)

        if not src.exists():
            logger.error(f"❌ Dossier introuvable: {src}")
            return False

        files = sorted(f for f in src.iterdir()
                       if not f.is_dir() and not f.name.startswith("."))
        if not files:
            logger.warning(f"⚠  Aucun fichier dans {src}")
            return False

        logger.info(f"\n{'='*65}")
        logger.info(f"🚀 {model.upper()}  run {run_date:%Y%m%d %HZ}  —  {len(files)} fichiers")
        logger.info(f"   Dask: {self.dask_workers}w×{self.dask_threads}t  "
                    f"| chunk_time={self.chunk_time}  | write_threads={self.write_threads}")
        logger.info(f"{'='*65}")

        # Démarrage cluster Dask local
        with LocalCluster(
            n_workers=self.dask_workers,
            threads_per_worker=self.dask_threads,
            memory_limit="auto",
            dashboard_address=self.dashboard_address,
        ) as cluster, Client(cluster) as client:

            logger.info(f" Dask dashboard: {client.dashboard_link}")

            # ── Phase 1 : Lecture lazy ────────────────────────────────────
            t1 = time.perf_counter()
            ds = self._read(files, fmt)
            if ds is None:
                logger.error("❌ Aucune donnée lue")
                return False
            logger.info(
                f"  Phase 1 (lecture) : {time.perf_counter()-t1:.1f}s  "
                f"— time={ds.dims.get('time','?')} "
                f"lat={ds.dims.get('latitude','?')} "
                f"lon={ds.dims.get('longitude','?')} "
                f"vars={len(ds.data_vars)}"
            )

            # ── Phase 2 : Dérivés lazy (graph Dask, 0 RAM) ───────────────
            t2 = time.perf_counter()
            ds = self.derived_builder.build(ds)
            logger.info(f"  Phase 2 (dérivés) : {time.perf_counter()-t2:.1f}s "
                        f"— {len(ds.data_vars)} vars total")

            # ── Phase 3 : Cumuls (chargement minimal) ────────────────────
            t3 = time.perf_counter()
            ds = self.acc_processor.process(ds, dt_hours)
            logger.info(f"  Phase 3 (cumuls)  : {time.perf_counter()-t3:.1f}s "
                        f"— {len(ds.data_vars)} vars total")

            # ── Phase 4 : Partition groupes Zarr ─────────────────────────
            t4 = time.perf_counter()
            groups = self.partitioner.partition(ds)
            logger.info(
                f"  Phase 4 (groupes) : {time.perf_counter()-t4:.1f}s "
                f"— {len(groups)} groupes: {list(groups.keys())}"
            )

            # ── Phase 5 : Écriture Zarr streaming ────────────────────────
            t5 = time.perf_counter()
            self.writer.write_all(groups, run_dir)
            logger.info(f"  Phase 5 (écriture): {time.perf_counter()-t5:.1f}s")

        elapsed = time.perf_counter() - t_start
        logger.info(f"\n✅ {model.upper()} {run_date:%Y%m%d%H} — terminé en {elapsed:.1f}s → {run_dir}")
        return True

    # ── Lecture selon format ──────────────────────────────────────────────────

    def _read(self, files: List[Path], fmt: Optional[str]) -> Optional[xr.Dataset]:
        detected = fmt or self._detect_format(files)
        logger.info(f"  Format détecté : {detected}")

        if detected in ("fa", "lfa"):
            return self.fa_reader.read_all(files, n_threads=self.read_threads)
        elif detected in ("grib", "grib1", "grib2"):
            return self.grib_reader.read_all(files)
        elif detected in ("netcdf", "nc"):
            return self.nc_reader.read_all(files)
        else:
            logger.error(f"  Format inconnu : {detected}")
            return None

    @staticmethod
    def _detect_format(files: List[Path]) -> str:
        """Détecte le format depuis les noms/extensions des fichiers."""
        if not files:
            return "unknown"
        sample = files[0]
        name   = sample.name.lower()
        ext    = sample.suffix.lower()

        if ext == ".lfa":                          return "lfa"
        if ext == ".fa" or "fullpos" in name:     return "fa"
        if ext in (".grib", ".grb", ".grb1"):     return "grib1"
        if ext in (".grib2", ".grb2"):            return "grib2"
        if ext in (".nc", ".nc4", ".netcdf"):     return "netcdf"

        # Heuristique sur le contenu du nom
        if any(x in name for x in ("fullpos", "hpos", "arome", "aladin")):
            return "fa"
        if any(x in name for x in ("grib", "grb")):
            return "grib2"
        return "unknown"

    def _get_run_dir(self, model: str, run_date: datetime) -> Path:
        d = self.output_dir / model / run_date.strftime("%Y%m%d%H")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def cleanup_old_runs(self, days: int = 5):
        cutoff = datetime.now() - timedelta(days=days)
        for model_dir in self.output_dir.iterdir():
            if not model_dir.is_dir():
                continue
            for run_dir in model_dir.iterdir():
                if not run_dir.is_dir():
                    continue
                try:
                    rd = datetime.strptime(run_dir.name, "%Y%m%d%H")
                    if rd < cutoff:
                        logger.info(f"🗑  Suppression: {run_dir}")
                        shutil.rmtree(run_dir)
                except Exception:
                    continue


# ENTRY POINT CLI

def main():
    parser = argparse.ArgumentParser(
        description="NWP → Zarr  |  Dask Lazy Streaming  (FA / GRIB1 / GRIB2 / NetCDF)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--input",          required=True,    help="Dossier des fichiers du run")
    parser.add_argument("--model",          required=True,    help="Nom du modèle")
    parser.add_argument("--run",            required=True,    help="Date run YYYYMMDDHH")
    parser.add_argument("--output",         default="/scratch/zarr")
    parser.add_argument("--config",         default=None,     help="Dossier des configs JSON")
    parser.add_argument("--fmt",            default=None,
                        choices=["fa", "lfa", "grib", "grib1", "grib2", "netcdf"])
    parser.add_argument("--dt-hours",       type=float, default=1.0,
                        help="Pas de temps en heures (pour le décumulage)")
    parser.add_argument("--dask-workers",   type=int,   default=4,
                        help="Nombre de workers Dask")
    parser.add_argument("--dask-threads",   type=int,   default=2,
                        help="Threads par worker Dask")
    parser.add_argument("--chunk-time",     type=int,   default=6,
                        help="Taille des chunks Dask sur la dimension time")
    parser.add_argument("--write-threads",  type=int,   default=4,
                        help="Threads pour l'écriture Zarr parallèle")
    parser.add_argument("--read-threads",   type=int,   default=16,
                        help="Threads pour la lecture FA parallèle")
    parser.add_argument("--pyramids",       action="store_true",
                        help="Activer les pyramides multiscale (ndpyramid)")
    parser.add_argument("--dashboard-address", default=":8787",
                        help="Adresse du dashboard Dask (ex: :8787 ou 0.0.0.0:3112)")
    parser.add_argument("--cleanup",        type=int,   default=None, metavar="DAYS",
                        help="Supprimer les runs de plus de N jours")

    args = parser.parse_args()

    converter = NWPConverter(
        output_dir    = args.output,
        config_dir    = args.config,
        use_pyramids  = args.pyramids,
        dask_workers  = args.dask_workers,
        dask_threads  = args.dask_threads,
        chunk_time    = args.chunk_time,
        write_threads = args.write_threads,
        read_threads  = args.read_threads,
        dashboard_address = args.dashboard_address,
    )

    if args.cleanup is not None:
        converter.cleanup_old_runs(args.cleanup)
        return

    try:
        run_date = datetime.strptime(args.run, "%Y%m%d%H")
    except ValueError:
        logger.error(f"❌ Format date invalide: {args.run} (attendu YYYYMMDDHH)")
        sys.exit(1)

    ok = converter.convert(
        input_dir = args.input,
        model     = args.model,
        run_date  = run_date,
        fmt       = args.fmt,
        dt_hours  = args.dt_hours,
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
