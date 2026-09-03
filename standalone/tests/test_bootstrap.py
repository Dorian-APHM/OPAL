"""The bridge must expose the backend engines without the server stack."""
import sys

import pytest


def test_backend_is_importable():
    import config as backend_config

    assert "Condition" in backend_config.DOMAIN_CONFIG


def test_shims_replace_the_server_modules():
    import db.app_db
    import utils.cdm_helper
    import utils.reference_labels

    assert utils.cdm_helper.__name__.startswith("opal_standalone.shims")
    assert utils.reference_labels.__name__.startswith("opal_standalone.shims")
    assert db.app_db.__name__.startswith("opal_standalone.shims")


def test_engines_import_without_fastapi_or_sqlalchemy():
    """Importing every engine used by the bricks must not pull the web stack."""
    import modules.cohort.characterization  # noqa: F401
    import modules.cohort.comparison  # noqa: F401
    import modules.cohort.pathways  # noqa: F401
    import modules.cohort.sql_builder  # noqa: F401
    import modules.datamanagement.extractor  # noqa: F401
    import modules.estimation.survival  # noqa: F401
    import modules.incidence.engine  # noqa: F401
    import modules.lineage.parser  # noqa: F401
    import modules.mapping.suggest  # noqa: F401
    import modules.quality.comparator  # noqa: F401
    import modules.quality.conformity  # noqa: F401
    import modules.quality.engine  # noqa: F401
    import modules.quality.report_builder  # noqa: F401

    assert "fastapi" not in sys.modules
    assert "sqlalchemy" not in sys.modules


def test_null_session_refuses_queries():
    from db.app_db import SessionLocal

    session = SessionLocal()
    with pytest.raises(RuntimeError):
        session.query(object)
    session.close()


def test_schema_map_resolves_categories():
    from utils.cdm_helper import SchemaMap

    schema = SchemaMap("omop_cdm", {"vocabulary": "omop_vocab"})
    assert str(schema) == "omop_cdm"
    assert schema.t("person") == "omop_cdm.person"
    assert schema.t("concept") == "omop_vocab.concept"
    assert schema.schema_for("unknown_table") == "omop_cdm"
