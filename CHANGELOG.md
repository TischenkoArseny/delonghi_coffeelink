# Changelog

All notable changes to this project will be documented in this file.

## [0.3.3] - 2026-06-05

### Fixed
- Command sniffer: Ayla returns string datapoints wrapped in whitespace (a real captured app wake came back as `...\n`). The trailing newline made `base64.b64decode(validate=True)` reject the frame, so the `Last Captured Command` sensor showed only `origin`/`captured_at` with no decoded fields, and could mis-attribute the integration's own echoed command as `app`. Values are now normalised (whitespace stripped) before attribution and decoding.

## [0.3.2] - 2026-06-05

### Added
- **Command sniffer (diagnostic).** The coordinator now watches the binary command channel (`data_request` / `app_data_request`) and the response channel each poll. When a command is written by the **official Coffee Link app** (i.e. one this integration did not send), its exact bytes are captured, decoded, and logged (`CAPTURED app->machine command ...`).
- New diagnostic sensor **Last Captured Command**: its state is the captured base64 frame; attributes decode it (family, beverage, action, recipe params, CRC validity, timestamp) and include **`matches_integration`** - whether the app's structural bytes (payload + CRC, timestamp ignored) equal what this integration would generate. This is the ground-truth needed to debug models where commands return HTTP 200 but the machine stays silent (e.g. Eletta Explore).
- `decode_command` / `summarize_decoded` helpers in `command_builder` (pure, fully unit-tested).

### Notes
- Passive feature: no extra API calls (properties are already polled), and no change to command encoding - safe for the reference PrimaDonna Soul.

## [0.3.1] - 2026-06-03

### Fixed
- Sensors stuck on `unknown` for Eletta Explore (`oem_model=DL-striker-cb`): counter property names now resolve from a per-model candidate list (e.g. `d700_tot_bev_b` on Soul vs `d701_tot_bev_b` on Eletta), same approach as the v0.3.0 command-property detection.
- `Last Connected` now resolves `device_connected` / `app_device_connected` via the candidate list (the previous one-off fallback is removed).

### Changed
- Counter/info sensors whose property is absent on the device are no longer created, instead of appearing permanently `unknown` (e.g. Total Milk Drinks / Total Water / Descale Status on Eletta).
- Counter parsing is more robust (handles int and numeric strings); when a counter value is present but not a plain integer, the raw value and Ayla `base_type` are logged once so unknown encodings can be reported and supported.

## [0.3.0] - 2026-05-21

### Added
- Auto-detection of the binary command property at first refresh (`data_request` on PrimaDonna Soul / `app_data_request` on Eletta Explore), fixing `HTTP 404` on `set_property` for non-Soul models.

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
