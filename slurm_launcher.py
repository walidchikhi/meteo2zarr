#!/usr/bin/env python3
"""
slurm_launcher.py — Lanceur SLURM pour la conversion NWP → Zarr
================================================================

Activation d'environnement virtuel (choisir UNE option) :

  --venv  /path/to/venv          Python venv  (source venv/bin/activate)
  --conda-env  my_env            Conda env    (conda activate my_env)
  --modules  python/3.11 hdf5    HPC modules  (module load ...)

  Ces options sont cumulables : ex. modules + venv

Usage :

  # venv Python standard
  python slurm_launcher.py single_job \\
      --model arome --run 2026030100 \\
      --input /fennecData/data/chprod/AROME/FULLPOS/2026/03/01/r00 \\
      --output ./zarr/ \\
      --venv /home/user/envs/nwp_env

  # Conda
  python slurm_launcher.py single_job \\
      --model arome --run 2026030100 \\
      --input /fennecData/data/chprod/AROME/FULLPOS/2026/03/01/r00 \\
      --output ./zarr/ \\
      --conda-env nwp_env

  # Modules HPC + venv
  python slurm_launcher.py single_job \\
      --model arome --run 2026030100 \\
      --input /fennecData/data/chprod/AROME/FULLPOS/2026/03/01/r00 \\
      --output ./zarr/ \\
      --modules python/3.11 hdf5/1.14 eccodes/2.31 \\
      --venv /scratch/user/nwp_env

  # Plusieurs modèles en parallèle (job array)
  python slurm_launcher.py multi_job \\
      --models arome,aladin \\
      --run 2026030100 \\
      --input-base /fennecData/data/chprod \\
      --output ./zarr/ \\
      --venv /home/user/envs/nwp_env

  # Statut d'un job
  python slurm_launcher.py status --jobid 12345

  # Générer un script cron
  python slurm_launcher.py cron \\
      --models arome,aladin \\
      --runs-per-day 0 6 12 18 \\
      --input-base /fennecData/data/chprod \\
      --output ./zarr/ \\
      --venv /home/user/envs/nwp_env
"""

import os
import sys
import time
import logging
import argparse
import subprocess
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("slurm_launcher")

# ----─
# PROFILS HPC  —  adapter selon votre cluster
# ----─

MODEL_PROFILES: Dict[str, dict] = {
    "arome": {
        "cpus_per_task": 32, "mem_gb": 32,  "time": "00:30:00",
        "partition": "Models", "read_threads": 16, "write_threads": 8,
    },
    "aladin": {
        "cpus_per_task": 32, "mem_gb": 32,  "time": "00:10:00",
        "partition": "Models", "read_threads": 16, "write_threads": 8,
    },
    "arpege": {
        "cpus_per_task": 48, "mem_gb": 32, "time": "00:20:00",
        "partition": "Models",  "read_threads": 24, "write_threads": 8,
    },
    "gfs": {
        "cpus_per_task": 32, "mem_gb": 32,  "time": "00:20:00",
        "partition": "Models",  "read_threads": 16, "write_threads": 8,
    },
    "default": {
        "cpus_per_task": 16, "mem_gb": 32,  "time": "00:15:00",
        "partition": "Models", "read_threads": 8,  "write_threads": 4,
    },
}

# Chemins relatifs au script courant
SCRIPT_DIR       = Path(__file__).resolve().parent
CONVERTER_SCRIPT = SCRIPT_DIR / "core_hpc.py"
CONFIG_DIR       = SCRIPT_DIR


# ----─
# GÉNÉRATEUR DE SCRIPTS SBATCH
# ----─

def _build_script(lines: List[str]) -> str:
    """
    Assemble les lignes du script et garantit :
      - Pas d'espace avant #!/bin/bash
      - Pas de lignes vides parasites avec des espaces
      - Terminaison par un newline
    """
    cleaned = []
    for line in lines:
        # Supprimer les espaces de fin mais garder l'indentation interne
        cleaned.append(line.rstrip())
    return "\n".join(cleaned) + "\n"


