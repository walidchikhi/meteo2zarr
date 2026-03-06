# FAQ

## Common Issues

### 1. `ModuleNotFoundError: No module named 'epygram'`
This usually happens when the job starts on a compute node and the virtual environment is not correctly configured or is missing dependencies. 
- **Solution**: Ensure you are using a shared virtual environment (like `venv_zarr`) and check the `slurm_launcher.py` output for "Environment check passed".

### 2. `MemoryError` or Job killed by OOM
Converting large datasets requires significant RAM.
- **Solution**: Increase `--mem` in the `slurm_launcher.py` call or adjust the `MODEL_PROFILES` in the launcher script. Reducing `--read-threads` can also help.

### 3. Zarr output contains only `NaN`s
This often happens if the `dt_hours` (time step) is incorrect.
- **Solution**: Check the `--dt-hours` argument. If your FA files are spaced by 3 hours, use `--dt-hours 3.0`.

### 4. How to add a new variable?
1. Open `fa_definitions.json`.
2. Add the FA field name to the `fields` section.
3. Define its `shortname` and `formula`.
4. Run a new conversion job.

## Troubleshooting Slurm

- **Check logs**: Logs are stored in `zarr/<model>/<run>/logs/`.
- **Examine scripts**: Generated sbatch scripts are in `zarr/<model>/<run>/sbatch_scripts/`. You can try running these scripts manually via `sbatch <script_name>` for debugging.
