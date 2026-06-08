#!/bin/bash



export AA=$(date +%Y)
export MM=$(date +%m)
export DD=$(date +%d)

DAY="${AA}${MM}${DD}00"

REMOTE_USER="nkerroumi-dev"
REMOTE_HOST="10.16.10.22"
#REMOTE_BASE="/home/nkerroumi-dev/zarr"
REMOTE_BASE="/data/zarr"
BASE="/fennecData/home/pnt/metview/Prod/scr2/zarr"

# =========================================================
# MODELS + SUBFOLDERS
# =========================================================

declare -A PATHS

PATHS["aladin_5km"]="aladin"
PATHS["aladin_8km"]="aladin"
PATHS["arome25km"]="arome"
PATHS["arome3km"]="arome"
PATHS["arpege01"]="arpege"
PATHS["arpege05"]="arpege"

# =========================================================

echo "========================================="
echo "Starting transfer for cycle: $DAY"
echo "========================================="

for MODEL in "${!PATHS[@]}"; do

    SUBDIR=${PATHS[$MODEL]}

    SRC="${BASE}/${MODEL}/${SUBDIR}/${DAY}"

    DEST="${REMOTE_BASE}/${MODEL}/${DAY}"

    echo ""
    echo "-----------------------------------------"
    echo "MODEL : $MODEL"
    echo "SOURCE: $SRC"
    echo "DEST  : ${REMOTE_USER}@${REMOTE_HOST}:${DEST}"
    echo "-----------------------------------------"

    if [ -d "$SRC" ]; then

        # Create remote directory
        ssh ${REMOTE_USER}@${REMOTE_HOST} \
            "mkdir -p ${DEST}"

        # Transfer
        rsync -avh --progress \
              --partial \
              --inplace \
              "${SRC}/" \
              "${REMOTE_USER}@${REMOTE_HOST}:${DEST}/"

        echo "Transfer completed for $MODEL"

    else
        echo "WARNING: Missing directory:"
        echo "$SRC"
    fi

done

echo ""
echo "========================================="
echo "All transfers completed"
echo "========================================="
