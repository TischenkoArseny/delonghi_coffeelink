# Changelog

All notable changes to this project will be documented in this file.

## [0.2.0] - 2026-04-22

### Added
- `Wake` button to bring the machine out of standby (cmd family `0x84 0x0f`).

## [0.1.0] - 2026-04-22

Initial release.

### Added
- Cloud authentication chain: Gigya (SAP Customer Data Cloud) login + HMAC-SHA1 signed JWT + Ayla Networks SSO.
- 22 beverage buttons (Espresso, Cappuccino, Latte Macchiato, Hot Water, Tea, etc.) + generic Stop.
- 16 sensors for lifetime counters, descale status, water hardness, connection status, software version.
- Services: `start_beverage`, `stop_beverage`, `send_raw_command` (advanced).
- English + French translations for the config flow.

### Technical
- Reverse-engineered command format: `0x0d <len> <family> <action> <params> <crc16> <unix_ts>`.
- CRC16 AUG-CCITT (poly `0x1021`, init `0x1D0F`) over pre-CRC bytes, big-endian.
- Beverage family: `0x83 0xf0`. Power/wake family: `0x84 0x0f`.
- Tested on PrimaDonna Soul ECAM 612.55.SB.

### Known limitations
- Coffee Link mobile app must be closed for the machine to accept cloud-routed commands (LAN mode takes priority with a 30s keep-alive).
- Default recipe parameters are the captured Hot Water values; some beverages may need per-drink tuned params.
- No power-off command captured yet.
