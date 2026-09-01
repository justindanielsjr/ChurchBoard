# Sunday meter-calibration capture plan

One capture pass to set the three UNCONFIRMED meter-scaling constants left over from
Phases 3 and 4. Everything else in the Shure integrations is already verified.

| Constant | File | Now (placeholder) | What it controls |
|---|---|---|---|
| RF window | `app/modules/shure.py` → `axient_meter_percent(parts[6], -100, -40)` | −100 dBm → 0 %, −40 dBm → 100 % | Axient mic card RF bar |
| Audio window | `app/modules/shure.py` → `axient_meter_percent(parts[3], -50, 0)` | −50 dBFS → 0 %, 0 dBFS → 100 % | Axient mic card audio bar |
| `PSM_AUDIO_FULL_SCALE` | `app/modules/shure.py` | `2500` (model `dBFS = v/50 − 50`) | PSM1000 pack card audio bar |

Already measured (transmitters OFF): Axient no-signal floor RSSI raw ≈ 9–12, `audRms` raw 033,
`audPeak` raw 005. PSM no-signal `AUDIO_IN_LVL_L/_R` ≈ 300–450 (idle bus noise).

The bench box reaches every device on TCP 2202. Run the probes from there (or any laptop on the
production LAN). Multiple control connections are fine — this does not disturb ChurchBoard or WWB.

---

## Prep (2 min)

```
cd <repo>
.venv/Scripts/python.exe -c "import socket
for ip in ('10.100.3.217','10.100.3.218','10.100.3.219','10.100.3.220','10.100.3.221','10.100.3.222'):
    try:
        socket.create_connection((ip,2202),2).close(); print(ip,'ok')
    except OSError as e:
        print(ip,'FAIL',e)"
```

All six should print `ok`. If any print `FAIL`, that device isn't reachable from this machine — fix before starting.

---

## Part A — Axient RF window (no band needed, ~10 min, can be done before rehearsal)

1. Start the probe (writes one `.log` per receiver to the current directory):

   ```
   .venv/Scripts/python.exe tools/axient_probe.py --seconds 600
   ```

2. Power on **one ADX2** and **one ADX1** (so both transmitter types are represented). Leave their
   mics live but quiet.

3. Walk one transmitter to three positions, holding each **~30 s**, and for each write down the
   **wall-clock time** and the receiver's own **RSSI in dBm** (front panel, or WWB → channel → RF):
   - **P1** – right at the antennas / front of stage (strongest)
   - **P2** – normal performer position, mid-stage
   - **P3** – as far as anyone realistically goes (back of platform / green room doorway)

4. Let the probe finish or Ctrl-C it.

The probe already prints `RSSI  ->  antenna N = −XX dBm` and expands each `SAMPLE ALL` frame, so the
raw value ↔ dBm pairing is in the log; the handwritten dBm from WWB is the cross-check.

---

## Part B — Axient audio window (during rehearsal, ~5 min)

Keep (or restart) `axient_probe.py` running. Pick **2–3 vocal channels** actually in use. For each,
hold three conditions **~20 s** and note the **time** + the receiver's **audio level in dBFS**
(WWB → channel → audio meter):

- **silent** – performer not singing, mic open
- **normal** – normal sung/spoken level
- **loud** – loudest part of the set for that mic

---

## Part C — PSM1000 pack audio (during rehearsal, ~5 min)

```
.venv/Scripts/python.exe tools/psm_probe.py --seconds 420
```

For **2–3 IEM mixes** (include at least one dual-mono transmitter on 10.100.3.221 so L and R are
separate), hold three conditions **~20 s** and note the **time** + the **console send level feeding
that P10T input** (the bus/matrix output meter, in dBFS or dBu — whichever your console shows):

- **silent** – nothing in that mix
- **normal** – full band playing, typical mix level
- **loud** – loudest moment

The probe prints `AUDIO_IN_LVL_L/_R  ->  −XX dBFS (model)  app would show ~NN%` so you can already
see whether the current guess looks sane while capturing.

---

## Send back

- All `.log` files from `axient_probe.py` and `psm_probe.py` (they're timestamped, plain text).
- The handwritten notes: for each condition, `time · channel/mix · what it was (P1/silent/loud/…) ·
  the dBm or dBFS you read`.

## Then

Pick `floor`/`ceiling` for the two Axient windows and `PSM_AUDIO_FULL_SCALE` so the bar tracks the
hardware — three one-line edits in `shure.py`, re-run the unit tests, quick board re-check. That
closes out Phases 3 and 4.
