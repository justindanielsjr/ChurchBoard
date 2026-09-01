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

### Phase 4 — Shure PSM1000 integration — ✅ code complete on branch `phase-4-psm1000` (stacked on
`phase-3-axient`). All of 4a–4d done, browser-verified. Only open item: the `PSM_AUDIO_FULL_SCALE`
calibration (see quirk 3), same Sunday-rehearsal capture as the Axient meter windows —
**capture plan + tools are ready: `tools/meter-calibration-capture.md`, `tools/axient_probe.py`,
`tools/psm_probe.py`**. It sets all three placeholder constants (Axient RF window, Axient audio window,
`PSM_AUDIO_FULL_SCALE`) in one pass; after it, three one-line edits in `shure.py` close out Phases 3 & 4.
- **4d** (assignment wiring + card): almost nothing was needed here because 4c already made pack cards
  first-class `state["mics"]` entries with stable ids — `assignmentEntries` resolves `person_assignment_map`'s
  `pack` slot by `mic.id`, so networked packs slot in exactly like manual channels. Changes: `common.js` —
  `micIsActive`/`micHealth`/`micMeters`/`micCardMarkup` get a `mic.pack` branch (packs have
  `battery_percent: null` → without it JS `Number(null)=0` renders every pack "critical" with a bogus BAT
  meter). Pack cards: health = `online?(muted?"low":"healthy"):"critical"`; meters show AUD only; status is
  `MUTED`/`LIVE`/`OFFLINE`; the PACK gear line shows the label + ` · MUTED`; `technical-meta` line gains
  `mic.rf_power` (→ `477.850 MHz · 50 mW`); `itemLabel` drops the `· Ch N` suffix for packs. `editor.js` —
  one token in `channelName` (`mic.pack?" · pack":`) so the Mic/Pack dropdowns label pack channels; the
  dropdowns already iterate `runtimeState.mics` so packs appeared automatically. No new tests (pure render);
  verified with synthetic `micCardMarkup` calls in the browser (combined mic+pack, standalone pack, muted,
  offline) + no console errors on display/editor.
- **4c** (runtime merge): `runtime.py` imports `PSM1000Client`, adds an `"iem"` key to `_last_refresh`, and
  folds `PSM1000Client(config.get("iem", {}))` into the existing shure/sennheiser `asyncio.gather` block
  (`~line 490`): `next_state["mics"] = shure_status + sennheiser_status + psm_status`, with `psm_due` /
  `self._last_refresh["iem"]` and the no-config `elif` guard extended with `and not psm.configured`. Pack cards
  carry `pack: True` (not `manual`), so `_fold_in_manual_roster`'s `manual`-strip leaves them alone. Demo mode
  returns before this block, so packs never show in demo. End-to-end verified against the live racks — 4 pack
  cards land in `/api/runtime` `state["mics"]` with real frequencies, `battery_percent: None`, `online: True`.
  Test: `RuntimeAssignmentTests.test_psm1000_packs_merge_into_live_mic_state`.
- **4b** (settings + UI): `settings.iem = {"enabled": bool, "packs": [ {id,label,host,port,transmitter,side} ]}`
  — an opaque `dict[str,Any]` field on `SettingsUpdate` (mirrors `shure`/`sennheiser`; no per-row pydantic
  model). `module-settings.js`: an `iem.enabled` toggle + a "PSM1000 in-ear packs" section in the mics module
  settings (`moduleIemPackRows`, `moduleIemPackMarkup`, `data-iem-pack-*` / `data-add-iem-pack` /
  `data-delete-iem-pack`, hydrate + `collectWireless` write). Row fields: Label / Rack IP / Transmitter (1|2) /
  Feed (Stereo | Mono L | Mono R). Rows missing label or host are dropped silently on save. `iem` is NOT in the
  `mics` module `settings_keys` dict (list there crashes `registry.py`). Browser-verified round-trip.
  `PSM1000Client` now reads `settings["packs"]` (was `iem_packs`) so `runtime.py` can pass `config.get("iem", {})`
  straight in at 4c.

