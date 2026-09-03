"""OPAL standalone — toutes les briques dans une seule application.

Chaque brique reste lançable séparément (``streamlit run standalone/apps/<brique>.py``) ;
cette page les regroupe pour un usage quotidien.

Lancement :
    streamlit run standalone/apps/opal.py
"""
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from opal_standalone import ui  # noqa: E402

ui.page_setup("OPAL", "🩺")

labels = {f"{icon}  {label}": key for key, label, icon, _desc in ui.BRICKS}
with st.sidebar:
    st.markdown("### Brique")
    chosen = st.radio("Brique", list(labels), label_visibility="collapsed", key="_opal_brick")

brick = labels[chosen]
view = importlib.import_module(f"opal_standalone.views.{brick}")
config, cdm, store = ui.sidebar(brick)
view.render(config, cdm, store)
