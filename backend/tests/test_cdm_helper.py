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
