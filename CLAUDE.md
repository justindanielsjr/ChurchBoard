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

### Phase 2 — Assignment/pool redesign — IN PROGRESS, not yet built
This scope went through several iterations before landing here — this is the final agreed shape, don't rebuild
earlier discarded versions of it:

- **Do NOT build a "team opt-in checkbox" pool mechanism.** Earlier discussion explored letting dashboard widgets
  pull from a Planning Center team's full roster regardless of whether they're scheduled for a given service. This
  was explicitly dropped — testing showed the *existing* `team_ids`/`position_keys` filtering on the assignments/mics
  widget (which already lets you opt teams in or leave them out — e.g. Security stays excluded by simply never being
  checked) is good enough as-is. Leave that mechanism untouched.
- **Manual people list** — a small settings-backed list (name + optional photo) for people who exist in real life but
  not as Planning Center People records (e.g. a last-minute walk-on). Independent of PCO entirely.
- **Manual mic channels** — for the Shure GLXD16 guitar packs, which have no Ethernet/IP control at all. Currently
  `state.mics` is built *exclusively* from live Shure/Sennheiser network polling
  (`next_state["mics"] = shure_status + sennheiser_status` in `app/modules/runtime.py`) — there's no existing concept
  of a channel that isn't a live networked receiver. Need: a small manual-channel list (name only, no IP/model),
  merged into that same `mics` array, tagged as non-networked. Card rendering (`micCardMarkup` in `common.js`) needs
  a branch for this: currently `mic.placeholder` means "a person is assigned but no receiver matched" (opposite of
  what's needed here) — a manual channel needs its own flag so it doesn't render as a fake "OFFLINE" battery/RF
  reading, more like the honest "no telemetry" treatment already planned for PSM1000 packs in Phase 4. Something
  like a `networked: false` or `manual: true` flag, with the card showing "Not networked" and no meters.
- **Person-ID-keyed assignment mapping** — replacing the current `position_mic_map` (position-string → mic ID) with
  a mapping keyed by person ID, where the person ID can point to either a PCO-scheduled person or a manual person,
  and the target can be either a networked or manual mic/pack channel. This is the mechanism that makes everything
  else here possible — manual people and manual channels only matter once assignment isn't locked to PCO position
  strings.
- **Combined mic+pack card** — one card per person with two independent optional slots (mic, pack), not two separate
  boards. Confirmed relevant because packs and mics are physically stored together and only vocals/band ever touch a
  pack — a security or speaking-team person's card just never shows a pack slot. Card rendering already exists per
  *mic* (`micCardMarkup`) — extending to show both slots per *person* is a real but contained change on top of the
  person-ID mapping above.

### Phase 3 — Shure Axient Digital integration — not started
Extend `app/modules/shure.py` (currently only handles QLX-D/ULX-D/SLX-D battery field `BATT_BARS` and a generic
`GET`/`REP`/`SAMPLE` frame parser over TCP 2202) with an Axient branch: different battery field (`BATT_CHARGE`,
a direct percentage, not the 0–5 bar scale), Axient's documented extra fields (antenna/frequency diversity). Also
needs a new `<option>` in the receiver-model dropdown in the setup UI (currently only offers "Shure QLX-D / ULX-D"
and "Shure SLX-D"). Protocol is officially published by Shure (not reverse-engineered) at pubs.shure.com/command-
strings. Needs real AD4Q/AD600 hardware on the bench to nail down exact field values — can't be fully verified from
docs alone.

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
