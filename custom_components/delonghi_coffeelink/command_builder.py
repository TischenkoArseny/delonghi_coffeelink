"""Binary command builder for DeLonghi Coffee Link (Ayla transport)."""
from __future__ import annotations

import base64
import binascii
import time

from .const import (
    BEVERAGES,
    CMD_FAMILY_BREW,
    CMD_FAMILY_POWER,
    CMD_LENGTH,
    CMD_PREFIX,
    CMD_RESPONSE_PREFIX,
    CRC_INIT,
    CRC_POLY,
    DEFAULT_RECIPE_PARAMS,
    POWER_WAKE_PARAMS,
)

_BEV_NAMES = {bev_id: display for bev_id, _key, display, _icon in BEVERAGES}
_ACTION_NAMES = {0x01: "start", 0x02: "stop"}


def crc16_aug_ccitt(data: bytes) -> int:
    """CRC16 AUG-CCITT: poly 0x1021, init 0x1D0F, BE, no reflection."""
    crc = CRC_INIT
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ CRC_POLY
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc


def build_beverage_command(
    beverage_id: int,
    action: int,
    params: bytes = DEFAULT_RECIPE_PARAMS,
    timestamp: int | None = None,
) -> bytes:
    """
    Build a raw binary beverage start/stop command.

    beverage_id: 1 byte (see BEVERAGES in const.py)
    action: 0x01 (start) or 0x02 (stop)
    params: 6 bytes of recipe parameters
    timestamp: Unix seconds; None = now
    """
    if timestamp is None:
        timestamp = int(time.time())
    header = bytes(
        [CMD_PREFIX, CMD_LENGTH, CMD_FAMILY_BREW[0], CMD_FAMILY_BREW[1], beverage_id, action]
    ) + params
    if len(header) != 12:
        raise ValueError(f"Header must be 12 bytes, got {len(header)}")
    crc = crc16_aug_ccitt(header)
    return header + crc.to_bytes(2, "big") + timestamp.to_bytes(4, "big")


def encode_command(command_bytes: bytes) -> str:
    """Base64-encode command for transmission via Ayla data_request property."""
    return base64.b64encode(command_bytes).decode("ascii")


def build_and_encode(beverage_id: int, action: int, params: bytes = DEFAULT_RECIPE_PARAMS) -> str:
    """Shortcut: build command + base64 encode for Ayla."""
    return encode_command(build_beverage_command(beverage_id, action, params))


def build_wake_command(timestamp: int | None = None) -> bytes:
    """
    Build the WAKE / power-on command (different family 0x84 0x0f).

    Captured from app: 0d 07 84 0f 02 01 <crc16> <timestamp>
    Length byte = 0x07, payload before CRC = 6 bytes.
    """
    if timestamp is None:
        timestamp = int(time.time())
    header = bytes([CMD_PREFIX, 0x07, CMD_FAMILY_POWER[0], CMD_FAMILY_POWER[1]]) + POWER_WAKE_PARAMS
    if len(header) != 6:
        raise ValueError(f"Wake header must be 6 bytes, got {len(header)}")
    crc = crc16_aug_ccitt(header)
    return header + crc.to_bytes(2, "big") + timestamp.to_bytes(4, "big")


def build_wake_encoded() -> str:
    """Shortcut: build wake command + base64 encode."""
    return encode_command(build_wake_command())


# ---------------------------------------------------------------------------
# Decoding / inspection (used by the diagnostic command sniffer)
#
# These functions never raise on bad input - they return a dict describing what
# could be parsed, so a value captured live from the cloud (possibly written by
# the official Coffee Link app, possibly malformed) can always be logged.
# ---------------------------------------------------------------------------


