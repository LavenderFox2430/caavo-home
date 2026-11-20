# Caavo Home for Home Assistant

![Caavo Home](custom_components/caavo_home/brand/icon.png)

[![Validate](https://github.com/LavenderFox2430/caavo-home/actions/workflows/validate.yml/badge.svg)](https://github.com/LavenderFox2430/caavo-home/actions/workflows/validate.yml)

Local control of a Caavo running the replacement **Caavo Home launcher with API v1**. This is an independent custom integration; it does not connect to the original Caavo cloud service.

Version **0.2.0**. Requires Home Assistant Core **2026.11.2 or later**. Adds custom IR command buttons, macro buttons, activity start buttons and a theater activity selector, plus the device's WebUI link, IP/MAC sensors and theater job status. Theater controls require Caavo Home 2.2 with companion 1.7 or later. Older API v1 devices retain their existing controls. MAC information is available when the companion includes network metadata; absent metadata does not block the integration.

## Install through Marketplace / HACS

Repository: **[LavenderFox2430/caavo-home](https://github.com/LavenderFox2430/caavo-home)**.

This integration requires a Caavo already running the replacement **Caavo Home launcher with local API v1**. Installing this integration does not install the launcher or modify stock Caavo firmware. The original Caavo cloud API is not supported.

<!-- ha-marketplace:exclude-start -->
For the supported **Home Assistant Core 2026.11.2+** releases:

1. Open **Settings → Marketplace → Add from link**.
2. Enter `https://github.com/LavenderFox2430/caavo-home` and install **Caavo Home**. Connect GitHub if prompted.
3. Restart Home Assistant.
4. Open **Settings → Devices & services** and configure the discovered device, or choose **Add integration → Caavo Home**.
5. Enter the API key from the Caavo's on-TV **Integration settings**. Manual setup also asks for its private IPv4 address.

This repository uses the standard HACS **Integration** layout. Home Assistant 2026.11+ uses the built-in Marketplace in place of standalone HACS; older Home Assistant versions are not supported by this release. See the [official repository and version requirements](https://contributors.home-assistant.io/marketplace/reference/repository-structure/).

The repository can be added by URL; it is not listed in the default catalog.

## Install the ZIP manually

1. Download `caavo_home-0.2.0.zip` from the [0.2.0 release](https://github.com/LavenderFox2430/caavo-home/releases/tag/v0.2.0), or build it with `python tools/build_release.py`. A SHA-256 checksum is provided with the release.
2. Extract it into your Home Assistant **configuration directory**, usually `/config`. The resulting file must be `/config/custom_components/caavo_home/manifest.json`. Avoid an extra nested `caavo_home-0.2.0` directory. Back up an existing `custom_components/caavo_home` folder outside `custom_components` before replacing it.
3. Restart Home Assistant.
4. Open **Settings → Devices & services**. Configure the discovered **Caavo Home** device, or choose **Add integration → Caavo Home**.
5. Enter the API key shown in the Caavo's on-TV **Integration settings**. Manual setup also asks for the unit's private IPv4 address, without `http://`, a port, or a path.
<!-- ha-marketplace:exclude-end -->

The API runs at `http://<Caavo IPv4>:8090/api/v1`. Each unit has its own stable ID and API key. Nothing in this integration assumes a particular unit, address, SSH account, or token.

**Upgrading from 0.1.x:** overwrite the files in the existing `custom_components/caavo_home` folder with this ZIP, verify that its `manifest.json` says `0.2.0`, and fully restart Home Assistant. A browser refresh or integration reload alone may keep an old module cached. Existing entry IDs, device IDs, entity IDs, and saved credentials are unchanged; there is no need to delete an existing integration entry.

Removing this integration only removes its Home Assistant connection. It does not change the Caavo's power, input, configuration, or API key.

## Discovery and network access

The launcher advertises `_caavo-home._tcp.local.` on port 8090, with TXT properties `id`, `api=1`, `path=/api/v1`, `auth=bearer`, `model`, and `version`. Android may advertise both IPv4 and IPv6; the integration selects a private IPv4 address because API v1 serves IPv4. Home Assistant must be able to receive mDNS advertisements and reach TCP 8090. Container/VLAN installations may need their usual mDNS and LAN routing configuration; manual setup works without discovery.

Discovery first reads unauthenticated `/info` and compares its ID with the advertisement. An existing entry's address changes only when the actual ID matches. Every authenticated request also checks `/info` first, so an address accidentally reassigned to another Caavo does not receive the saved key. This ID check is not cryptographic authentication.

**The API uses ordinary HTTP on a trusted LAN. Its bearer key and commands are not encrypted in transit. Do not expose port 8090 to the Internet.** The integration accepts RFC1918 private IPv4 addresses and IPv4 link-local addresses. It does not send credentials in URLs, follow redirects, discover SSH credentials, or use cloud accounts.

## Entities

The device info card's native **Visit / WebUI** link opens `/automation` on a
theater-capable Caavo, or the normal remote on older companions. Home Assistant
controls the label and placement of this link. The MAC is also registered as a
network connection; IP and MAC diagnostic entities can be placed on dashboards.
No API key is included in a link. Theater asks for the owner key separately.

### Theater controls

Create devices, buttons, macros and activities in Caavo's Theater editor first.
The integration discovers them at its next successful poll (normally ten seconds):

| Control | Home Assistant entity/action |
|---|---|
| Custom IR button | `button`, named with its device and command |
| Saved macro | `button`, named `Macro · …` |
| Activity start | `button`, named `Start · …` |
| Activity selection | `select` named Theater activity; Off runs the active activity's stop macro |
| End activity | `button` named End theater activity |
| Stop remaining job steps | `button` named Cancel theater job |
| Job progress | Theater job diagnostic sensor, with request ID and completed/total steps |

Use the standard `button.press` and `select.select_option` actions in dashboard
cards, scripts and automations. For example, replace the entity ID with the macro
button created for your library:

```yaml
actions:
  - action: button.press
    target:
      entity_id: button.caavo_home_macro_movie_night
```

Macro delays, repetitions and conditions execute on Caavo, so Home Assistant does
not need to send each step. A successful press means the job was accepted; inspect
Theater job for completion. Only one job runs at a time. Cancellation skips remaining
steps and cannot undo transmitted commands. A lost response triggers one receipt
lookup using the original request ID, never another run request. If the result is
still uncertain, inspect that ID in Theater before pressing again.

Activity options include their stable IDs to distinguish identical names. Activity
state is **assumed**, not equipment feedback. Re-selecting the active activity uses
Caavo's no-op protection. Switching activities runs old-stop then new-start macros.

New library items appear automatically. Renames keep entity IDs and user-assigned
names. Deleted controls become unavailable; their registry entries are retained so
dashboard references are not silently erased. Removing or unloading this integration
never deletes the onboard library. Raw IR timings, macro bodies and variable values
are not copied into Home Assistant entity state or diagnostic downloads.

### Existing controls

| Entity | Behavior |
| --- | --- |
| HDMI input select | Selects inputs 1–4 using their current owner-assigned names. Every label includes its port to distinguish duplicate names. |
| Media player | Shows Caavo on/standby state and selected HDMI input; supports source selection, Caavo wake/standby, and volume steps. |
| Remote | Sends explicit supported key clicks and user-requested sequences. Wake/standby controls the Caavo. |
| Wake Caavo / Caavo standby / Restart Caavo | Explicit device power actions. Restart sends the API's required confirmation. |
| Open launcher | Presses the Caavo/Home button. |
| Play/pause toggle / Mute toggle | Sends a toggle; no playback or mute state is invented. |
| Hardware backend ready | Diagnostic status even when hardware-control entities are unavailable. |
| Caavo power state | `on`, `off`, `transitioning`, or `unknown`. |
| CPU temperature | Read-only average of CPU0–CPU3, reported in °C with measurement history. Unavailable when the API omits the optional reading. |
| HDMI 1–4 signal | Optional diagnostics, disabled by default in the entity registry. |

**Caavo standby is box/HDMI-system standby. It does not promise to turn off every connected TV, AVR, or source.** Source switching opens the launcher's HDMI viewing screen. The API does not provide content metadata, a reliable playback state, absolute volume, or mute state, so those capabilities are not advertised. Volume, playback, and source commands depend on the launcher's configured device-control support.

The integration polls every 10 seconds. A reachable API with `available=false` keeps the diagnostic backend status visible while hardware controls are unavailable. There is no event subscription in API v1.

The CPU temperature entity reads the optional `temperatureCelsius` field from the same `/state` response, with no extra requests. Older API v1 devices remain compatible: a missing, null, or invalid temperature makes only this sensor unavailable. A failed poll also marks it unavailable rather than presenting the last reading as current. Home Assistant may display the reading in your configured temperature unit.

## Remote commands

`up`, `down`, `left`, `right`, `select`, `back`, `menu`, `caavo`, `home`, `volume_up`, `volume_down`, `mute`, `play_pause`, `rewind`, `forward`, `page_up`, `page_down`, `keypad`, and `num_0` through `num_9`.

`caavo` opens the replacement launcher. `home` sends Home to the selected HDMI source. The remote entity's `supported_commands` attribute lists the intersection supported by this integration and the current launcher.

Example action; replace the entity ID with yours:

```yaml
action: remote.send_command
target:
  entity_id: remote.caavo_home_remote
data:
  command:
    - down
    - select
  num_repeats: 1
  delay_secs: 0.2
```

Held-key requests (`hold_secs`) are rejected. Explicit repetitions are limited to 20 and sequences to 100 keys. All mutations share one client lock and a minimum 120 ms start interval, allowing margin above the API's 90 ms limit. GET requests time out after 10 seconds and POST requests after 25 seconds. **Failed or uncertain mutations are never automatically retried.** A sequence stops at its first failure; check the device before repeating an action that timed out.

## Change the address or API key

Use **Settings → Devices & services → Caavo Home → Reconfigure**. A blank new-key field retains the existing key. A rejected key starts Home Assistant's reauthentication flow. Both paths verify the original unit's ID before sending credentials to the address. To connect a different Caavo, add a separate integration entry.

## Diagnostics

Home Assistant diagnostics contain only whitelisted protocol/availability fields. The API key, IPv4 address, stable ID, and owner names are redacted or omitted. Raw response bodies and authentication headers are not logged by the client.

## Repository and releases

The public repository contains this integration, its tests, original project icons, and packaging tools under the included MIT license. Device credentials, backups, firmware, and raw runtime captures are excluded. Report integration issues at [GitHub Issues](https://github.com/LavenderFox2430/caavo-home/issues); redact API keys, unit IDs, addresses, and owner names from reports.

Marketplace / HACS installs from `custom_components/caavo_home` in the versioned repository. The manual ZIP is shaped for extraction into `/config` and is deliberately not configured as a HACS `zip_release`.

For a maintainer release:

1. Update the manifest version, changelog, and version-specific installation links.
2. Run the validation commands below and review the diff for private data.
3. Push the reviewed source and wait for tests, Hassfest, and HACS validation.
4. Create a matching `vX.Y.Z` GitHub release and attach the built ZIP and checksum. The build tool creates local files only; it never publishes.

## Development and validation

```text
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python -m ruff check .
python -m ruff format --check .
python tools/build_release.py
```

Tests use mocked asynchronous HTTP and minimal Home Assistant API doubles. They verify fragmented/oversized responses, identity checks before token transmission, discovery address changes, reconfigure/reauth, timeouts/no retries, serialization/rate spacing, duplicate input labels, availability, and stopped command sequences. They do not exercise real Home Assistant's entity registry, frontend, mDNS transport, or a physical Caavo.

Version 0.2.0 passes **59 host tests**, including theater discovery, stable IDs,
renames/removal, activity selection, cancellation, malformed libraries, partial
failures, metadata matching and receipt lookup without retransmission. Ruff and
the exact Core 2026.11.2 import/helper audit also pass. After installation and an
owner-performed restart of Core 2026.11.2, its saved registry contains the six new
base theater/network entities and the Theater configuration URL; the firmware
version also follows a live companion update. No Caavo errors appeared in the
available startup log. The actual HTTP client reads the physical device's theater
library successfully. That library was empty during this check, so custom library
entity discovery and dashboard-triggered IR remain covered by host tests rather
than claimed as live appliance verification.

The original 38 mocked tests passed, including optional temperature values and compatibility with older API responses, plus construction and validation of user, discovery confirmation, reconfigure, and reauthentication forms with the real `probatio==0.13.0` library used by Core 2026.11.2. The Home Assistant framework is mocked, with the removed legacy Zeroconf export deliberately absent. A release regression test also verifies reproducible builds from a clean checkout with no private evidence files. GitHub Actions runs these tests, Ruff, Hassfest, and HACS validation.

Separately, on November 19, 2026, the unchanged `CaavoClient` using real `aiohttp` successfully read `/info`, `/capabilities`, and `/state` from a physical Caavo. Its authenticated API v1 response reported an available backend, the original launcher disabled, four inputs, power on, and 28 remote keys. This verifies real HTTP transport and response parsing; it does not establish Home Assistant runtime behavior or successful physical power, input, and remote-key commands. Historical runtime evidence remains in the maintainer's private workspace and is not bundled in public releases.

Runtime imports, relevant form/coordinator helper signatures, and entity feature constants were checked against exact [Core 2026.11.2 source](https://github.com/home-assistant/core/tree/2026.11.2/homeassistant), using `tools/audit_ha_imports.py`. `ZeroconfServiceInfo` now comes from `helpers.service_info.zeroconf` only during type checking; postponed annotations require no discovery-type import at runtime. These static checks do not replace validation in a running Home Assistant instance.

Companion 1.4's live authenticated temperature API and `state.temperatureCelsius` were also verified on November 19, 2026: the reported value matched the mean of all four CPU sensor readings. This is API-level verification; display and history of the new temperature entity inside Home Assistant still need runtime confirmation.

On Windows, sandboxed asyncio may require local IPC permission for its event loop even though these tests make no real network requests. Runtime Home Assistant validation belongs in a supported Home Assistant environment.