The P10R bodypack the performer wears is receive-only — no RF path back — so person↔pack is purely the Phase 2
`person_assignment_map` assignment; there is no pack battery/health telemetry, ever. The P10T rack side
(frequency, RF mute, RF power, input audio meter) does report.

**Hardware:** 3× P10T dual-transmitter rack units, Shure Control IPs `10.100.3.220` / `.221` / `.222`, reachable
from the dev box on TCP 2202. Each rack = 2 transmitters (channel index 1/2), each transmitter = stereo RF. Their
8 packs: `IEM **`/`IEM 1` on .220 (both stereo), `IEM 2`–`IEM 5` on .221 (both transmitters run "dual mono" —
different mono mix on L vs R, packs panned to a side), `GTR 2`/`GTR 3` on .222 (stereo).

**Config model** (`settings.iem_packs`, list — one row per physical pack): `{id, label, host, port?, transmitter
(1|2), side ("stereo"|"left"|"right"), rack_name?}`. `label` is the sticker on the bodypack and is what shows in
the assignment dropdown and on the card — the receiver's `CHAN_NAME` does NOT match (racks report `IEM 2/3`,
`GUITAR 2`). A dual-mono transmitter gets two rows (side left / right, each showing its own `AUDIO_IN_LVL_L`/`_R`
meter); a stereo transmitter gets one row (side stereo, showing the louder of L/R).

**`PSM1000Client` (in `shure.py`, 4a):** groups `iem_packs` by host, one connection per rack, per transmitter
GETs `CHAN_NAME`/`FREQUENCY`/`RF_MUTE`/`RF_TX_LVL` + `SET METER_RATE 00100`, parses `AUDIO_IN_LVL_L/_R` reports,
emits one card per configured row via `psm_pack_card()` — `{name: label, pack: True, battery_percent: None,
rf: None, frequency, muted, rf_power, audio, online}`. Helpers `psm_rf_muted` (RF_MUTE 1/0, zero-padded),
`psm_rf_power` (→ "50 mW"), `psm_audio_percent`.

**Protocol quirks learned from the real racks (not in Shure's published page):**
1. A P10T only acts on a **CRLF-terminated** command and ignores run-on strings — unlike the QLX/Axient path,
   which writes bare `< … >`. `PSM1000Client` appends `\r\n` to every write.
2. `AUDIO_TX_MODE` reads `3` (stereo) on **every** transmitter including the dual-mono ones — it's not a mode
   they set, so it's useless for validating `side`. Not queried.
3. `AUDIO_IN_LVL_L/_R` full scale is **undocumented**; live values run ~0–1900. Working model:
   `dBFS = value/50 − 50` (0–2500 → −50..0 dBFS), i.e. `PSM_AUDIO_FULL_SCALE = 2500`. **UNCONFIRMED** — retune
   that one constant from the same Sunday rehearsal capture as the Axient meter windows.
4. Box-level replies (no channel index, e.g. `DEVICE_NAME`) don't match `FRAME`; not relied on.
- Tests: `test_core.py` `PSM1000Tests` + `PSM1000StatusTests` (fake-socket fan-out, stereo + L/R pair). Suite 210.

### Phase 5 — `stage_plot` widget — ✅ code complete (2026-09-01), browser-verified, on branch
`phase-5-stage-plot` (stacked on `phase-4-psm1000`). Commits `703640c` 5a · `fd73f0f` 5b · `49ed3db` 5c ·
`7d1ecf3` 5d. Built exactly to the locked design below. Key files: `builtin.py` (manifest),
`common.js` (`stagePlotEntries` / `stagePlotMarkup` / `stagePlotRfChip` + dispatch), `editor.js`
(`renderStagePlotEditor` + drag handlers + `stagePlotKeyFor`/`setStagePlotPlacement`/`removeStagePlotPlacement`;
`isPositionWidget` extended; `#assignment-grouping-label`/`-hint` now hidden for non-assignments — also fixes
the `people` widget), `editor.html` (`#stage-plot-controls`), `style.css` (`.stage-plot` / `.sp-*`).
Gotcha found in build: a person's position keys must come from `person.positions[].key` (what PCO/demo
people carry), not `person.position_keys`/`position_key` — mirrors `filteredPeople`. Locked design follows:
**Purpose:** musicians finding their spot on stage. Readability first; NOT a live-telemetry surface (that lives
in the mics widget). New widget type `stage_plot`.

