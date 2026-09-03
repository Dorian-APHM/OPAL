"""OPAL standalone — Lignage ETL.

Lancement :
    streamlit run standalone/apps/lineage.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from opal_standalone import ui  # noqa: E402
from opal_standalone.views import lineage as view  # noqa: E402

ui.page_setup(view.TITLE, view.ICON)
config, cdm, store = ui.sidebar("lineage")
view.render(config, cdm, store)