def _resolve_python(
    venv:           Optional[str] = None,
    conda_env:      Optional[str] = None,
    python_version: str           = "python3",
) -> str:
    """
    Retourne le chemin vers le bon interpréteur Python.

    Avec un venv :
      1. Cherche le binaire explicitement demandé  (ex: python3.12)
      2. Sinon scanne venv/bin/ pour le python3.x le plus récent
      3. Sinon python3, python
      4. Si le venv n'existe pas localement, retourne le chemin calculé
         (il sera présent sur le nœud de calcul)
    """
    ver = python_version.strip()
    requested = ver if ver.startswith("python") else f"python{ver}"

    if venv:
        bin_dir = Path(venv) / "bin"

        # Candidats dans l'ordre de priorité :
        # 1. Le binaire explicitement demandé  (ex: python3.12)
        # 2. Tous les python3.x versionnés du venv, triés par version décroissante
        # 3. python3 générique, python
        if bin_dir.exists():
            versioned = sorted(
                [p.name for p in bin_dir.iterdir()
                 if p.name.startswith("python3.")            # python3.12 oui, python3 non
                 and p.name[7:].replace(".", "").isdigit()   # exclure python3.something-weird
                 and os.access(str(p), os.X_OK)],
                key=lambda n: [int(x) for x in n.replace("python", "").split(".") if x.isdigit()],
                reverse=True,
            )
        else:
            versioned = []

        # Ordre de priorité :
        # 1. Binaire explicitement demandé (ex: python3.12)
        # 2. Autres python3.x versionnés trouvés dans le venv (plus récent en premier)
        # 3. python3 / python génériques — UNIQUEMENT si aucun versionné n'existe
        if versioned:
            candidates = [requested] + versioned
        else:
            candidates = [requested, "python3", "python"]

        # Dédupliquer en gardant l'ordre
        seen, ordered = set(), []
        for c in candidates:
            if c not in seen:
                seen.add(c)
                ordered.append(c)

        for candidate in ordered:
            p = bin_dir / candidate
            # Si on a des binaires versionnés, ignorer python3/python génériques
            if versioned and candidate in ("python3", "python"):
                continue
            if p.exists() and os.access(str(p), os.X_OK):
                if candidate != requested:
                    print(f"  ℹ  '{requested}' absent du venv → utilisation de '{candidate}'")
                return str(p)

        # Venv absent localement (nœud de calcul) → retourner le chemin demandé
        return str(bin_dir / requested)

    return requested


def _env_activation_lines(
    venv:           Optional[str]       = None,
    conda_env:      Optional[str]       = None,
    modules:        Optional[List[str]] = None,
    python_bin:     str                 = "python3",
) -> List[str]:
    """
    Génère les lignes d'environnement pour le script SBATCH.

    Pour venv  : PAS de 'source activate' — on utilise le binaire absolu directement.
                 On ajoute juste une vérification que le binaire existe.
    Pour conda : 'conda activate' obligatoire car conda modifie le PATH pour
                 les bibliothèques C (HDF5, eccodes...).
    """
    lines = []

    # - 1. Modules HPC ------
    if modules:
        lines += [
            "# - Modules HPC -",
            "module purge",
        ]
        for mod in modules:
            lines.append(f"module load {mod}")
        lines.append("")

    # - 2. Conda (nécessite activate pour les libs C) ----─
    if conda_env:
        lines += [
            "# - Conda --",
            'CONDA_BASE=$(conda info --base 2>/dev/null || echo "")',
            'if [ -z "$CONDA_BASE" ]; then',
            '    for _p in "$HOME/miniconda3" "$HOME/anaconda3" "/opt/conda" "/usr/local/conda"; do',
            '        [ -f "$_p/etc/profile.d/conda.sh" ] && CONDA_BASE="$_p" && break',
            '    done',
            'fi',
            '[ -z "$CONDA_BASE" ] && echo " conda introuvable" && exit 1',
            'source "$CONDA_BASE/etc/profile.d/conda.sh"',
            f'conda activate "{conda_env}" || {{ echo " conda activate échoué"; exit 1; }}',
            "",
        ]

    # - 3. Venv : vérification du binaire seulement (pas de source activate) -
    elif venv:
        lines += [
            "# - Python venv -",
            f'PYTHON_BIN="{python_bin}"',
            'if [ ! -e "$PYTHON_BIN" ]; then',
            f'    echo " Python introuvable : $PYTHON_BIN"',
            f'    echo " Vérifiez --venv et --python"',
            '    exit 1',
            'fi',
            "",
        ]

    # - 4. Vérification finale ----
    lines += [
        "# - Vérification environnement -----─",
        f'echo "Python bin : {python_bin}"',
        f'"{python_bin}" --version || {{ echo " python --version échoué"; exit 1; }}',
        f'"{python_bin}" -c "import numpy, xarray, zarr; print(\'✅ numpy\', numpy.__version__, \'| xarray\', xarray.__version__, \'| zarr OK\')" || {{ echo " imports échoués — venv incomplet ?"; exit 1; }}',
        "",
    ]

    return lines