**Roster = `filteredPeople(widget.settings, state)`** (the People-widget resolver, in `common.js`), NOT
`assignmentEntries` — because the plot must show a filtered person even if they have no wireless mic, and
`assignmentEntries`'s `peopleByKey` map is last-write-wins so it drops the 2nd person on a shared position.
`filteredPeople` dedupes by identity and returns both people on a shared position. Mic/pack name per person is
looked up from `state.mics` by the same fallback chain `itemLeaderDetails` uses (person_id → name →
position_key).

**Settings:**
- Assignments-widget filter block reused verbatim: `team_ids`, `position_keys`, `position_labels`, manual-people
  selection.
- `background_image` — optional `data:image/` URI (~4 MB UI cap) + `background_aspect` (computed on upload so
  the display letterboxes without waiting for image load). No image → plain 2:1 rectangle.
- `placements` — `{ "<key>": {x, y} }`, x/y as 0–1 fractions of the letterboxed plot area. **Option B keying:**
  `key` is a PCO **position key** (`band::electric-guitar`) for the normal 1-person-per-position case — fully
  service-stable, Jesse inherits Ben's spot. `key` is `"p:<personId>"` for a **per-person override**, used when
  a position has 2+ people (e.g. two "Melody" singers) and one needs their own spot. Resolution per person:
  `placements["p:"+id]` → else `placements[positionKey]` → else the **parking strip**. Multiple people sharing a
  position anchor with no override **fan out** deterministically (sort by id, offset x by `(i-(n-1)/2)*spread`).
- `show_rf` — default off; on adds a small battery/RF chip to each marker.
- Unfilled positions are **hidden** (skip `placeholder`/no-person slots).

**Display:** letterboxed background (image or plain rect) centred in the widget, markers `position:absolute` at
`left:x% top:y%` of the plot box. Marker = circular PCO photo, or an auto-coloured initials disc when no photo
(mirrors `fullNamePlaceholderMarkup`), + name + mic/pack name, stage-readable sizes. Unplaced people flow into a
parking strip along the bottom edge, styled "needs a spot".

**Placement editor (in the widget settings panel, not on the grid):** letterboxed background at editor size,
one draggable puck per resolved person. Drag a solo-position puck → writes `placements[positionKey]`; drag a
puck off a shared anchor → detaches it to `placements["p:"+id]`; drag off-canvas → removes the placement (back
to parking / fan-out). Parking row beneath; drag a puck up onto the canvas to place it. No auto-prune of stale
keys (a returning person keeps their spot); a "Clear all placements" button for a reset.

**Increments (branch `phase-5-stage-plot`, stack on `phase-4-psm1000`):**
- **5a** — manifest in `app/modules/builtin.py` (the entry that gets missed — see ground rules) + frontend
  palette/`defaults` + display renders the filtered roster as markers on a plain letterboxed rect, all parked.
  Verify it appears in the palette and honours the team/position filters.
- **5b** — background image upload + `background_aspect`; display letterboxes it behind the markers.
- **5c** — the drag placement editor; Option B `placements` written/read.
- **5d** — marker readability styling, `show_rf` chip, parking-strip polish.

### Later, no urgency — ProdCom transcript module
Deferred by choice, not blocked by anything above. If/when revisited: MXU's "ProdCom integration" almost certainly
just consumes ProdCom's own local API (documented WebSocket at `/api/v1/ws` and SSE at `/api/v1/transcript/stream`,
optional pre-shared key auth, no auth by default) rather than reimplementing speech-to-text. Plan is to run ProdCom
itself (paid, macOS/iOS only) somewhere in the production network and write a small module that subscribes to its
transcript stream — similar shape/difficulty to the Shure modules, not a from-scratch ASR build.

