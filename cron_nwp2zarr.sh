#!/bin/bash
# Auto-généré par slurm_launcher.py
# Cron : 5 * * * * /chemin/vers/cron_nwp2zarr.sh >> /var/log/nwp2zarr.log 2>&1

MODELS='arome'
RUNS='2026030100'
INPUT_BASE='/fennecData/data/chprod/AROME/FULLPOS/2026/03/01/r00'
OUTPUT_DIR='zarr'
LAUNCHER='/fennecData/home/pnt/metview/Prod/scr2/slurm_launcher.py'
LOCK_DIR='/tmp/nwp2zarr_locks'
mkdir -p "$LOCK_DIR"

CURRENT_HOUR=$(date -u +%-H)
CURRENT_DATE=$(date -u +%Y%m%d)

for RUN_HOUR in $RUNS; do
    if [ "$CURRENT_HOUR" -eq "$RUN_HOUR" ]; then
        RUN_ID="${CURRENT_DATE}$(printf '%02d' $RUN_HOUR)"
        LOCK="$LOCK_DIR/$RUN_ID.lock"
        [ -f "$LOCK" ] && continue

        echo "$(date) [$RUN_ID] Soumission jobs..."
        conda activate "chikhiw" 2>/dev/null || true
        python3 "$LAUNCHER" multi_job \
            --models "$MODELS" \
            --run "$RUN_ID" \
            --input-base "$INPUT_BASE" \
            --output "$OUTPUT_DIR" \
            --conda-env "chikhiw"

        touch "$LOCK"
        find "$LOCK_DIR" -name "*.lock" -mtime +2 -delete
        echo "$(date) [$RUN_ID] Jobs soumis."
    fi
done