def make_sbatch_single(
    model:           str,
    run:             str,
    input_dir:       str,
    output_dir:      str,
    profile:         dict,
    log_dir:         SCRIPT_DIR,
    account:         Optional[str]       = None,
    qos:             Optional[str]       = None,
    venv:            Optional[str]       = None,
    conda_env:       Optional[str]       = None,
    modules:         Optional[List[str]] = None,
    python_version:  str                 = "python3",
    fmt:             Optional[str]       = None,
    dt_hours:        float               = 1.0,
    dask_workers:    int                 = 4,
    chunk_time:      int                 = 6,
    pyramids:        bool                = False,
    dashboard_address: str               = "0.0.0.0",
    dashboard_port:  int                 = 3112,
) -> str:
    """Génère un script SBATCH pour 1 modèle / 1 run."""

    jname    = f"nwp2zarr_{model}_{run}"
    mem      = f"{profile['mem_gb']}G"
    rt       = profile["read_threads"]
    wt       = profile["write_threads"]
    cpus     = profile["cpus_per_task"]
    python   = _resolve_python(venv, conda_env, python_version)

    lines = ["#!/bin/bash"]

    # - Directives SBATCH ----
    lines += [
        f"#SBATCH --job-name={jname}",
        f"#SBATCH --nodes=1",
        f"#SBATCH --ntasks=1",
        f"#SBATCH --cpus-per-task={cpus}",
        f"#SBATCH --mem={mem}",
        f"#SBATCH --time={profile['time']}",
        f"#SBATCH --partition={profile['partition']}",
        f"#SBATCH --output={jname}.out",
        f"#SBATCH --error={jname}.err",
        f"#SBATCH --mail-type=FAIL",
    ]
    if account:
        lines.append(f"#SBATCH --account={account}")
    if qos:
        lines.append(f"#SBATCH --qos={qos}")

    lines.append("")

    # - Activation environnement virtuel ---
    lines += _env_activation_lines(
        venv=venv, conda_env=conda_env, modules=modules, python_bin=python
    )

    # - Variables d'environnement ----─
    lines += [
        f"export NWP_READ_THREADS={rt}",
        f"export NWP_WRITE_THREADS={wt}",
        f"export OMP_NUM_THREADS={cpus}",
        f"export BLOSC_NTHREADS={max(4, cpus // 4)}",
        "",
    ]

    # - Infos ------─
    lines += [
        'echo "=== NWP2ZARR Start: $(date) ==="',
        f'echo "Modèle  : {model}"',
        f'echo "Run     : {run}"',
        f'echo "Nœud    : $(hostname)"',
        f'echo "CPUs    : $SLURM_CPUS_PER_TASK"',
        f'echo "RAM     : {mem}"',
        f'echo "Python  : {python}"',
        f'echo "Input   : {input_dir}"',
        f'echo "Output  : {output_dir}"',
        'echo "========================================="',
        "",
    ]

    # - Commande de conversion ----
    cmd_lines = [
        f"time {python} {CONVERTER_SCRIPT} \\",
        f"    --model {model} \\",
        f"    --run {run} \\",
        f'    --input "{input_dir}" \\',
        f'    --output "{output_dir}" \\',
        f'    --config "{CONFIG_DIR}" \\',
        f"    --read-threads {rt} \\",
        f"    --write-threads {wt} \\",
        f"    --dask-workers {dask_workers} \\",
        f"    --chunk-time {chunk_time} \\",
        f"    --dt-hours {dt_hours} \\",
        f"    --dashboard-address {dashboard_address}:{dashboard_port} \\",
    ]
    if fmt:
        cmd_lines.append(f"    --fmt {fmt} \\")
    if pyramids:
        cmd_lines.append("    --pyramids \\")
    cmd_lines[-1] = cmd_lines[-1].rstrip(" \\")

    lines += cmd_lines
    lines += [
        "",
        "EXIT_CODE=$?",
        'echo "=== Job terminé: $(date) | Code: $EXIT_CODE ==="',
        "exit $EXIT_CODE",
    ]

    return _build_script(lines)


