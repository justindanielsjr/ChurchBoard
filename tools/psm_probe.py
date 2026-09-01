#!/usr/bin/env python3
"""One-off bench tool: capture Shure PSM1000 P10T audio-meter traffic.

Purpose: calibrate ``PSM_AUDIO_FULL_SCALE`` in ``app/modules/shure.py`` (the
``AUDIO_IN_LVL_L/_R`` -> 0-100% mapping, working model ``dBFS = value/50 - 50``).
This is NOT part of the app. Run it from any machine on the production LAN that
can reach the P10T Shure Control interface on TCP 2202.

    python tools/psm_probe.py                       # the 3 P10T racks, 180 s
    python tools/psm_probe.py --seconds 420
    python tools/psm_probe.py --ip 10.100.3.220 --transmitters 1

During the window, feed real programme into each transmitter at service gain
(silent -> normal -> as loud as it gets) and note, for each condition, the
console send level driving that input and the wall-clock time. Send the .log
files plus those notes back.

Multiple control connections to a P10T are fine, so this does not disturb a
running ChurchBoard instance.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import re
from pathlib import Path

PORT = 2202

DEFAULT_TARGETS = {
    "10.100.3.220": "P10T-1 (IEM ** / IEM 1, stereo)",
    "10.100.3.221": "P10T-2 (IEM 2-5, dual mono L/R)",
    "10.100.3.222": "P10T-3 (GTR 2 / GTR 3, stereo)",
}

# P10T replies are < REPORT x KEY value > , CRLF-terminated, value may hold spaces.
FRAME = re.compile(r"<\s*REPORT\s+(\d+)\s+([A-Z_]+)(?:\s+([^>]*?))?\s*>")

GET_KEYS = ("CHAN_NAME", "FREQUENCY", "RF_MUTE", "RF_TX_LVL", "AUDIO_TX_MODE")

# Mirror of the working model in shure.py so the log shows what the app would do.
FULL_SCALE = 2500


def parse_transmitters(spec: str) -> list[int]:
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if part:
            out.add(int(part))
    return sorted(out) or [1, 2]


def annotate(key: str, value: str) -> str:
    if key in ("AUDIO_IN_LVL_L", "AUDIO_IN_LVL_R"):
        try:
            raw = int(value)
        except ValueError:
            return ""
        pct = max(0, min(100, round(raw / FULL_SCALE * 100)))
        return f"  ->  {raw / 50 - 50:+.1f} dBFS (model)   app would show ~{pct}%"
    if key == "FREQUENCY" and value.strip().isdigit():
        return f"  ->  {int(value) / 1000:.3f} MHz"
    if key == "RF_MUTE":
        return "  ->  MUTED" if value.strip().lstrip("0") == "1" else "  ->  live"
    if key == "AUDIO_TX_MODE":
        return {"1": "  ->  mono", "2": "  ->  point-to-point", "3": "  ->  stereo"}.get(value.strip(), "")
    return ""


async def probe(ip: str, label: str, transmitters: list[int], seconds: int, meter_ms: int, out_dir: Path) -> None:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = re.sub(r"[^A-Za-z0-9]+", "-", label).strip("-") or ip.replace(".", "-")
    path = out_dir / f"psm-capture-{safe}-{stamp}.log"
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
        emit(f"# transmitters={transmitters} meter_rate={meter_ms}ms window={seconds}s  FULL_SCALE={FULL_SCALE}")

        # P10T only acts on CRLF-terminated commands; start metering before the GETs.
        for tx in transmitters:
            writer.write(f"< SET {tx} METER_RATE {meter_ms:05d} >\r\n".encode())
            for key in GET_KEYS:
                writer.write(f"< GET {tx} {key} >\r\n".encode())
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
                    tx, key, value = match.group(1), match.group(2), (match.group(3) or "").strip()
                    ts = dt.datetime.now().strftime("%H:%M:%S")
                    emit(f"{ts}  tx{tx} {key:<16} {value}{annotate(key, value)}")
                    pos = match.end()
        finally:
            for tx in transmitters:
                writer.write(f"< SET {tx} METER_RATE 00000 >\r\n".encode())
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
    ap.add_argument("--ip", action="append", metavar="ADDR", help="P10T Shure Control IP (repeatable); default = the 3 racks")
    ap.add_argument("--transmitters", default="1,2", help="transmitter spec within each rack, e.g. '1,2' or '1'")
    ap.add_argument("--seconds", type=int, default=180, help="capture window (default 180)")
    ap.add_argument("--meter-ms", type=int, default=250, help="METER_RATE in ms (default 250 = 4 Hz)")
    ap.add_argument("--out-dir", type=Path, default=Path.cwd(), help="where to write .log files (default: cwd)")
    args = ap.parse_args()

    targets = {ip: ip for ip in args.ip} if args.ip else dict(DEFAULT_TARGETS)
    transmitters = parse_transmitters(args.transmitters)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Probing {len(targets)} P10T rack(s), transmitters {transmitters}, {args.seconds}s window.")
    print("Feed real programme at service gain (silent / normal / loud) during the window,")
    print("and note the console send level + wall-clock time for each condition.\n")

    await asyncio.gather(*(
        probe(ip, label, transmitters, args.seconds, args.meter_ms, args.out_dir)
        for ip, label in targets.items()
    ))


if __name__ == "__main__":
    asyncio.run(main())
