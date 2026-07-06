"""Common fixtures for the B&D Garage tests."""

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

from bnd_garage_client import Credentials, HubStatus
from bnd_garage_client.models import DoorState
import pytest

from homeassistant.components.bnd_garage.const import (
    CONF_ACTION_DEVICE_ID,
    CONF_HUB_ID,
    CONF_PHONE_ID,
    CONF_PHONE_PASSWORD,
    CONF_PHONE_SECRET,
    CONF_USER_PASSWORD,
)
from homeassistant.const import CONF_HOST

from tests.common import MockConfigEntry

TEST_HOST = "192.168.1.50"
TEST_HUB_ID = "test-hub-id"
TEST_CREDENTIALS = Credentials(
    hub_id=TEST_HUB_ID,
    phone_id="test-phone-id",
    phone_password="test-phone-password",
    control_secret="test-control-secret",
    user_password="test-user-password",
    device_id="test-device-id",
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> None:
    """Enable custom integrations for every test in this suite."""


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Override async_setup_entry."""
    with patch(
        "homeassistant.components.bnd_garage.async_setup_entry",
        return_value=True,
    ) as mock_setup_entry:
        yield mock_setup_entry


@pytest.fixture
def mock_register() -> Generator[AsyncMock]:
    """Mock the bnd_garage_client pairing call used by the config flow."""
    with patch(
        "homeassistant.components.bnd_garage.config_flow.pair_new_phone",
        autospec=True,
    ) as mock_register:
        mock_register.return_value = TEST_CREDENTIALS
        yield mock_register


@pytest.fixture
def mock_client() -> Generator[AsyncMock]:
    """Mock the bnd_garage_client HubClient used during integration setup."""
    with patch(
        "homeassistant.components.bnd_garage.HubClient", autospec=True
    ) as mock_client_cls:
        client = mock_client_cls.return_value
        client.connect.return_value = None
        client.close.return_value = None
        client.get_status.return_value = HubStatus(
            state=DoorState.CLOSED, position=0, rate=0
        )
        yield client


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Mock a config entry."""
    return MockConfigEntry(
        domain="bnd_garage",
        title="B&D Garage",
        data={
            CONF_HOST: TEST_HOST,
            CONF_HUB_ID: TEST_CREDENTIALS.hub_id,
            CONF_PHONE_ID: TEST_CREDENTIALS.phone_id,
            CONF_PHONE_PASSWORD: TEST_CREDENTIALS.phone_password,
            CONF_PHONE_SECRET: TEST_CREDENTIALS.control_secret,
            CONF_USER_PASSWORD: TEST_CREDENTIALS.user_password,
            CONF_ACTION_DEVICE_ID: TEST_CREDENTIALS.device_id,
        },
        unique_id=TEST_HUB_ID,
    )
