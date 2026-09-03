"""OPAL standalone — Explorateur de concepts.

Lancement :
    streamlit run standalone/apps/concepts.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from opal_standalone import ui  # noqa: E402
from opal_standalone.views import concepts as view  # noqa: E402

ui.page_setup(view.TITLE, view.ICON)
config, cdm, store = ui.sidebar("concepts")
view.render(config, cdm, store)
