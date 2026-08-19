"""Example: Submitting meteo2zarr batch jobs on Slurm HPC clusters."""

import os
import subprocess
from pathlib import Path
from meteo2zarr.config import ConfigLoader

# This script demonstrates how to invoke meteo2zarr in Slurm sbatch environments
SBATCH_TEMPLATE = """#!/bin/bash
#SBATCH --job-name=meteo2zarr_{model}_{run}
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task={cpus}
#SBATCH --mem={mem}
#SBATCH --time={time_limit}
#SBATCH --partition={partition}
#SBATCH --output=meteo2zarr_{model}_{run}.out
#SBATCH --error=meteo2zarr_{model}_{run}.err

source ~/miniconda3/bin/activate
conda activate meteo

meteo2zarr convert \\
    --model {model} \\
    --run {run} \\
    --input {input_dir} \\
    --output {output_dir} \\
    --dask-workers {workers} \\
    --dask-threads {threads} \\
    --chunk-time {chunk_time}
"""

def submit_slurm_job(model: str, run: str, input_dir: str, output_dir: str):
    script_content = SBATCH_TEMPLATE.format(
        model=model,
        run=run,
        input_dir=input_dir,
        output_dir=output_dir,
        cpus=32,
        mem="32G",
        time_limit="00:30:00",
        partition="Models",
        workers=8,
        threads=4,
        chunk_time=6,
    )
    script_path = f"job_{model}_{run}.sbatch"
    with open(script_path, "w") as f:
        f.write(script_content)
    
    print(f"Generated Slurm job script: {script_path}")
    # subprocess.run(["sbatch", script_path], check=True)

if __name__ == "__main__":
    submit_slurm_job("arome", "2026030100", "/data/nwp/arome", "./zarr_out")
