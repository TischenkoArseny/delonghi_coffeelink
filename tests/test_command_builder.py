"""Unit tests for the pure command builder / decoder logic.

These tests load only the dependency-free modules (`const`, `command_builder`)
directly, without importing the package `__init__` (which pulls in Home
Assistant). That keeps them runnable with just `pytest` installed.

Payloads below are REAL frames captured from the GitHub issue threads (logged as
"Sending ... value=" by the integration itself), so they are known-good and let
us assert the decoder against ground truth.
"""
from __future__ import annotations

import base64
import importlib.util
import sys
import types
from pathlib import Path

import pytest

PKG_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "delonghi_coffeelink"


def _load(modname: str, filename: str):
    full = f"delonghi_coffeelink.{modname}"
    spec = importlib.util.spec_from_file_location(full, PKG_DIR / filename)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod


# Stub the parent package so the modules' relative imports resolve, WITHOUT
# executing the real __init__.py (which imports homeassistant/voluptuous).
if "delonghi_coffeelink" not in sys.modules:
    _pkg = types.ModuleType("delonghi_coffeelink")
    _pkg.__path__ = [str(PKG_DIR)]
    sys.modules["delonghi_coffeelink"] = _pkg

const = _load("const", "const.py")
cb = _load("command_builder", "command_builder.py")


# --- CRC -------------------------------------------------------------------

def test_crc16_aug_ccitt_known_vector():
    # Hot Water header (12 bytes) -> CRC 0x8124 (from captured frame).
    header = bytes.fromhex("0d0d83f010010f00fa1b0106")
    assert cb.crc16_aug_ccitt(header) == 0x8124


# --- build_beverage_command -----------------------------------------------

def test_build_beverage_command_structure():
    cmd = cb.build_beverage_command(0x10, const.ACTION_START, timestamp=0x6a20b3db)
    assert cmd.hex(" ") == "0d 0d 83 f0 10 01 0f 00 fa 1b 01 06 81 24 6a 20 b3 db"


def test_build_beverage_command_rejects_bad_param_length():
    with pytest.raises(ValueError):
        cb.build_beverage_command(0x01, 0x01, params=b"\x00")


def test_build_wake_command_structure():
    cmd = cb.build_wake_command(timestamp=0x6a1744a2)
    assert cmd.hex(" ") == "0d 07 84 0f 02 01 55 12 6a 17 44 a2"


# --- decode_command: beverage ---------------------------------------------

@pytest.mark.parametrize(
    "b64, bev_id, bev_name, params",
    [
        ("DQ2D8BABDwD6GwEGgSRqILPb", "0x10", "Hot Water", "0f 00 fa 1b 01 06"),
        ("DQ2D8AEBDwD6GwEG+0NqILPw", "0x01", "Espresso", "0f 00 fa 1b 01 06"),
        ("DQ2D8BYBDwD6GwEGAe9qIcfY", "0x16", "Tea", "0f 00 fa 1b 01 06"),
    ],
)
def test_decode_beverage_real_frames(b64, bev_id, bev_name, params):
    d = cb.decode_command(b64)
    assert d["type"] == "beverage"
    assert d["beverage_id"] == bev_id
    assert d["beverage_name"] == bev_name
    assert d["action"] == 1
    assert d["action_name"] == "start"
    assert d["params"] == params
    assert d["crc_valid"] is True
    assert "timestamp" in d


def test_decode_power_real_frame():
    d = cb.decode_command("DQeEDwIBVRJqF0Si")
    assert d["type"] == "power"
    assert d["family"] == "84 0f"
    assert d["params"] == "02 01"
    assert d["crc_valid"] is True
    assert d["timestamp"] == 0x6a1744a2


# --- decode_command: robustness -------------------------------------------

def test_decode_rejects_non_base64():
    d = cb.decode_command("not base64 !!!")
    assert "error" in d and d.get("type") is None


def test_decode_rejects_empty_and_non_string():
    assert "error" in cb.decode_command("")
    assert "error" in cb.decode_command(None)  # type: ignore[arg-type]


def test_decode_unknown_frame_still_hex_dumps():
    d = cb.decode_command(base64.b64encode(b"\x01\x02\x03\x04\x05").decode())
    assert d["type"] == "unknown"
    assert d["hex"] == "01 02 03 04 05"


def test_decode_machine_response_prefix():
    # Response frames start with 0xd0 (machine -> app).
    d = cb.decode_command(base64.b64encode(bytes([0xd0, 0x0d, 0x83, 0xf0, 0x00])).decode())
    assert d["type"] == "machine_response"


# --- structural comparison (the key diagnostic) ----------------------------

def test_builder_structural_matches_for_integration_frame():
    """A frame the integration itself produced must compare equal structurally."""
    d = cb.decode_command("DQ2D8BABDwD6GwEGgSRqILPb")  # hot water, integration-built
    assert cb.builder_structural_b64(d) == d["structural_b64"]


def test_builder_structural_detects_param_difference():
    """If the recipe params differ, the structural prefix must differ - this is
    exactly how an Eletta app capture with different bytes would be flagged."""
    altered = cb.build_beverage_command(0x10, 0x01, params=bytes([0x0f, 0x00, 0xff, 0x1b, 0x01, 0x06]))
    d = cb.decode_command(base64.b64encode(altered).decode())
    assert d["type"] == "beverage"
    assert cb.builder_structural_b64(d) != d["structural_b64"]


def test_builder_structural_none_for_unknown():
    d = cb.decode_command(base64.b64encode(b"\x01\x02\x03\x04").decode())
    assert cb.builder_structural_b64(d) is None


# --- summary string --------------------------------------------------------

def test_summarize_beverage_includes_match_flag():
    d = cb.decode_command("DQ2D8AEBDwD6GwEG+0NqILPw")  # espresso
    d["matches_integration"] = True
    s = cb.summarize_decoded(d)
    assert "Espresso" in s and "matches_integration=True" in s


def test_summarize_handles_error():
    assert "undecodable" in cb.summarize_decoded(cb.decode_command(""))
