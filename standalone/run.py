#!/usr/bin/env python3
"""Launcher for the OPAL standalone bricks.

    python standalone/run.py                 # all bricks in one app
    python standalone/run.py quality         # only the quality brick
    python standalone/run.py quality --port 8502
    python standalone/run.py --list

Equivalent to running ``streamlit run standalone/apps/<brick>.py`` yourself.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

APPS_DIR = Path(__file__).resolve().parent / "apps"

BRICKS = {
    "opal": "Toutes les briques dans une seule application",
    "quality": "Qualité des données (analyses, conformité, rapports)",
    "cohort": "Constructeur de cohortes",
    "concepts": "Explorateur de concepts",
    "concept_sets": "Concept sets",
    "mapping": "Mapping des termes source",
    "incidence": "Taux d'incidence",
    "estimation": "Estimation (Kaplan-Meier)",
    "datamanagement": "Extraction de données",
    "lineage": "Lignage ETL",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("brick", nargs="?", default="opal", choices=sorted(BRICKS),
                        help="brique à lancer (défaut : opal)")
    parser.add_argument("--port", type=int, default=None, help="port d'écoute Streamlit")
    parser.add_argument("--config", default=None,
                        help="chemin du fichier de configuration TOML")
    parser.add_argument("--list", action="store_true", help="lister les briques et quitter")
    args = parser.parse_args(argv)

    if args.list:
        width = max(len(name) for name in BRICKS)
        for name, description in BRICKS.items():
            print(f"{name.ljust(width)}  {description}")
        return 0

    app = APPS_DIR / f"{args.brick}.py"
    if not app.exists():
        print(f"Application introuvable : {app}", file=sys.stderr)
        return 1

    command = [sys.executable, "-m", "streamlit", "run", str(app)]
    if args.port:
        command += ["--server.port", str(args.port)]

    env = None
    if args.config:
        import os

        env = dict(os.environ, OPAL_STANDALONE_CONFIG=str(Path(args.config).expanduser()))

    try:
        return subprocess.call(command, env=env)
    except FileNotFoundError:
        print(
            "Streamlit n'est pas installé. Installez les dépendances :\n"
            "    pip install -r standalone/requirements.txt",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