def make_sbatch_array(
    models:          List[str],
    run:             str,
    input_base:      str,
    output_dir:      str,
    log_dir:         Path,
    account:         Optional[str]       = None,
    venv:            Optional[str]       = None,
    conda_env:       Optional[str]       = None,
    modules:         Optional[List[str]] = None,
    python_version:  str                 = "python3",
    dt_hours:        float               = 1.0,
    dask_workers:    int                 = 4,
    chunk_time:      int                 = 6,
    dashboard_address: str               = "0.0.0.0",
    dashboard_port:  int                 = 3112,
) -> str:
    """Génère un job array SLURM (1 task par modèle)."""

    # Profil le plus exigeant comme référence
    max_cpu = max(MODEL_PROFILES.get(m, MODEL_PROFILES["default"])["cpus_per_task"] for m in models)
    max_mem = max(MODEL_PROFILES.get(m, MODEL_PROFILES["default"])["mem_gb"]         for m in models)
    max_time = sorted(
        [MODEL_PROFILES.get(m, MODEL_PROFILES["default"])["time"] for m in models]
    )[-1]
    partition = MODEL_PROFILES.get(models[0], MODEL_PROFILES["default"])["partition"]

    jname = f"nwp2zarr_array_{run}"

    lines = ["#!/bin/bash"]
    lines += [
        f"#SBATCH --job-name={jname}",
        f"#SBATCH --nodes=1",
        f"#SBATCH --ntasks=1",
        f"#SBATCH --cpus-per-task={max_cpu}",
        f"#SBATCH --mem={max_mem}G",
        f"#SBATCH --time={max_time}",
        f"#SBATCH --partition={partition}",
        f"#SBATCH --array=0-{len(models)-1}",
        f"#SBATCH --output={log_dir}/{jname}_%A_%a.out",
        f"#SBATCH --error={log_dir}/{jname}_%A_%a.err",
    ]
    if account:
        lines.append(f"#SBATCH --account={account}")
    lines.append("")

    lines += _env_activation_lines(
        venv=venv, conda_env=conda_env, modules=modules,
        python_bin=_resolve_python(venv, conda_env, python_version)
    )

    # Tableaux bash modèles / formats / inputs
    model_arr  = " ".join(models)
    fmt_arr    = " ".join(
        MODEL_PROFILES.get(m, {}).get("fmt", "fa") for m in models
    )
    input_arr  = " ".join(f"{input_base}/{m}/{run}" for m in models)
    rt_arr     = " ".join(
        str(MODEL_PROFILES.get(m, MODEL_PROFILES["default"])["read_threads"]) for m in models
    )
    wt_arr     = " ".join(
        str(MODEL_PROFILES.get(m, MODEL_PROFILES["default"])["write_threads"]) for m in models
    )

    lines += [
        f"MODELS=({model_arr})",
        f"FMTS=({fmt_arr})",
        f"INPUTS=({input_arr})",
        f"READ_THREADS=({rt_arr})",
        f"WRITE_THREADS=({wt_arr})",
        "",
        "MODEL=${MODELS[$SLURM_ARRAY_TASK_ID]}",
        "FMT=${FMTS[$SLURM_ARRAY_TASK_ID]}",
        "INPUT=${INPUTS[$SLURM_ARRAY_TASK_ID]}",
        "RT=${READ_THREADS[$SLURM_ARRAY_TASK_ID]}",
        "WT=${WRITE_THREADS[$SLURM_ARRAY_TASK_ID]}",
        "",
        "export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK",
        f"export BLOSC_NTHREADS={max(4, max_cpu // 4)}",
        "",
        'echo "=== Task $SLURM_ARRAY_TASK_ID : $MODEL | $(date) ==="',
        'echo "=== Task $SLURM_ARRAY_TASK_ID : $MODEL | $(date) ==="',
        f'echo "Python  : {_resolve_python(venv, conda_env, python_version)}"',
        "",
        f"time {_resolve_python(venv, conda_env, python_version)} {CONVERTER_SCRIPT} \\",
        "    --model \"$MODEL\" \\",
        f"    --run {run} \\",
        "    --input \"$INPUT\" \\",
        f'    --output "{output_dir}" \\',
        f'    --config "{CONFIG_DIR}" \\',
        "    --read-threads \"$RT\" \\",
        "    --write-threads \"$WT\" \\",
        f"    --dask-workers {dask_workers} \\",
        f"    --chunk-time {chunk_time} \\",
        f"    --dt-hours {dt_hours} \\",
        f"    --dashboard-address 0.0.0.0:{dashboard_port}",
        "",
        'echo "=== $MODEL terminé: $(date) ==="',
    ]

    return _build_script(lines)


