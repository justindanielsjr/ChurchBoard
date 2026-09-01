#!/usr/bin/env python3
"""One-off bench tool: capture raw Shure Axient Digital command-string traffic.

Purpose: calibrate the RF/audio meter windows in ``app/modules/shure.py``
(``axient_meter_percent`` — the -100..-40 dBm and -50..0 dBFS placeholders).
This is NOT part of the app. Run it from any machine on the production LAN that
can reach the receivers' Shure Control interface on TCP 2202.

    python tools/axient_probe.py                        # the 3 AD4Qs, 60 s
    python tools/axient_probe.py --seconds 180
    python tools/axient_probe.py --ip 10.100.3.217 --channels 1-2
    python tools/axient_probe.py --ip 10.100.3.216 --channels 0   # AD600, device-level only

During the capture window, have talent use each mic at realistic levels
(silent -> normal speech/vocal -> loud) and note the receiver's own RSSI (dBm)
and audio (dBFS) readings from the front panel or Wireless Workbench for two or
three moments. Send the .log files plus those hand readings back.

Multiple control connections to a Shure receiver are fine (WWB + a control
system coexist), so this does not disturb a running ChurchBoard instance.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import re
from pathlib import Path

PORT = 2202

DEFAULT_TARGETS = {
    "10.100.3.217": "AD4Q-1 (4x ADX2)",
    "10.100.3.218": "AD4Q-2 (4x ADX2)",
    "10.100.3.219": "AD4Q-3 (4x ADX1)",
}
# AD600 at 10.100.3.216 is a Spectrum Manager: no per-channel transmitter, audio
# or RF telemetry, so it is not a default target. Probe it with --ip if wanted.

# Same frame grammar the shure module parses.
FRAME = re.compile(r"<\s*(?:REP|REPLY|REPORT|SAMPLE)\s+(\d+)\s+([A-Z_]+)(?:\s+\{?([^>}]*)\}?)?\s*>")

# Per-channel properties to GET once up front (superset of what the module uses,
# plus the raw metering fields we are calibrating against).
GET_KEYS = (
    "CHAN_NAME", "TX_MODEL", "FREQUENCY", "FD_MODE", "ANTENNA_STATUS",
    "TX_BATT_CHARGE_PERCENT", "TX_BATT_BARS", "TX_BATT_MINS", "CHAN_QUALITY",
    "RSSI 0", "AUDIO_LEVEL_RMS", "AUDIO_LEVEL_PEAK",
)
# SAMPLE x ALL, standard channel (no frequency diversity, no quadversity):
SAMPLE_ALL_FIELDS = (
    "qual", "audBitmap", "audPeak", "audRms", "rfAntStats",
    "rfBitmapA", "rfRssiA", "rfBitmapB", "rfRssiB",
)


def parse_channels(spec: str) -> list[int]:
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            out.update(range(int(lo), int(hi) + 1))
        else:
            out.add(int(part))
    return sorted(out)


def _db(value: str, offset: int = 120) -> str:
    try:
        return f"{int(value) - offset} dB"
    except ValueError:
        return value


def annotate(channel: int, key: str, value: str) -> str:
    """Add Shure's documented conversions so the log is readable without a decoder ring."""
    parts = value.split()
    if key == "RSSI" and len(parts) == 2:
        return f"  ->  antenna {parts[0]} = {_db(parts[1], 120).replace('dB', 'dBm')}"
    if key in ("AUDIO_LEVEL_RMS", "AUDIO_LEVEL_PEAK") and parts:
        return f"  ->  {_db(parts[0], 120).replace('dB', 'dBFS')}"
    if key == "FREQUENCY" and value.strip().isdigit():
        return f"  ->  {int(value) / 1000:.3f} MHz"
    if key == "ALL" and len(parts) >= len(SAMPLE_ALL_FIELDS):
        named = dict(zip(SAMPLE_ALL_FIELDS, parts))
        rssi_a = _db(named["rfRssiA"], 120).replace("dB", "dBm")
        rssi_b = _db(named["rfRssiB"], 120).replace("dB", "dBm")
        peak = _db(named["audPeak"], 120).replace("dB", "dBFS")
        rms = _db(named["audRms"], 120).replace("dB", "dBFS")
        return (
            f"  ->  ant={named['rfAntStats']} rssiA={rssi_a} rssiB={rssi_b} "
            f"audPeak={peak} audRms={rms} qual={named['qual']}"
        )
    return ""


