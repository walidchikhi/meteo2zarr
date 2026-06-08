#!/bin/bash

source ~/miniconda3/bin/activate
conda activate nour

rm nwp2zarr_a*.err
rm nwp2zarr_a*.out

export AA=$(date +%Y)
export MM=$(date +%m)
export DD=$(date +%d)

#AROME 
python3 slurm_launcher.py single_job --model arome --run ${AA}${MM}${DD}00 --input /fennecData/home/pnt/output/AROME/cy46/pre_oper/GRIB/${DD}${MM}${AA}  --output zarr/arome25km --fmt grib2  --conda-env nour
python3 slurm_launcher.py single_job --model arome --run ${AA}${MM}${DD}00 --input /fennecData/data/chprod/AROME/FULLPOS/${AA}/${MM}/${DD}/r00 --output zarr/arome3km --fmt fa  --conda-env nour


#ALADIN
python3 slurm_launcher.py single_job --model aladin --run ${AA}${MM}${DD}00 --input /fennecData/home/pnt/output/ALADIN/cy46/pre_oper/GRIB/${DD}${MM}${AA}  --output zarr/aladin_5km --fmt grib2  --conda-env nour
python3 slurm_launcher.py single_job --model aladin --run ${AA}${MM}${DD}00 --input /fennecData/data/chprod/ALADIN/FULLPOS/${AA}/${MM}/${DD}/r00  --output zarr/aladin_8km --fmt fa  --conda-env nour


#ARPEGE
python3 slurm_launcher.py single_job --model arpege  --run ${AA}${MM}${DD}00 --input /fennecData/home/pnt/metview/ARPEGE/get_ARPEGE/${DD}${MM}${AA} --output zarr/arpege01 --fmt grib2  --conda-env nour
python3 slurm_launcher.py single_job --model arpege  --run ${AA}${MM}${DD}00 --input /fennecData/home/pnt/metview/ARPEGE/get_ARPEGE05/${DD}${MM}${AA} --output zarr/arpege05 --fmt grib2  --conda-env nour
