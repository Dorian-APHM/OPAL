"""Tests for utils/cdm_helper.py — Centralized CDM connection helper."""
import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException


class TestGetCdmConnection:
    def test_cdm_not_found(self):
        from utils.cdm_helper import get_cdm_connection

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            get_cdm_connection(db, "nonexistent")
        assert exc_info.value.status_code == 404

    @patch("utils.cdm_helper.get_omop_connection")
    @patch("utils.cdm_helper.decrypt_password")
    def test_success(self, mock_decrypt, mock_get_conn):
        from utils.cdm_helper import get_cdm_connection

        mock_decrypt.return_value = "decrypted_pass"
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn

        # Mock CDM config
        cdm = MagicMock()
        cdm.db_host = "localhost"
        cdm.db_port = 5432
        cdm.db_name = "testdb"
        cdm.db_user = "user"
        cdm.db_password_encrypted = "encrypted"
        cdm.omop_schema = "omop_cdm"

        db = MagicMock()
        # First query: CdmConfig, second: AnalysisSettings
        db.query.return_value.filter.return_value.first.side_effect = [cdm, None]

        conn, schema = get_cdm_connection(db, "test_cdm")

        assert conn == mock_conn
        assert schema == "omop_cdm"
        mock_decrypt.assert_called_once_with("encrypted")
        mock_get_conn.assert_called_once()

    @patch("utils.cdm_helper.get_omop_connection")
    @patch("utils.cdm_helper.decrypt_password")
    def test_with_analysis_settings_override(self, mock_decrypt, mock_get_conn):
        from utils.cdm_helper import get_cdm_connection

        mock_decrypt.return_value = "pass"
        mock_get_conn.return_value = MagicMock()

        cdm = MagicMock()
        cdm.db_host = "localhost"
        cdm.db_port = 5432
        cdm.db_name = "testdb"
        cdm.db_user = "user"
        cdm.db_password_encrypted = "enc"
        cdm.omop_schema = "omop_cdm"

        settings = MagicMock()
        settings.omop_schema = "custom_schema"

        db = MagicMock()
        db.query.return_value.filter.return_value.first.side_effect = [cdm, settings]

        conn, schema = get_cdm_connection(db, "test_cdm")
        assert schema == "custom_schema"


class TestCheckCdmAccess:
    def test_disabled_auth(self):
        """When auth is disabled, access is always granted."""
        from utils.cdm_helper import check_cdm_access
        request = MagicMock()
        with patch("config.AUTH_ENABLED", False):
            # Should not raise
            check_cdm_access(request, "any_cdm")

    def test_no_user_raises_401(self):
        from utils.cdm_helper import check_cdm_access

        request = MagicMock()
        request.state = MagicMock(spec=[])  # no 'user' attribute

        with patch("config.AUTH_ENABLED", True):
            with pytest.raises(HTTPException) as exc_info:
                check_cdm_access(request, "test_cdm")
            assert exc_info.value.status_code == 401

    def test_access_denied_raises_403(self):
        from utils.cdm_helper import check_cdm_access

        request = MagicMock()
        request.state.user = {"preferred_username": "testuser", "roles": ["viewer"]}

        with patch("config.AUTH_ENABLED", True), \
             patch("auth.keycloak._check_cdm_access", return_value=False):
            with pytest.raises(HTTPException) as exc_info:
                check_cdm_access(request, "restricted_cdm")
            assert exc_info.value.status_code == 403

    def test_access_granted(self):
        from utils.cdm_helper import check_cdm_access

        request = MagicMock()
        request.state.user = {"preferred_username": "admin", "roles": ["admin"]}

        with patch("config.AUTH_ENABLED", True), \
             patch("auth.keycloak._check_cdm_access", return_value=True):
            # Should not raise
            check_cdm_access(request, "test_cdm")


class TestColumnExistsCache:
    """Regression: a transient failure must not be cached (would permanently
    disable a column that actually exists)."""

    def _make_conn(self, behaviors):
        """behaviors: list of callables run on each execute() call."""
        import itertools
        from unittest.mock import MagicMock
        calls = iter(behaviors)

        class _Cur:
            def execute(self, *a, **k):
                next(calls)()  # may raise

            def fetchone(self):
                return (1,)

            def close(self):
                pass

        conn = MagicMock()
        conn.dsn = "host=h port=5432 dbname=d user=u"
        conn.cursor = lambda *a, **k: _Cur()
        return conn

    def test_transient_error_is_not_cached(self):
        from utils import cdm_helper
        cdm_helper._column_exists_cache.clear()

        def boom():
            raise RuntimeError("connection reset")

        def ok():
            return None

        conn = self._make_conn([boom, ok])
        # First call hits the error → False, and must NOT be cached.
        assert cdm_helper._column_exists(conn, "omop", "drug_exposure", "drug_source_atc") is False
        assert len(cdm_helper._column_exists_cache) == 0
        # Second call succeeds → True, and is cached.
        assert cdm_helper._column_exists(conn, "omop", "drug_exposure", "drug_source_atc") is True
        assert len(cdm_helper._column_exists_cache) == 1

    def test_success_is_cached(self):
        from utils import cdm_helper
        cdm_helper._column_exists_cache.clear()
        conn = self._make_conn([lambda: None, lambda: (_ for _ in ()).throw(AssertionError("should be cached"))])
        assert cdm_helper._column_exists(conn, "omop", "person", "x") is True
        # Second call must come from cache (execute would assert if hit again).
        assert cdm_helper._column_exists(conn, "omop", "person", "x") is True
