# ChurchBoard fork — custom build

This is a personal fork of [wtapper89/ChurchBoard](https://github.com/wtapper89/ChurchBoard), a self-hosted production
dashboard (ProPresenter + Planning Center + Shure wireless status). We're extending it for a specific church AVL setup:
Shure Axient Digital (AD4Q/AD600) instead of QLX-D/ULX-D/SLX-D, Shure PSM1000 packs, a small number of non-networked
Shure GLXD16 guitar packs, and a few custom widgets the base project doesn't have.

Treat this file as the source of truth for project scope and decisions. Update it as phases complete or scope changes.

## Ground rules

- This is a **fork of an actively developed upstream project**. Before making sweeping changes, check
  `git log --oneline -10` against `upstream/main` (remote should already be configured) to see if relevant files have
  moved since this file was last updated.
- **The widget palette is NOT purely frontend.** `app/modules/builtin.py` (the `churchboard-core` module's `widgets`
  list) is the actual source of truth for what appears in the editor — it gets served to the frontend as a module
  catalog, and `applyModulePalette()` in `editor.js` *overwrites* the frontend's hardcoded `paletteCategories` and
  `defaults` with whatever the backend reports. Any new widget type needs an entry in `builtin.py`, not just frontend
  JS, or it will silently never appear no matter how correct the frontend code is. (Lost real time to this once
  already — don't repeat it.)
- **Running from source vs. the installed app use different config locations by default.** Installed/packaged
  builds: `~/.churchboard/churchboard.json`. Running `python run.py` from the repo: `<repo>/data/churchboard.json`.
  Set `CHURCHBOARD_DATA_DIR` to point a dev run at the same config as an installed instance.
- Dev run command: `python run.py` (needs `.venv` activated, `pip install -r requirements.txt` done once).
- Windows dev environment: PowerShell, native Claude Code install, Git for Windows already present.
- macOS is the intended final deployment target; a signed installer isn't set up (no Apple Developer cert), so builds
  are ad-hoc signed — expect a Gatekeeper "unidentified developer" prompt on first launch of any build produced here.

## Status

### Phase 1 — Rich-text Notes widget — ✅ DONE, merged
A `rich_text` widget type ("Notes" in the Content palette category). Editor: small toolbar (bold/italic/underline/
bulleted/numbered list) over a `contenteditable` div, saved as sanitized HTML in `widget.settings.html`. Display:
scrollable div rendering that sanitized HTML. A shared whitelist sanitizer (`sanitizeRichText` in `common.js`) is
applied both on save and on render. Touched: `app/modules/builtin.py` (widget manifest entry — the part that was
initially missed), `app/static/common.js`, `app/static/editor.js`, `app/static/style.css`.

Purely typed-in content, not sourced from Planning Center at all (the existing `sermon_notes` widget already pulls
PCO note fields but strips all formatting down to plain text — deliberately left alone since notes are typed directly
in ChurchBoard here, not in Planning Center).

### Phase 2 — Assignment/pool redesign — ✅ DONE, browser-verified, committed (branch `phase-2-assignments`,
commit `8a4ac02`; not pushed/merged). Built in small increments: 2a manual mic channels, 2b manual people list,
2c person-ID-keyed mapping, 2d combined mic+pack card. Two bug-fix rounds + a card-typography pass along the way.
This scope went through several iterations before landing here — don't rebuild earlier discarded versions of it.

- **Do NOT build a "team opt-in checkbox" pool mechanism.** Earlier discussion explored letting dashboard widgets
  pull from a Planning Center team's full roster regardless of whether they're scheduled for a given service. This
  was explicitly dropped — testing showed the *existing* `team_ids`/`position_keys` filtering on the assignments/mics
  widget (which already lets you opt teams in or leave them out — e.g. Security stays excluded by simply never being
  checked) is good enough as-is. Leave that mechanism untouched.
- **Manual people list** — ✅ DONE (increment 2b). `settings.manual_people` (list of `{id, name, photo}`; photo is a
  `data:image/` URI, 6 MB model cap). `ManualPerson` model in `models.py`; `RuntimeService._manual_people()` returns
  Planning-Center-shaped person dicts tagged `manual: true` with `person_id: ""` and empty positions; folded into
  `state.people` by `_fold_in_manual_roster()`. UI: "Manual people" section (name + photo picker) in the **mics**
  module settings. Independent of Planning Center entirely.
- **Manual mic channels** — ✅ DONE (increment 2a). For the Shure GLXD16 guitar packs, which have no Ethernet/IP
  control at all. Settings-backed list `settings.manual_mic_channels` (top-level, sibling of `position_mic_map`;
  each entry `{id, name}` only). `RuntimeService._manual_mic_cards()` turns each into a card dict tagged
  `manual: true` with `battery_percent/rf/audio: None`, `online: false`, `receiver: "Not networked"`; `refresh()`
  strips any existing `manual` mics from `next_state["mics"]` and re-adds from settings every cycle (idempotent
  across the wireless polling branch). `micCardMarkup`/`micHealth` in `common.js` branch on `mic.manual` → neutral
  grey card, "NOT NETWORKED" status, no meters (`.mic-nonetworked` / `.technical-nonetworked` in place of
  `micMeters` / `.technical-stats`). This flag is distinct from `mic.placeholder` ("person assigned, no receiver
  matched"). UI: "Manual channels" section in the **mics** module settings (`/modules#mics`) — name-only rows.
  Model: `ManualMicChannel` in `models.py`. NOT added to the `mics` module `settings_keys` (that list is
  dict-shaped and drives enable/disable on uninstall — a list there would crash `registry.py`). Not surfaced in
  demo mode (demo state returns early before the merge). Tests: `test_core.py` RuntimeAssignmentTests +
  `test_api.py` round-trip.
- **Person-ID-keyed assignment mapping** — ✅ DONE (increment 2c). `widget.settings.person_assignment_map` =
  `{ personId: {mic: "<channelId>", pack: "<channelId>"} }`, keyed by PCO `person_id` or manual person `id`. NOT
  a global setting and NOT resolved in the runtime — it lives per assignments-widget and is resolved client-side
  in `assignmentEntries` (`common.js`). `position_mic_map` is untouched (still the position-string fallback).
  `ManualPerson` model (`models.py`); `RuntimeService._manual_people()` + `_fold_in_manual_roster()` in
  `runtime.py` (the latter called at BOTH of `refresh()`'s state-publish points — the early ProPresenter publish
  and the final one — so a request served mid-refresh never sees the roster without manual entries).
- **Combined mic+pack card** — ✅ DONE (increment 2d). Editor: the assignments-widget settings has a
  **"Channel assignments"** section — one row per person (scheduled, filtered by team/position, + all manual
  people + any assigned-but-filtered-out stragglers), each with a **Mic** dropdown and a **Pack** dropdown listing
  every channel (networked mics + manual channels). A channel belongs to exactly one (person, slot); the change
  handler clears it from everywhere else first. Card (`micCardMarkup`): `equipment` items carry a `slot`
  (`"mic"`/`"pack"`); the gear area renders labelled lines — `MIC  Blue · Ch 1` / `PACK  P10T-2` (amber
  `.gear-line`, small dim `<b>` label) — pack line only when present. **A person with nothing assigned (no mic,
  no pack) is not rendered on the board at all** (`assignmentEntries` skips person-map entries with no resolved
  equipment). Packs are just channels — for now they're manual channels; Phase 4 feeds networked P10T
  transmitters into the same `state.mics` list and the pack slot lights up automatically. Legacy paths
  (`position_mic_map`, demo, standalone) have no `slot` on their equipment → single unlabelled gear line, unchanged.

### Phase 3 — Shure Axient Digital integration — ✅ code complete + browser-verified, committed on branch
`phase-3-axient` (stacked on `phase-2-assignments`). Built from the official published spec
(www.shure.com/en-US/docs/commandstrings/AD4 — "AD4" is the current URL slug; `pubs.shure.com` redirects there).
Same GET/REP/SAMPLE parser and TCP 2202 as the QLX/ULX/SLX path — Axient just takes a branch.

**Hardware:** 3× AD4Q on the production LAN — Shure Control IPs `10.100.3.217` (AD4Q-1, 4× ADX2),
`.218` (AD4Q-2, 4× ADX2), `.219` (AD4Q-3, 4× ADX1). `10.100.3.216` is an AD600 **Spectrum Manager** (no
per-channel transmitter/audio/RF telemetry — not a receiver for our purposes). The dev box can reach all three
AD4Qs directly on 2202. `tools/axient_probe.py` captures raw command-string traffic (all receivers over one
window, with Shure's dB conversions annotated inline) — that is the calibration instrument.

**Verified against real hardware (2026-09-01, transmitters OFF):** every token/frame the branch relies on is
spelled and shaped exactly as the spec says — `TX_BATT_CHARGE_PERCENT`, `TX_MODEL` (`UNKNOWN` when no TX),
`FD_MODE` (`OFF`), `ANTENNA_STATUS` (`XX` when no TX), the 9-field `SAMPLE x ALL`, `FREQUENCY` as `0604550`.
No-signal floors: RSSI raw ≈ 9–12 (≈ −108…−111 dBm), `audRms` raw `033` (−87 dBFS), `audPeak` raw `005`
(−115 dBFS), `CHAN_QUALITY` `255`. **Still outstanding:** transmitters powered on with real mic levels at
service gain staging — needed only to set the RF (−100..−40 dBm) and audio (−50..0 dBFS) windows in
`axient_meter_percent`. RF range can be had any time someone powers a TX and walks it near→far; the audio
window wants a rehearsal.

- **Model plumbing** (`module-settings.js`): new **"Shure Axient Digital"** `<option>` in the per-mic Receiver
  dropdown (`data-mic-field="manufacturer"` → `shure-axient`). `hydrateModuleMics` maps stored `model:"axient"`
  → that option; `collectWireless` maps it back to `model:"axient"` in `shure.mics`. `shure` settings is a
  free-form `dict[str,Any]` in `models.py` — no schema change needed. Toggle label now reads
  "…/ SLX-D / Axient Digital" (still the one `shure.enabled` switch).
- **Telemetry branch** (`shure.py` `_receiver`): when `receiver_model == "axient"` the per-channel GET set becomes
  `CHAN_NAME`, `TX_BATT_CHARGE_PERCENT`, `FREQUENCY`, `TX_MODEL`, `FD_MODE`, `ANTENNA_STATUS` (vs `BATT_BARS` /
  `TX_TYPE` on the legacy path); `battery_key`/`tx_key` also drive the read-loop break condition. New helpers:
  `battery_charge_percent()` (direct 0–100, 255→None), `format_frequency()` (7-digit kHz string → "578.350 MHz"),
  `axient_meter_percent(value, floor, ceiling)` (0–120 byte, actual dB = value−120, mapped onto 0–100% across a
  dB window), `axient_antenna_label()` ("BR"→"Ant A+B", "XX"→""). `tx_type` stores the raw `TX_MODEL` token
  (`ADX2`, `UNKNOWN`, …) so `transmitter_active()` keeps working unchanged.
- **Axient `SAMPLE … ALL` frame** is 9 fields for a standard channel:
  `qual audBitmap audPeak audRms rfAntStats rfBitmapA rfRssiA rfBitmapB rfRssiB`. We take `rf` = max of the two
  `rfRssi` bytes through a −100..−40 dBm window, `audio` = `audRms` through a −50..0 dBFS window, `antenna` from
  `rfAntStats`. **Those two dB windows are first-guess** — flagged in the `axient_meter_percent` docstring — and
  are the one thing that genuinely needs hardware. Quadversity / FD-C SAMPLE variants (11/13/19 fields) are not
  parsed yet; the `len(parts) >= 9` guard just means rf/audio stay at their last value for those, everything else
  still updates.
- **Card display** (`common.js`): the `technical-meta` line on the mic card now joins
  `[frequency, tx_type, antenna, diversity]` (was just `frequency`+`tx_type`) → e.g.
  `578.350 MHz · ADX2 · Ant A+B · FD-C`. Legacy mics have no `antenna`/`diversity` keys so their line is
  unchanged. This is the only frontend-render change; browser-smoke-tested it plus the settings round-trip.
- Tests: `test_core.py` `ShureTests` (charge %, frequency/antenna label helpers, receiver keeps `model:"axient"`)
  + `ShureStatusTests.test_axient_receiver_reports_charge_percent_frequency_and_diversity` (full fake-socket
  parse); `test_api.py` settings round-trip. Suite is 204 tests, same 7 pre-existing Windows failures.

### Phase 4 — Shure PSM1000 integration — not started
Same command-string protocol family and TCP port as Axient (P10T transmitter is officially documented in the same
GET/SET/REP/SAMPLE convention). Important asymmetry: the P10R bodypack the performer wears is receive-only — no RF
path back to report its own battery level, unlike Axient beltpacks. So this integration gets person-to-pack
*assignment* for free from the Phase 2 mapping, but there's no live pack battery/health telemetry to show, ever —
that's a hardware limitation, not something to keep trying to solve. The P10T transmitter side (frequency, mute,
audio level) does report and can be shown.

### Phase 5 — Custom stage plot widget — not started
No existing analog in the codebase (closest is the mic/pack card list, which isn't spatial). Two-part build: (1) an
editor mode to place mic/monitor/DI icons on a stage outline and save x/y positions, (2) a display mode rendering
those positions with live status overlays using whatever channel data Phases 3–4 produce. Deliberately last — most
novel UI work, most valuable once real assignment/channel data already exists to show.

### Later, no urgency — ProdCom transcript module
Deferred by choice, not blocked by anything above. If/when revisited: MXU's "ProdCom integration" almost certainly
just consumes ProdCom's own local API (documented WebSocket at `/api/v1/ws` and SSE at `/api/v1/transcript/stream`,
optional pre-shared key auth, no auth by default) rather than reimplementing speech-to-text. Plan is to run ProdCom
itself (paid, macOS/iOS only) somewhere in the production network and write a small module that subscribes to its
transcript stream — similar shape/difficulty to the Shure modules, not a from-scratch ASR build.

## Working style notes
- Patches/diffs against upstream drift fast (upstream ChurchBoard is actively developed) — if working from a fresh
  clone or pulling upstream changes, expect to re-verify insertion points in `common.js`/`editor.js` rather than
  assuming line numbers are stable.
- Prefer small, testable increments per phase sub-item over one giant change — this matches how Phase 1 actually went
  (small pieces, verified working end-to-end, then committed) rather than a big-bang rewrite.
