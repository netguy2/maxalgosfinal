"""
Test suite for utils/env_patch.py
"""

import os
from unittest.mock import patch
from utils.env_patch import install_getenv_patch
from utils.broker_context import broker_credential_context


def test_getenv_patch_installed():
    install_getenv_patch()
    assert os.getenv is not None


def test_getenv_patch_with_broker_context():
    install_getenv_patch()

    with patch("database.user_db.get_user_broker_credentials") as mock_get_creds:
        mock_get_creds.return_value = {
            "broker_api_key": "test_user_key_123",
            "broker_api_secret": "test_user_secret_456",
        }

        with broker_credential_context("user_a", "zerodha"):
            api_key = os.getenv("BROKER_API_KEY")
            api_secret = os.getenv("BROKER_API_SECRET")
            assert api_key == "test_user_key_123"
            assert api_secret == "test_user_secret_456"
            mock_get_creds.assert_called_with("user_a", "zerodha")
