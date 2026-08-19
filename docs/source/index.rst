.. meteo2zarr documentation master file

Welcome to meteo2zarr's documentation!
======================================

**meteo2zarr** is a high-performance Python package and CLI utility designed for meteorological services and research centers. It converts raw Numerical Weather Prediction (NWP) model outputs (FA, LFA, GRIB1, GRIB2) into cloud-optimized, multidimensional `Zarr` stores with distributed Dask computing, Blosc compression, instant spatial-temporal inspection, and publication-ready cartographic visualization.

.. toctree::
   :maxdepth: 2
   :caption: User Guide

   installation
   quickstart
   conversion
   inspection
   reading
   plotting
   configuration

.. toctree::
   :maxdepth: 2
   :caption: API Reference

   api

.. toctree::
   :maxdepth: 1
   :caption: Architecture & Performance

   architecture
   faq