# ----─
# SOUMISSION SLURM
# ----─

def submit_job(
    script:      str,
    scripts_dir: Path,
    job_label:   str,
    dry_run:     bool = False,
) -> Optional[str]:
    """Sauvegarde le script et le soumet via sbatch."""

    # Sauvegarde systématique pour audit
    scripts_dir.mkdir(parents=True, exist_ok=True)
    ts          = datetime.now().strftime("%Y%m%d_%H%M%S")
    script_path = scripts_dir / f"{job_label}_{ts}.sh"
    script_path.write_text(script)
    print(f"📝 Script sauvé: {script_path}")

    if dry_run:
        print("🔍 [DRY RUN] Contenu du script :")
        print("─" * 60)
        print(script)
        print("─" * 60)
        return None

    # Vérification préalable : le script commence bien par #!/bin/bash
    first_line = script.split("\n")[0]
    if not first_line.startswith("#!"):
        print(f" Le script ne commence pas par un shebang : {repr(first_line)}")
        return None

    result = subprocess.run(
        ["sbatch", "--parsable"],
        input=script,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f" Erreur sbatch: {result.stderr.strip()}")
        # Afficher les premières lignes pour diagnostic
        print("   Début du script soumis :")
        for i, line in enumerate(script.split("\n")[:5]):
            print(f"   L{i+1}: {repr(line)}")
        return None

    job_id = result.stdout.strip().split(";")[0]
    print(f"✅ Job soumis: {job_id}")
    return job_id


