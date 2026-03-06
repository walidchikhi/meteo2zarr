# Usage Guide

The system uses a two-tier execution model:
1.  **`slurm_launcher.py`**: A CLI tool to submit jobs to the HPC cluster.
2.  **`core_hpc.py`**: The internal engine that performs the actual conversion.

## 1. Submitting a Single Job

To convert a single run for a specific model (e.g., AROME):

```bash
python slurm_launcher.py single_job \
    --model arome \
    --run 2026030100 \
    --input /path/to/AROME/FULLPOS/2026/03/01/r00 \
    --output ./zarr/ \
    --venv ./venv_zarr/
```

### Key Arguments:
- `--model`: `arome`, `aladin`, `arpege`, or `gfs`.
- `--run`: The timestamp in `YYYYMMDDHH` format.
- `--input`: Path to the directory containing FA files.
- `--output`: Root directory for Zarr stores.
- `--venv` (or `--conda-env`): Path to the python environment.

## 2. Using Job Arrays (Multi-job)

To convert multiple models in parallel for the same run:

```bash
python slurm_launcher.py multi_job \
    --models arome,aladin \
    --run 2026030100 \
    --input-base /path/to/data/chprod \
    --output ./zarr/ \
    --venv ./venv_zarr/
```

This submissions a **Slurm Job Array**, where each task handles one model independently.

## 3. Automation with Cron

You can generate an executable shell script that can be added to your `crontab`:

```bash
python slurm_launcher.py cron \
    --models arome,aladin \
    --runs-per-day 0 6 12 18 \
    --input-base /path/to/data/chprod \
    --output ./zarr/ \
    --venv ./venv_zarr/
```

This creates `cron_nwp2zarr.sh`. You can then add it to your crontab:
```bash
5 * * * * /path/to/scr2/cron_nwp2zarr.sh >> /var/log/nwp2zarr.log 2>&1
```

## 4. Monitoring Progress

### Slurm Status
```bash
python slurm_launcher.py status --jobid <JOB_ID>
# or standard slurm commands
squeue -u $USER
```

### Dask Dashboard
Each job starts a Dask dashboard. You can access it via the address/port printed in the `.err` log:
- **Default**: `http://<compute-node-ip>:3112`
- **Arguments**: `--dashboard-port 3112 --dashboard-address 0.0.0.0`
