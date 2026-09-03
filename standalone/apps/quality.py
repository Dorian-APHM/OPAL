"""OPAL standalone — Qualité des données.

Lancement :
    streamlit run standalone/apps/quality.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from opal_standalone import ui  # noqa: E402
from opal_standalone.views import quality as view  # noqa: E402

ui.page_setup(view.TITLE, view.ICON)
config, cdm, store = ui.sidebar("quality")
view.render(config, cdm, store)
