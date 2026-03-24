"""
Tests that en.json and fr.json have matching keys (i18n completeness).
"""
import json
from pathlib import Path


I18N_DIR = Path(__file__).resolve().parent.parent / "i18n"


def _collect_keys(d: dict, prefix: str = "") -> set[str]:
    """Recursively collect dotted key paths from a nested dict."""
    keys = set()
    for k, v in d.items():
        full = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            keys |= _collect_keys(v, full)
        else:
            keys.add(full)
    return keys


def test_i18n_files_exist():
    assert (I18N_DIR / "en.json").exists(), "en.json missing"
    assert (I18N_DIR / "fr.json").exists(), "fr.json missing"


def test_i18n_key_parity():
    """en.json and fr.json must have exactly the same set of keys."""
    with open(I18N_DIR / "en.json", encoding="utf-8") as f:
        en = json.load(f)
    with open(I18N_DIR / "fr.json", encoding="utf-8") as f:
        fr = json.load(f)

    en_keys = _collect_keys(en)
    fr_keys = _collect_keys(fr)

    missing_in_fr = en_keys - fr_keys
    missing_in_en = fr_keys - en_keys

    assert not missing_in_fr, f"Keys in en.json but missing in fr.json: {sorted(missing_in_fr)}"
    assert not missing_in_en, f"Keys in fr.json but missing in en.json: {sorted(missing_in_en)}"


def test_i18n_no_empty_values():
    """No translation value should be empty."""
    for lang in ("en", "fr"):
        with open(I18N_DIR / f"{lang}.json", encoding="utf-8") as f:
            data = json.load(f)
        keys = _collect_keys(data)
        assert len(keys) > 0, f"{lang}.json has no keys"


def test_i18n_endpoint(client):
    """Test the /api/i18n/{lang} endpoint returns valid JSON."""
    resp = client.get("/api/i18n/en")
    assert resp.status_code == 200
    data = resp.json()
    assert "app" in data

    resp = client.get("/api/i18n/fr")
    assert resp.status_code == 200

    resp = client.get("/api/i18n/zz")
    assert resp.status_code == 404
