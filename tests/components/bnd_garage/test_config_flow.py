"""Test the B&D Garage config flow."""

from unittest.mock import AsyncMock

from bnd_garage_client.errors import AuthenticationError, HubUnreachableError
import pytest

from homeassistant.components.bnd_garage.const import (
    CONF_ACTIVATION_CODE,
    CONF_DEVICE_IDS,
    CONF_HUB_ID,
    CONF_USER_PASSWORD,
    DOMAIN,
)
from homeassistant.config_entries import SOURCE_DHCP, SOURCE_USER
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from . import setup_integration
from .conftest import TEST_CREDENTIALS, TEST_HOST

from tests.common import MockConfigEntry

NEW_HOST = "192.168.1.77"
DHCP_DISCOVERY = DhcpServiceInfo(
    ip=NEW_HOST, hostname="bnd-hub", macaddress="ac64cfc2857e"
)


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
    assert result["data"][CONF_DEVICE_IDS] == list(TEST_CREDENTIALS.devices)
    assert result["result"].unique_id == TEST_CREDENTIALS.hub_id
    assert len(mock_setup_entry.mock_calls) == 1


@pytest.mark.parametrize(
    ("side_effect", "expected_error"),
    [
        pytest.param(AuthenticationError, "invalid_auth", id="invalid_auth"),
        pytest.param(HubUnreachableError, "cannot_connect", id="cannot_connect"),
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


@pytest.mark.usefixtures("mock_client", "mock_read_hub_id")
async def test_reconfigure_changes_host(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the hub's address can be changed without re-pairing."""
    await setup_integration(hass, mock_config_entry, [])

    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: NEW_HOST}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_HOST] == NEW_HOST
    # The pairing is untouched, so nothing has to be set up again.
    assert mock_config_entry.data[CONF_HUB_ID] == TEST_CREDENTIALS.hub_id
    assert mock_config_entry.unique_id == TEST_CREDENTIALS.hub_id


@pytest.mark.usefixtures("mock_client")
async def test_reconfigure_cannot_connect(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_read_hub_id: AsyncMock,
) -> None:
    """Test an unreachable new address is reported and can then be corrected."""
    await setup_integration(hass, mock_config_entry, [])

    result = await mock_config_entry.start_reconfigure_flow(hass)

    mock_read_hub_id.side_effect = HubUnreachableError
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: NEW_HOST}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert mock_config_entry.data[CONF_HOST] == TEST_HOST

    mock_read_hub_id.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: NEW_HOST}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_HOST] == NEW_HOST


@pytest.mark.usefixtures("mock_client")
async def test_reconfigure_rejects_a_different_hub(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_read_hub_id: AsyncMock,
) -> None:
    """Test an address belonging to another hub can't hijack the entry."""
    await setup_integration(hass, mock_config_entry, [])

    result = await mock_config_entry.start_reconfigure_flow(hass)

    mock_read_hub_id.return_value = "some-other-hub"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: NEW_HOST}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_hub"
    assert mock_config_entry.data[CONF_HOST] == TEST_HOST


@pytest.mark.usefixtures("mock_client", "mock_read_hub_id")
async def test_dhcp_follows_the_hub_to_a_new_address(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test a new DHCP lease for the paired hub updates the stored host."""
    await setup_integration(hass, mock_config_entry, [])

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP}, data=DHCP_DISCOVERY
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert mock_config_entry.data[CONF_HOST] == NEW_HOST


@pytest.mark.usefixtures("mock_read_hub_id")
async def test_dhcp_ignores_an_unpaired_hub(hass: HomeAssistant) -> None:
    """Test a hub that was never paired isn't set up behind the user's back."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP}, data=DHCP_DISCOVERY
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_paired"


async def test_dhcp_ignores_an_unreachable_address(
    hass: HomeAssistant,
    mock_read_hub_id: AsyncMock,
) -> None:
    """Test a device that can't be identified never rewrites a paired entry."""
    mock_read_hub_id.side_effect = HubUnreachableError

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP}, data=DHCP_DISCOVERY
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


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
