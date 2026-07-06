"""Test the B&D Garage config flow."""

from unittest.mock import AsyncMock

from bnd_garage_client.errors import (
    AmbiguousDeviceError,
    AuthenticationError,
    HubUnreachableError,
)
import pytest

from homeassistant.components.bnd_garage.const import (
    CONF_ACTION_DEVICE_ID,
    CONF_ACTIVATION_CODE,
    CONF_HUB_ID,
    CONF_USER_PASSWORD,
    DOMAIN,
)
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from . import setup_integration
from .conftest import TEST_CREDENTIALS, TEST_HOST

from tests.common import MockConfigEntry


async def test_form(
    hass: HomeAssistant,
    mock_register: AsyncMock,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test we get the form and can pair successfully."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert not result["errors"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_HOST: TEST_HOST,
            CONF_ACTIVATION_CODE: "123456",
            CONF_USER_PASSWORD: "test-user-password",
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "B&D Garage"
    assert result["data"][CONF_HOST] == TEST_HOST
    assert result["data"][CONF_HUB_ID] == TEST_CREDENTIALS.hub_id
    assert result["data"][CONF_ACTION_DEVICE_ID] == TEST_CREDENTIALS.device_id
    assert result["result"].unique_id == TEST_CREDENTIALS.hub_id
    assert len(mock_setup_entry.mock_calls) == 1


@pytest.mark.parametrize(
    ("side_effect", "expected_error"),
    [
        pytest.param(AuthenticationError, "invalid_auth", id="invalid_auth"),
        pytest.param(HubUnreachableError, "cannot_connect", id="cannot_connect"),
        pytest.param(
            AmbiguousDeviceError([("door 1", "id1"), ("door 2", "id2")]),
            "multiple_devices_found",
            id="multiple_devices_found",
        ),
        pytest.param(Exception, "unknown", id="unknown"),
    ],
)
@pytest.mark.usefixtures("mock_setup_entry")
async def test_form_exceptions(
    hass: HomeAssistant,
    mock_register: AsyncMock,
    side_effect: type[Exception],
    expected_error: str,
) -> None:
    """Test we handle pairing errors and can then recover."""
    mock_register.side_effect = side_effect
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_HOST: TEST_HOST,
            CONF_ACTIVATION_CODE: "123456",
            CONF_USER_PASSWORD: "test-user-password",
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected_error}

    mock_register.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_HOST: TEST_HOST,
            CONF_ACTIVATION_CODE: "123456",
            CONF_USER_PASSWORD: "test-user-password",
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_duplicate_hub(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_register: AsyncMock,
) -> None:
    """Test that pairing with an already-configured hub aborts."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_HOST: TEST_HOST,
            CONF_ACTIVATION_CODE: "123456",
            CONF_USER_PASSWORD: "test-user-password",
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    mock_register: AsyncMock,
) -> None:
    """Test the reauth flow."""
    await setup_integration(hass, mock_config_entry, [])

    result = await mock_config_entry.start_reauth_flow(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_ACTIVATION_CODE: "654321",
            CONF_USER_PASSWORD: "new-user-password",
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert len(hass.config_entries.async_entries()) == 1

    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    ("side_effect", "expected_error"),
    [
        pytest.param(AuthenticationError, "invalid_auth", id="invalid_auth"),
        pytest.param(HubUnreachableError, "cannot_connect", id="cannot_connect"),
    ],
)
async def test_reauth_exceptions(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    mock_register: AsyncMock,
    side_effect: type[Exception],
    expected_error: str,
) -> None:
    """Test we handle re-pairing errors and can then recover."""
    await setup_integration(hass, mock_config_entry, [])

    result = await mock_config_entry.start_reauth_flow(hass)

    mock_register.side_effect = side_effect
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_ACTIVATION_CODE: "654321",
            CONF_USER_PASSWORD: "new-user-password",
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected_error}

    mock_register.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_ACTIVATION_CODE: "654321",
            CONF_USER_PASSWORD: "new-user-password",
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"

    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
