"""Binary command builder for DeLonghi Coffee Link (Ayla transport)."""
from __future__ import annotations

import base64
import time

from .const import (
    CMD_FAMILY_BREW,
    CMD_FAMILY_POWER,
    CMD_LENGTH,
    CMD_PREFIX,
    CRC_INIT,
    CRC_POLY,
    DEFAULT_RECIPE_PARAMS,
    POWER_WAKE_PARAMS,
)


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