def get_job_status(job_id: str) -> dict:
    """Retourne le statut d'un job SLURM via sacct."""
    result = subprocess.run(
        ["sacct", "-j", job_id,
         "--format=JobID,State,Elapsed,MaxRSS,CPUTime",
         "--noheader", "-P"],
        capture_output=True, text=True,
    )
    lines = [l for l in result.stdout.strip().split("\n")
             if l and not l.startswith(job_id + ".")]
    if lines:
        f = lines[0].split("|")
        return {
            "job_id":   f[0] if len(f) > 0 else "?",
            "state":    f[1] if len(f) > 1 else "?",
            "elapsed":  f[2] if len(f) > 2 else "?",
            "max_rss":  f[3] if len(f) > 3 else "?",
            "cpu_time": f[4] if len(f) > 4 else "?",
        }
    # Fallback squeue si sacct non disponible
    r2 = subprocess.run(
        ["squeue", "-j", job_id, "-h", "-o", "%i %T %M"],
        capture_output=True, text=True,
    )
    if r2.stdout.strip():
        parts = r2.stdout.strip().split()
        return {"job_id": parts[0], "state": parts[1] if len(parts) > 1 else "?",
                "elapsed": parts[2] if len(parts) > 2 else "?"}
    return {"job_id": job_id, "state": "UNKNOWN"}