### Later, no urgency — Shure SBC240 networked charger monitoring
6× SBC240 2-bay networked chargers (12 bays = the 12 Axient channels; whole ADX1/ADX2 transmitters are docked,
not bare batteries). Not on the network yet — the church is considering it. **Only the Axient side** has
networked chargers; the PSM1000 P10R has none, so this does nothing for the IEM battery blind spot. Value is
modest and additive: pre-call charge readiness while packs are docked (the AD4Q shows nothing until a
transmitter is powered *and* linked), time-to-full, and charge-fault detection. Battery health % / cycle count
are already available from the AD4Q for *linked* transmitters (Phase 3), so the charger only adds those for
docked ones. Because whole transmitters are docked, each bay reports the ADX device ID — the same ID the AD4Q
reports when linked — so bay↔channel correlation is possible. Two possible shapes: (a) fold "Charging · 92%"
into the existing mic cards when a channel's transmitter is docked (higher value, needs device-ID matching),
or (b) a standalone 12-tile bay-grid readiness widget (simpler, no correlation). **Do first:** confirm the
SBC240 exposes per-bay battery over the command-strings port (TCP 2202) and not only via WWB's discovery
layer. Priority: after Phase 5.

### Later, no urgency — dedicated Mac display viewer
The deployment is **one always-on Mac** feeding an Ultrix router (→ any auditorium display). Chrome develops a
memory leak over long sessions and stops rendering until relaunched. The web app itself is fine; this is only
about a more stable window to view `/display/<slug>` through. Options, cheapest first:
1. **Scheduled `location.reload()`** in `display.js` (every few hours or a fixed early-morning time), or a
   `launchd` job that relaunches the browser nightly. ~5 lines. Helps regardless of browser. Note: Chrome's
   leak is often GPU/compositor memory that survives a page reload, so this may not be enough on its own.
2. **Switch Chrome → Safari** + the scheduled reload. WebKit's footprint is lighter and signage Macs commonly
   run Safari for this. Likely reduces but won't eliminate the problem; Safari's kiosk lockdown is weak (no
   true `--kiosk`, cmd-W / URL bar / password prompts, aggressive timer throttling if the window is ever
   occluded). Probably good enough for a display nobody touches.
3. **Tiny WKWebView kiosk app** (~100 lines Swift, ~a weekend): bare fullscreen window at a configurable URL,
   prevents display sleep, auto-reconnect with backoff, and a **watchdog** that reloads if the page's poll
   timestamp stops advancing for a few minutes (the thing that saves a live service). No Apple Developer cert
   needed for local use. Near-zero maintenance — it just loads a URL. Rendering is current WebKit, very close
   to Chrome (the display CSS already `-webkit-` prefixes `backdrop-filter`) but wants one visual check.
   Mac-only, one client by design; a second non-Mac display goes back to a browser.
Recommended order: do (1)+(2) after the Phases 2–5 merge; build (3) only if Safari also degrades or the lack of
lockdown bites. Would be "Phase 6".

### Decisions (won't-do, so they don't resurface)
- **NDI + Behringer (X32/M32) modules:** this church uses neither (no NDI; console is Allen & Heath dLive).
  Decision: **uninstall the modules in the setup UI, do NOT strip the source** — stripping a fork of an
  actively developed upstream just buys endless merge conflicts, and the modules are inert when disabled.
  On the Mac deployment, don't install the NDI SDK and that module stays fully dormant.
- **Allen & Heath dLive console integration:** discussed (feasible — MIDI-over-TCP port 51325 or possibly
  OSC on current firmware; scope ~ one Shure phase; no live input metering over MIDI; the useful parts would
  be volunteer monitor mixing + mute/DCA state + current scene name). **Not being pursued** — no need.

## Working style notes
- Patches/diffs against upstream drift fast (upstream ChurchBoard is actively developed) — if working from a fresh
  clone or pulling upstream changes, expect to re-verify insertion points in `common.js`/`editor.js` rather than
  assuming line numbers are stable.
- Prefer small, testable increments per phase sub-item over one giant change — this matches how Phase 1 actually went
  (small pieces, verified working end-to-end, then committed) rather than a big-bang rewrite.
