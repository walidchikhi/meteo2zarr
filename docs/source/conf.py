"""Configuration file for the Sphinx documentation builder (ReadTheDocs)."""

import os
import sys

sys.path.insert(0, os.path.abspath("../../src"))

# Project information
project = "meteo2zarr"
copyright = "2026, Walid Chikhi, Meteo-Algeria"
author = "Walid Chikhi"
release = "0.1.0"

# Extensions
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
        "myst_parser",
]

# Source suffix
source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

# Master doc
master_doc = "index"

# HTML Theme
html_theme = "sphinx_rtd_theme"
html_theme_options = {
    "navigation_depth": 4,
    "collapse_navigation": False,
    "sticky_navigation": True,
    "includehidden": True,
    "titles_only": False,
}

# Autodoc configuration
autodoc_member_order = "bysource"
autodoc_typehints = "description"

# Intersphinx mapping
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "xarray": ("https://docs.xarray.dev/en/stable/", None),
    "zarr": ("https://zarr.readthedocs.io/en/stable/", None),
    "dask": ("https://docs.dask.org/en/stable/", None),
}
