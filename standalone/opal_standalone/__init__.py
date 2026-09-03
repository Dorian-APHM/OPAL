"""OPAL standalone — each brick as a self-contained Streamlit app.

Importing this package makes OPAL's analysis engines importable without the
FastAPI/SQLAlchemy server stack (see :mod:`opal_standalone.bootstrap`).
"""
from opal_standalone.bootstrap import install as _install

_install()

__all__ = ["bootstrap", "config", "omop", "store", "ui", "glue", "views"]