async def probe(ip: str, label: str, channels: list[int], seconds: int, meter_ms: int, out_dir: Path) -> None:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = re.sub(r"[^A-Za-z0-9]+", "-", label).strip("-") or ip.replace(".", "-")
    path = out_dir / f"axient-capture-{safe}-{stamp}.log"
    tag = f"[{label}]"

    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, PORT), timeout=4)
    except (OSError, asyncio.TimeoutError) as exc:
        print(f"{tag} CONNECT FAILED ({ip}:{PORT}): {exc}")
        return

    with path.open("w", encoding="utf-8") as log:
        def emit(line: str) -> None:
            print(f"{tag} {line}")
            log.write(line + "\n")
            log.flush()

        emit(f"# {dt.datetime.now().isoformat(timespec='seconds')}  {ip}  {label}")
        emit(f"# channels={channels} meter_rate={meter_ms}ms window={seconds}s")

        writer.write(b"< GET 0 MODEL >< GET 0 FW_VER >")
        for ch in channels:
            for key in GET_KEYS:
                writer.write(f"< GET {ch} {key} >".encode())
            if ch != 0:
                writer.write(f"< SET {ch} METER_RATE {meter_ms:05d} >".encode())
        await writer.drain()

        buf = ""
        pos = 0
        deadline = asyncio.get_running_loop().time() + seconds
        try:
            while asyncio.get_running_loop().time() < deadline:
                remaining = deadline - asyncio.get_running_loop().time()
                try:
                    chunk = await asyncio.wait_for(reader.read(4096), timeout=min(1.0, remaining))
                except asyncio.TimeoutError:
                    continue
                if not chunk:
                    emit("# connection closed by receiver")
                    break
                buf += chunk.decode(errors="replace")
                for match in FRAME.finditer(buf, pos):
                    ch, key, value = int(match.group(1)), match.group(2), (match.group(3) or "").strip()
                    ts = dt.datetime.now().strftime("%H:%M:%S")
                    emit(f"{ts}  ch{ch:<2} {key:<24} {value}{annotate(ch, key, value)}")
                    pos = match.end()
        finally:
            for ch in channels:
                if ch != 0:
                    writer.write(f"< SET {ch} METER_RATE 00000 >".encode())
            try:
                await writer.drain()
            except OSError:
                pass
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
            emit(f"# done -> {path}")


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ip", action="append", metavar="ADDR",
                    help="receiver Shure Control IP (repeatable); default = the 3 AD4Qs")
    ap.add_argument("--channels", default="1-4", help="channel spec, e.g. '1-4' or '1,3' (use '0' for device-level only)")
    ap.add_argument("--seconds", type=int, default=60, help="capture window (default 60)")
    ap.add_argument("--meter-ms", type=int, default=1000, help="METER_RATE in ms (default 1000 = 1 Hz)")
    ap.add_argument("--out-dir", type=Path, default=Path.cwd(), help="where to write .log files (default: cwd)")
    args = ap.parse_args()

    targets = {ip: ip for ip in args.ip} if args.ip else dict(DEFAULT_TARGETS)
    channels = parse_channels(args.channels)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Probing {len(targets)} receiver(s), channels {channels}, {args.seconds}s window.")
    print("Have talent exercise each mic (silent / normal / loud) during the window,")
    print("and jot the receiver's own RSSI (dBm) + audio (dBFS) for a few moments.\n")

    await asyncio.gather(*(
        probe(ip, label, channels, args.seconds, args.meter_ms, args.out_dir)
        for ip, label in targets.items()
    ))


if __name__ == "__main__":
    asyncio.run(main())
