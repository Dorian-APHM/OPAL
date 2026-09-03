"""OPAL standalone — Extraction de données.

Lancement :
    streamlit run standalone/apps/datamanagement.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from opal_standalone import ui  # noqa: E402
from opal_standalone.views import datamanagement as view  # noqa: E402

ui.page_setup(view.TITLE, view.ICON)
config, cdm, store = ui.sidebar("datamanagement")
view.render(config, cdm, store)
