"""DataUpdateCoordinator for DeLonghi Coffee Link."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .ayla_client import AylaDevice, DelonghiAylaClient
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class DelonghiCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Periodically fetch device properties from Ayla cloud."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: DelonghiAylaClient,
        device: AylaDevice,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{device.dsn}",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.client = client
        self.device = device

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch all properties + refresh device meta."""
        try:
            props = await self.client.async_get_properties(self.device.dsn)
            # Refresh device connection status
            devices = await self.client.async_get_devices()
            for d in devices:
                if d.dsn == self.device.dsn:
                    self.device = d
                    break
            return props
        except Exception as err:
            raise UpdateFailed(f"Error fetching Delonghi data: {err}") from err

    async def async_send_beverage(self, beverage_id: int, action: int) -> None:
        """Build + send a beverage command via data_request property."""
        from .command_builder import build_and_encode

        value = build_and_encode(beverage_id, action)
        _LOGGER.info(
            "Sending beverage cmd: bev_id=0x%02x action=%d value=%s",
            beverage_id,
            action,
            value,
        )
        await self.client.async_set_property_value(self.device.dsn, "data_request", value)
        await self.async_request_refresh()

    async def async_send_wake(self) -> None:
        """Send the WAKE / power-on command to bring the machine out of standby."""
        from .command_builder import build_wake_encoded

        value = build_wake_encoded()
        _LOGGER.info("Sending WAKE cmd: %s", value)
        await self.client.async_set_property_value(self.device.dsn, "data_request", value)
        await self.async_request_refresh()
