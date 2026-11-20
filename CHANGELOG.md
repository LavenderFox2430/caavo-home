# Changelog

## 0.2.0

- Discover custom IR commands, onboard macros and activity starts as button entities.
- Add a theater activity selector, end-activity button, cancel-job button and job status sensor.
- Refresh library controls automatically; keep stable IDs across renames and make removed controls unavailable.
- Add the native device-page WebUI link to Theater, plus IP/MAC diagnostics and reported MAC device connections.
- Refresh device software version and URL metadata, preserving existing integration identities and user names.
- Read durable job receipts after an uncertain run response without retransmitting commands.
- Keep older API v1 controls usable when theater support or network metadata is absent.
- Validate imports and registry calls against Core 2026.11.2; test library changes, partial failures, duplicate labels and timeout handling.

## 0.1.2

First public release, for Home Assistant Core 2026.11.2 or later.

- Local Caavo Home API v1 integration with discovery, reauthentication, and reconfiguration.
- HDMI input selection, media player, remote, power actions, and diagnostic entities.
- Optional CPU temperature sensor, compatible with API responses that omit temperature.
- Current configuration-flow imports and form schemas, correcting the 0.1.0 setup failure.
- Marketplace / HACS repository metadata, project icons, and GitHub validation workflows.
- Reproducible manual ZIP builds from a clean checkout, without private device captures.

Existing 0.1.2 installations keep the same runtime behavior and entity identifiers.
Host tests and historical real HTTP-client reads are documented in the README.
Setup and entity behavior in a running Home Assistant instance remain unverified.