def wait_for_jobs(job_ids: List[str], poll: int = 15, timeout: int = 3600):
    """Attend la fin de plusieurs jobs SLURM."""
    real_ids = [j for j in job_ids if j]
    if not real_ids:
        return
    print(f"⏳ Attente de {len(real_ids)} jobs...")
    pending = set(real_ids)
    t0      = time.time()
    while pending and (time.time() - t0 < timeout):
        time.sleep(poll)
        done = set()
        for jid in list(pending):
            s = get_job_status(jid.split("_")[0])
            if s["state"] in ("COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "NODE_FAIL"):
                icon = "✅" if s["state"] == "COMPLETED" else ""
                print(f"  {icon} Job {jid}: {s['state']} (elapsed={s.get('elapsed','?')})")
                done.add(jid)
        pending -= done
    if pending:
        print(f"⚠  Timeout, jobs encore en cours: {pending}")


def make_cron_script(
    models:        List[str],
    runs_per_day:  List[int],
    input_base:    str,
    output_dir:    str,
    account:       Optional[str] = None,
    venv:          Optional[str] = None,
    conda_env:     Optional[str] = None,
    out_script:    Optional[str] = None,
) -> str:
    """Génère un script shell exécutable par cron."""
    runs_str   = " ".join(str(r) for r in runs_per_day)
    models_str = " ".join(models)
    out        = out_script or str(SCRIPT_DIR / "cron_nwp2zarr.sh")
    launcher   = str(Path(__file__).resolve())

    lines = [
        "#!/bin/bash",
        "# Auto-généré par slurm_launcher.py",
        "# Cron : 5 * * * * /chemin/vers/cron_nwp2zarr.sh >> /var/log/nwp2zarr.log 2>&1",
        "",
        f"MODELS='{models_str}'",
        f"RUNS='{runs_str}'",
        f"INPUT_BASE='{input_base}'",
        f"OUTPUT_DIR='{output_dir}'",
        f"LAUNCHER='{launcher}'",
        "LOCK_DIR='/tmp/nwp2zarr_locks'",
        "mkdir -p \"$LOCK_DIR\"",
        "",
        "CURRENT_HOUR=$(date -u +%-H)",
        "CURRENT_DATE=$(date -u +%Y%m%d)",
        "",
        "for RUN_HOUR in $RUNS; do",
        '    if [ "$CURRENT_HOUR" -eq "$RUN_HOUR" ]; then',
        '        RUN_ID="${CURRENT_DATE}$(printf \'%02d\' $RUN_HOUR)"',
        '        LOCK="$LOCK_DIR/$RUN_ID.lock"',
        '        [ -f "$LOCK" ] && continue',
        "",
        '        echo "$(date) [$RUN_ID] Soumission jobs..."',
    ]

    # Activation env dans le script cron lui-même (pour que python3 soit le bon)
    if venv:
        lines.append(f'        source "{Path(venv) / "bin" / "activate"}" 2>/dev/null || true')
    elif conda_env:
        lines.append(f'        conda activate "{conda_env}" 2>/dev/null || true')

    env_arg = f' \\\n            --venv "{venv}"' if venv else \
              (f' \\\n            --conda-env "{conda_env}"' if conda_env else "")

    lines += [
        f'        python3 "$LAUNCHER" multi_job \\',
        f'            --models "$MODELS" \\',
        f'            --run "$RUN_ID" \\',
        f'            --input-base "$INPUT_BASE" \\',
        f'            --output "$OUTPUT_DIR"' +
        (f' \\' if account or venv or conda_env else ""),
    ]
    if venv:
        lines.append(f'            --venv "{venv}"' + (' \\' if account else ""))
    elif conda_env:
        lines.append(f'            --conda-env "{conda_env}"' + (' \\' if account else ""))
    if account:
        lines.append(f'            --account "{account}"')

    lines += [
        "",
        '        touch "$LOCK"',
        '        find "$LOCK_DIR" -name "*.lock" -mtime +2 -delete',
        '        echo "$(date) [$RUN_ID] Jobs soumis."',
        "    fi",
        "done",
    ]

    script = _build_script(lines)
    Path(out).write_text(script)
    Path(out).chmod(0o755)
    print(f"📅 Script cron écrit: {out}")
    return script


# ----─
# CLI
# ----─

def main():
    parser = argparse.ArgumentParser(
        description="Lanceur SLURM — NWP → Zarr",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    # - single_job ------
    p = sub.add_parser("single_job", help="1 job pour 1 modèle")
    p.add_argument("--model",         required=True)
    p.add_argument("--run",           required=True, help="YYYYMMDDHH")
    p.add_argument("--input",         required=True)
    p.add_argument("--output",        required=True)
    p.add_argument("--fmt",           default=None,
                   choices=["fa", "lfa", "grib", "grib1", "grib2", "netcdf"])
    p.add_argument("--dt-hours",      type=float, default=1.0)
    p.add_argument("--account",       default=None)
    p.add_argument("--qos",           default=None)
    p.add_argument("--partition",     default=None)
    p.add_argument("--venv",          default=None,
                   help="Chemin vers le venv Python (source venv/bin/activate)")
    p.add_argument("--conda-env", "--conda", default=None,
                   help="Nom de l'environnement Conda (conda activate)")
    p.add_argument("--modules",       nargs="+", default=[],
                   help="Modules HPC à charger (module load)")
    p.add_argument("--python",        default="python3",
                   help="Version Python à utiliser, ex: 3.12 ou python3.12 (défaut: python3)")
    p.add_argument("--dask-workers",  type=int,   default=4)
    p.add_argument("--read-threads",  type=int,   default=None, help="Overfide read_threads")
    p.add_argument("--write-threads", type=int,   default=None, help="Override write_threads")
    p.add_argument("--chunk-time",    type=int,   default=6)
    p.add_argument("--pyramids",       action="store_true")
    p.add_argument("--dashboard-port", type=int, default=3112)
    p.add_argument("--dashboard-address", default="0.0.0.0")
    p.add_argument("--dry-run",        action="store_true")
    p.add_argument("--wait",           action="store_true")
    p.add_argument("--log-dir",       default=None)

    # - multi_job ------─
    p2 = sub.add_parser("multi_job", help="N modèles en job array")
    p2.add_argument("--models",       required=True, help="Ex: arome,aladin")
    p2.add_argument("--run",          required=True)
    p2.add_argument("--input-base",   required=True)
    p2.add_argument("--output",       required=True)
    p2.add_argument("--dt-hours",     type=float, default=1.0)
    p2.add_argument("--account",      default=None)
    p2.add_argument("--venv",         default=None,
                    help="Chemin vers le venv Python (source venv/bin/activate)")
    p2.add_argument("--conda-env", "--conda", default=None,
                    help="Nom de l'environnement Conda (conda activate)")
    p2.add_argument("--modules",      nargs="+", default=[],
                    help="Modules HPC à charger (module load)")
    p2.add_argument("--python",       default="python3",
                    help="Version Python, ex: 3.12 ou python3.12")
    p2.add_argument("--dask-workers", type=int,   default=4)
    p2.add_argument("--chunk-time",   type=int,   default=6)
    p2.add_argument("--dashboard-port", type=int, default=3112)
    p2.add_argument("--dashboard-address", default="0.0.0.0")
    p2.add_argument("--dry-run",      action="store_true")
    p2.add_argument("--wait",         action="store_true")
    p2.add_argument("--log-dir",      default=None)

    # - status ------
    p3 = sub.add_parser("status", help="Statut d'un job SLURM")
    p3.add_argument("--jobid", required=True)

    # - cron -------
    p4 = sub.add_parser("cron", help="Générer un script cron")
    p4.add_argument("--models",        required=True)
    p4.add_argument("--runs-per-day",  nargs="+", type=int, default=[0, 6, 12, 18])
    p4.add_argument("--input-base",    required=True)
    p4.add_argument("--output",        required=True)
    p4.add_argument("--account",       default=None)
    p4.add_argument("--venv",          default=None,
                    help="Chemin vers le venv Python")
    p4.add_argument("--conda-env",     default=None)
    p4.add_argument("--out-script",    default=None)

    args = parser.parse_args()

    # - Traitement par mode -----─

    if args.mode == "single_job":
        profile = MODEL_PROFILES.get(args.model, MODEL_PROFILES["default"]).copy()
        if args.partition:
            profile["partition"] = args.partition
        if args.read_threads:
            profile["read_threads"] = args.read_threads
        if args.write_threads:
            profile["write_threads"] = args.write_threads

        log_dir = Path(args.log_dir) if args.log_dir else Path(args.output) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        script = make_sbatch_single(
            model           = args.model,
            run             = args.run,
            input_dir       = args.input,
            output_dir      = args.output,
            profile         = profile,
            log_dir         = log_dir,
            account         = args.account,
            qos             = args.qos,
            venv            = args.venv,
            conda_env       = args.conda_env,
            modules         = args.modules,
            python_version  = args.python,
            fmt             = args.fmt,
            dt_hours        = args.dt_hours,
            dask_workers    = args.dask_workers,
            chunk_time      = args.chunk_time,
            pyramids        = args.pyramids,
            dashboard_address = args.dashboard_address,
            dashboard_port  = args.dashboard_port,
        )

        scripts_dir = Path(args.output) / "sbatch_scripts"
        job_id = submit_job(script, scripts_dir, f"{args.model}_{args.run}", args.dry_run)

        if job_id and args.wait:
            wait_for_jobs([job_id])

    elif args.mode == "multi_job":
        models  = [m.strip() for m in args.models.split(",")]
        log_dir = Path(args.log_dir) if args.log_dir else Path(args.output) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        script = make_sbatch_array(
            models          = models,
            run             = args.run,
            input_base      = args.input_base,
            output_dir      = args.output,
            log_dir         = log_dir,
            account         = args.account,
            venv            = args.venv,
            conda_env       = args.conda_env,
            modules         = args.modules,
            python_version  = args.python,
            dt_hours        = args.dt_hours,
            dask_workers    = args.dask_workers,
            chunk_time      = args.chunk_time,
            dashboard_address = args.dashboard_address,
            dashboard_port  = args.dashboard_port,
        )

        scripts_dir = Path(args.output) / "sbatch_scripts"
        job_id = submit_job(script, scripts_dir, f"array_{args.run}", args.dry_run)

        if job_id and args.wait:
            wait_for_jobs([job_id])

    elif args.mode == "status":
        s = get_job_status(args.jobid)
        for k, v in s.items():
            print(f"  {k:12}: {v}")

    elif args.mode == "cron":
        models = [m.strip() for m in args.models.split(",")]
        make_cron_script(
            models       = models,
            runs_per_day = args.runs_per_day,
            input_base   = args.input_base,
            output_dir   = args.output,
            account      = args.account,
            venv         = args.venv,
            conda_env    = args.conda_env,
            out_script   = args.out_script,
        )


if __name__ == "__main__":
    main()
