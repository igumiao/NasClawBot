import os

import pytest

from app.config import get_settings


@pytest.mark.skipif(not os.getenv("RUN_CONNECTIVITY_TESTS"), reason="integration-only")
def test_connectivity_settings_are_present():
    settings = get_settings()
    assert settings.mteam_api_key
    assert settings.mteam_base_url
    assert settings.qb_base_url
    assert settings.qb_username
    assert settings.qb_password
