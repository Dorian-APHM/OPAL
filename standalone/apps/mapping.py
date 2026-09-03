"""OPAL standalone — Mapping des termes source.

Lancement :
    streamlit run standalone/apps/mapping.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from opal_standalone import ui  # noqa: E402
from opal_standalone.views import mapping as view  # noqa: E402

ui.page_setup(view.TITLE, view.ICON)
config, cdm, store = ui.sidebar("mapping")
view.render(config, cdm, store)