def decode_command(value_b64: str) -> dict:
    """Decode a base64 command/response payload into a human-readable dict.

    Recognises the two app->machine frame families this integration emits
    (brew ``0x83 0xf0`` and power/wake ``0x84 0x0f``) and machine->app
    responses (prefix ``0xd0``). Unknown shapes still get a hex dump.
    """
    out: dict = {"raw_b64": value_b64}
    if not isinstance(value_b64, str) or not value_b64:
        out["error"] = "value is not a non-empty string"
        return out
    try:
        raw = base64.b64decode(value_b64, validate=True)
    except (ValueError, binascii.Error):
        out["error"] = "not valid base64"
        return out

    out["hex"] = raw.hex(" ")
    out["length"] = len(raw)
    if len(raw) >= 4:
        out["prefix"] = f"0x{raw[0]:02x}"
        out["length_byte"] = f"0x{raw[1]:02x}"
        out["family"] = raw[2:4].hex(" ")
    family = bytes(raw[2:4]) if len(raw) >= 4 else b""

    if family == CMD_FAMILY_BREW and len(raw) >= 18:
        out["type"] = "beverage"
        out["beverage_id"] = f"0x{raw[4]:02x}"
        out["beverage_name"] = _BEV_NAMES.get(raw[4], "unknown")
        out["action"] = raw[5]
        out["action_name"] = _ACTION_NAMES.get(raw[5], "?")
        out["params"] = raw[6:12].hex(" ")
        out["crc"] = raw[12:14].hex(" ")
        out["crc_valid"] = crc16_aug_ccitt(raw[0:12]) == int.from_bytes(raw[12:14], "big")
        out["timestamp"] = int.from_bytes(raw[14:18], "big")
        # header + crc, without the 4 trailing timestamp bytes (which change every
        # second) - this is the part to compare between app and integration.
        out["structural_b64"] = base64.b64encode(raw[0:14]).decode("ascii")
    elif family == CMD_FAMILY_POWER and len(raw) >= 12:
        out["type"] = "power"
        out["params"] = raw[4:6].hex(" ")
        out["crc"] = raw[6:8].hex(" ")
        out["crc_valid"] = crc16_aug_ccitt(raw[0:6]) == int.from_bytes(raw[6:8], "big")
        out["timestamp"] = int.from_bytes(raw[8:12], "big")
        out["structural_b64"] = base64.b64encode(raw[0:8]).decode("ascii")
    elif len(raw) >= 1 and raw[0] == CMD_RESPONSE_PREFIX:
        out["type"] = "machine_response"
    else:
        out["type"] = "unknown"
    return out


def builder_structural_b64(decoded: dict) -> str | None:
    """Return the non-timestamp prefix THIS integration would emit for the same
    command, so a captured frame can be compared structurally (payload + CRC)
    while ignoring the per-second timestamp. ``None`` if not comparable.
    """
    kind = decoded.get("type")
    if kind == "beverage":
        try:
            bev_id = int(decoded["beverage_id"], 16)
        except (KeyError, ValueError):
            return None
        cmd = build_beverage_command(bev_id, decoded.get("action", 0x01))
        return base64.b64encode(cmd[0:14]).decode("ascii")
    if kind == "power":
        return base64.b64encode(build_wake_command()[0:8]).decode("ascii")
    return None


def summarize_decoded(decoded: dict) -> str:
    """One-line human summary for logs."""
    if "error" in decoded:
        return f"undecodable ({decoded['error']}): {decoded.get('raw_b64')}"
    kind = decoded.get("type")
    match = decoded.get("matches_integration")
    match_str = "" if match is None else f" matches_integration={match}"
    if kind == "beverage":
        return (
            f"beverage {decoded.get('beverage_name')} id={decoded.get('beverage_id')} "
            f"action={decoded.get('action_name')} params=[{decoded.get('params')}] "
            f"crc_valid={decoded.get('crc_valid')}{match_str}"
        )
    if kind == "power":
        return (
            f"power/wake params=[{decoded.get('params')}] "
            f"crc_valid={decoded.get('crc_valid')}{match_str}"
        )
    return f"{kind} hex=[{decoded.get('hex')}]"
