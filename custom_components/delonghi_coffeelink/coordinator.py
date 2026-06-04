"""DataUpdateCoordinator for DeLonghi Coffee Link."""
from __future__ import annotations

import logging
from collections import deque
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .ayla_client import AylaDevice, CloudError, DelonghiAylaClient
from .command_builder import (
    builder_structural_b64,
    decode_command,
    summarize_decoded,
)
from .const import (
    COMMAND_PROPERTY_CANDIDATES,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    RESPONSE_PROPERTY_CANDIDATES,
)

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
        self.command_property: str | None = None
        self.response_property: str | None = None
        # --- Command sniffer state ---------------------------------------
        # Values WE wrote, so a command echoed back by the cloud is not
        # mis-attributed to the official app. Bounded; only recent writes matter.
        self._sent_values: deque[str] = deque(maxlen=32)
        # Last datapoint marker seen per channel, to detect *new* writes only.
        self._last_cmd_marker: Any = None
        self._last_resp_marker: Any = None
        # Last decoded frames, surfaced via the diagnostic sensor.
        self.last_captured_command: dict | None = None
        self.last_machine_response: dict | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch all properties + refresh device meta."""
        try:
            props = await self.client.async_get_properties(self.device.dsn)
            if self.command_property is None:
                self.command_property = self._detect_property(
                    props, COMMAND_PROPERTY_CANDIDATES, "command"
                )
            if self.response_property is None:
                # Optional: absence is fine, the sniffer just skips responses.
                self.response_property = self._detect_property(
                    props, RESPONSE_PROPERTY_CANDIDATES, "response", required=False
                )
            self._sniff_app_traffic(props)
            # Refresh device connection status
            devices = await self.client.async_get_devices()
            for d in devices:
                if d.dsn == self.device.dsn:
                    self.device = d
                    break
            return props
        except Exception as err:
            raise UpdateFailed(f"Error fetching Delonghi data: {err}") from err

    def _detect_property(
        self,
        props: dict[str, Any],
        candidates: list[str],
        kind: str,
        required: bool = True,
    ) -> str | None:
        """Pick the right property name for this model from a candidate list.

        Different DeLonghi models expose the binary channels under different
        names (e.g. ``data_request`` on Soul vs ``app_data_request`` on Eletta).
        """
        for candidate in candidates:
            if candidate in props:
                _LOGGER.info(
                    "Using %s property '%s' for dsn=%s (oem_model=%s)",
                    kind,
                    candidate,
                    self.device.dsn,
                    self.device.oem_model,
                )
                return candidate
        if not required:
            _LOGGER.debug(
                "No %s property among %s for dsn=%s (sniffer will skip it)",
                kind,
                candidates,
                self.device.dsn,
            )
            return None
        raise CloudError(
            f"No known {kind} property found for dsn={self.device.dsn} "
            f"(oem_model={self.device.oem_model}). Tried {candidates}. "
            "Please open an issue with debug logs."
        )

    # ------------------------------------------------------------------ #
    # Command sniffer
    #
    # We already fetch every property each poll, so watching the command and
    # response channels is free (no extra API calls). When the value changes to
    # something this integration did not write, it was written by the official
    # Coffee Link app - i.e. the ground-truth bytes we need to compare against.
    # ------------------------------------------------------------------ #

    def _sniff_app_traffic(self, props: dict[str, Any]) -> None:
        # The sniffer is a diagnostic; it must never break the data update and
        # take the device unavailable. Swallow and log any unexpected error.
        try:
            if self.command_property:
                self._capture_channel(props, self.command_property, channel="command")
            if self.response_property:
                self._capture_channel(props, self.response_property, channel="response")
        except Exception:  # noqa: BLE001 - diagnostic must not break polling
            _LOGGER.debug("Command sniffer failed (non-fatal)", exc_info=True)

    def _capture_channel(
        self, props: dict[str, Any], prop_name: str, channel: str
    ) -> None:
        prop = props.get(prop_name)
        if not isinstance(prop, dict):
            return
        value = prop.get("value")
        if not isinstance(value, str) or not value.strip():
            return
        # Ayla wraps string datapoints in whitespace (e.g. a trailing newline);
        # normalise so attribution against _sent_values and the decode succeed.
        value = value.strip()
        # Prefer the cloud's datapoint timestamp to detect a new write (it also
        # catches the app re-sending byte-identical bytes); fall back to value.
        marker = prop.get("data_updated_at", value)
        marker_attr = "_last_cmd_marker" if channel == "command" else "_last_resp_marker"
        previous = getattr(self, marker_attr)
        if marker == previous:
            return  # nothing new this poll
        first_observation = previous is None
        setattr(self, marker_attr, marker)
        if first_observation:
            # The value already present at startup is not a fresh capture.
            return

        decoded = decode_command(value)
        if channel == "command":
            origin = "integration" if value in self._sent_values else "app"
            decoded["origin"] = origin
            decoded["captured_at"] = prop.get("data_updated_at")
            structural = builder_structural_b64(decoded)
            if structural is not None and "structural_b64" in decoded:
                decoded["matches_integration"] = decoded["structural_b64"] == structural
                decoded["builder_structural_b64"] = structural
            self.last_captured_command = decoded
            summary = summarize_decoded(decoded)
            if origin == "app":
                _LOGGER.warning(
                    "CAPTURED app->machine command on %s (dsn=%s): %s | %s",
                    prop_name, self.device.dsn, value, summary,
                )
            else:
                _LOGGER.debug(
                    "Observed own command echoed on %s: %s | %s",
                    prop_name, value, summary,
                )
        else:
            decoded["captured_at"] = prop.get("data_updated_at")
            self.last_machine_response = decoded
            _LOGGER.debug(
                "Machine->app response on %s (dsn=%s): %s | %s",
                prop_name, self.device.dsn, value, summarize_decoded(decoded),
            )

    def _record_sent(self, value: str) -> None:
        """Remember a value we wrote so the sniffer won't flag it as app traffic."""
        self._sent_values.append(value)

    async def async_send_beverage(self, beverage_id: int, action: int) -> None:
        """Build + send a beverage command via the resolved command property."""
        from .command_builder import build_and_encode

        value = build_and_encode(beverage_id, action)
        self._record_sent(value)
        prop = self.command_property or COMMAND_PROPERTY_CANDIDATES[0]
        _LOGGER.info(
            "Sending beverage cmd via %s: bev_id=0x%02x action=%d value=%s",
            prop,
            beverage_id,
            action,
            value,
        )
        await self.client.async_set_property_value(self.device.dsn, prop, value)
        await self.async_request_refresh()

    async def async_send_wake(self) -> None:
        """Send the WAKE / power-on command to bring the machine out of standby."""
        from .command_builder import build_wake_encoded

        value = build_wake_encoded()
        self._record_sent(value)
        prop = self.command_property or COMMAND_PROPERTY_CANDIDATES[0]
        _LOGGER.info("Sending WAKE cmd via %s: %s", prop, value)
        await self.client.async_set_property_value(self.device.dsn, prop, value)
        await self.async_request_refresh()
