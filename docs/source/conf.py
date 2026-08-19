"""Configuration file for Sphinx documentation (ReadTheDocs)."""

import os
import sys

sys.path.insert(0, os.path.abspath("../../src"))

project = "meteo2zarr"
copyright = "2026, Walid Chikhi, Meteo-Algeria"
author = "Walid Chikhi"
release = "1.0.1"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "myst_parser",
]

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

master_doc = "index"
root_doc = "index"

html_theme = "sphinx_rtd_theme"
html_theme_options = {
    "navigation_depth": 4,
    "collapse_navigation": False,
    "sticky_navigation": True,
    "includehidden": True,
    "titles_only": False,
}

html_static_path = ["_static"]
html_css_files = [
    "css/custom.css",
]

autodoc_member_order = "bysource"
autodoc_typehints = "description"
