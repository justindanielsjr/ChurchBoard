from __future__ import annotations

import asyncio
import math
import re
from typing import Any


FRAME = re.compile(r"<\s*(?:REP|REPLY|REPORT|SAMPLE)\s+(\d+)\s+([A-Z_]+)(?:\s+\{?([^>}]*)\}?)?\s*>")


def percent(value: str, maximum: int) -> int:
    try:
        return max(0, min(100, round(int(value.strip()) / maximum * 100)))
    except (TypeError, ValueError):
        return 0


def battery_percent(value: str) -> int | None:
    """Convert Shure's 0-5 battery bars without treating 255/unknown as full."""
    try:
        bars = int(value.strip())
    except (AttributeError, TypeError, ValueError):
        return None
    if not 0 <= bars <= 5:
        return None
    return round(bars / 5 * 100)


def battery_charge_percent(value: str) -> int | None:
    """Axient Digital reports TX_BATT_CHARGE_PERCENT as a direct 0-100 value (255 = unknown)."""
    try:
        charge = int(value.strip())
    except (AttributeError, TypeError, ValueError):
        return None
    return charge if 0 <= charge <= 100 else None


def format_frequency(value: str) -> str:
    """Axient FREQUENCY is a 7-digit kHz string, e.g. '0578350' -> '578.350 MHz'."""
    try:
        khz = int(value.strip())
    except (AttributeError, TypeError, ValueError):
        return str(value or "").strip()
    return f"{khz / 1000:.3f} MHz" if khz else ""


def axient_meter_percent(value: str, floor: int, ceiling: int) -> int:
    """Map an Axient 0-120 meter byte (actual dB = value - 120) onto 0-100% across [floor, ceiling] dB.

    Caller windows are bench-calibrated against the production AD4Qs: RF -90..-45 dBm
    (real range on a mic walk was -43 on the antennas to -80 behind a block wall; no-TX
    floor -105..-111), audio -50..-6 dBFS (silent mic idles ~-80, loudest sung audRms
    tops -3..-6). Captures 2026-09-02 (RF) and 2026-09-06 rehearsal (audio).
    """
    try:
        actual = int(value.strip()) - 120
    except (AttributeError, TypeError, ValueError):
        return 0
    return max(0, min(100, round((actual - floor) / (ceiling - floor) * 100)))


def axient_antenna_label(value: str) -> str:
    """ANTENNA_STATUS / rfAntStats: one char per antenna A-D, X=off, R=red, B=blue."""
    active = [letter for letter, flag in zip("ABCD", (value or "").strip()) if flag and flag != "X"]
    return f"Ant {'+'.join(active)}" if active else ""


def transmitter_active(state: dict[str, Any]) -> bool:
    tx_type = str(state.get("tx_type") or "").strip().upper()
    identified = bool(tx_type and tx_type not in {"UNKN", "UNKNOWN", "NONE", "OFF", "N/A"})
    battery_seen = bool(state.get("_battery_valid")) and int(state.get("battery_percent") or 0) > 0
    return bool(state.get("receiver_online") and (identified or battery_seen))


class ShureClient:
    def __init__(self, settings: dict[str, Any]):
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.get("enabled") and (self.settings.get("mics") or self.settings.get("receivers")))

    async def status(self) -> list[dict[str, Any]]:
        receivers = self._configured_receivers()
        results = await asyncio.gather(*(self._receiver(receiver) for receiver in receivers))
        return [mic for receiver in results for mic in receiver]

    def _configured_receivers(self) -> list[dict[str, Any]]:
        configured_mics = self.settings.get("mics") or []
        if not configured_mics:
            return self.settings.get("receivers", [])
        grouped: dict[tuple[str, int], dict[str, Any]] = {}
        for mic in configured_mics:
            host = str(mic.get("host") or "").strip()
            port = int(mic.get("port") or 2202)
            model = str(mic.get("model") or "qlx-ulx").strip().lower()
            if not host:
                continue
            receiver = grouped.setdefault((host, port), {
                "id": re.sub(r"[^a-z0-9]+", "-", host.casefold()).strip("-") or "receiver",
                "name": mic.get("receiver_name") or host,
                "host": host,
                "port": port,
                "model": model,
                "channel_configs": [],
            })
            receiver["channel_configs"].append(mic)
        return list(grouped.values())

    async def _receiver(self, receiver: dict[str, Any]) -> list[dict[str, Any]]:
        channel_configs = receiver.get("channel_configs") or []
        channel_numbers = sorted({int(item.get("channel") or 1) for item in channel_configs}) if channel_configs else list(range(1, int(receiver.get("channels", 2)) + 1))
        states = {index: {"name": f"Channel {index}", "battery_percent": 0, "rf": 0, "audio": 0, "online": False, "receiver_online": False, "errors": [], "_battery_valid": False} for index in channel_numbers}
        receiver_model = str(receiver.get("model") or "qlx-ulx").strip().lower()
        axient = receiver_model == "axient"
        battery_key, tx_key = ("TX_BATT_CHARGE_PERCENT", "TX_MODEL") if axient else ("BATT_BARS", "TX_TYPE")
        query_keys = ("CHAN_NAME", battery_key, "FREQUENCY", tx_key) + (("FD_MODE", "ANTENNA_STATUS") if axient else ())
        meter_rate = "00100" if axient else "100"
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(str(receiver.get("host", "")), int(receiver.get("port", 2202))), timeout=2)
            for channel in states:
                for key in query_keys:
                    writer.write(f"< GET {channel} {key} >".encode())
                writer.write(f"< SET {channel} METER_RATE {meter_rate} >".encode())
            await writer.drain()
            raw = b""
            deadline = asyncio.get_running_loop().time() + 1.25
            try:
                while len(raw) < 32768:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        break
                    chunk = await asyncio.wait_for(reader.read(4096), timeout=min(0.45, remaining))
                    if not chunk:
                        break
                    raw += chunk
                    seen = {(int(match.group(1)), match.group(2)) for match in FRAME.finditer(raw.decode(errors="ignore"))}
                    if all((channel, battery_key) in seen and (channel, tx_key) in seen and (channel, "ALL") in seen for channel in states):
                        break
            except asyncio.TimeoutError:
                pass
            writer.close()
            await writer.wait_closed()
            text = raw.decode(errors="ignore")
            for match in FRAME.finditer(text):
                channel, key, value = int(match.group(1)), match.group(2), (match.group(3) or "").strip()
                if channel not in states:
                    continue
                state = states[channel]
                state["receiver_online"] = True
                if key == "CHAN_NAME": state["name"] = value.replace("_", " ").strip()
                elif key == battery_key:
                    battery = battery_charge_percent(value) if axient else battery_percent(value)
                    state["_battery_valid"] = battery is not None
                    state["battery_percent"] = battery if battery is not None else 0
                elif key == "FREQUENCY": state["frequency"] = format_frequency(value) if axient else value
                elif key == tx_key: state["tx_type"] = value
                elif key == "FD_MODE": state["diversity"] = "" if value.upper() == "OFF" else value
                elif key == "ANTENNA_STATUS": state["antenna"] = axient_antenna_label(value)
                elif key == "ALL":
                    parts = value.split()
                    if axient and len(parts) >= 9:
                        # SAMPLE x ALL qual audBitmap audPeak audRms rfAntStats rfBitmapA rfRssiA rfBitmapB rfRssiB
                        state["antenna"] = axient_antenna_label(parts[4]) or state.get("antenna", "")
                        state["rf"] = max(axient_meter_percent(parts[6], -90, -45), axient_meter_percent(parts[8], -90, -45))
                        state["audio"] = axient_meter_percent(parts[3], -50, -6)
                    elif not axient and len(parts) >= 3:
                        state["rf"], state["audio"] = percent(parts[-2], 115), percent(parts[-1], 50)
        except (OSError, asyncio.TimeoutError) as exc:
            for state in states.values():
                state["errors"] = [str(exc) or "Receiver unavailable"]
        output = []
        receiver_id = str(receiver.get("id") or receiver.get("host") or "receiver")
        for channel, state in states.items():
            state["online"] = transmitter_active(state)
            state.pop("_battery_valid", None)
            if state["receiver_online"] and not state["online"] and not state["errors"]:
                state["errors"] = ["Transmitter off"]
            elif not state["receiver_online"] and not state["errors"]:
                state["errors"] = ["Receiver did not return status"]
            config = next((item for item in channel_configs if int(item.get("channel") or 1) == channel), {})
            configured_name = str(config.get("name") or "").strip()
            output.append({
                "id": str(config.get("id") or f"{receiver_id}-{channel}"),
                "receiver": config.get("receiver_name") or receiver.get("name") or receiver_id,
                "channel": channel,
                "model": str(config.get("model") or receiver_model),
                "default_photo": str(config.get("default_photo") or ""),
                **state,
                "name": configured_name or state["name"],
            })
        return output


# --- Shure PSM1000 (P10T in-ear transmitters) ------------------------------------
#
# Same command-string family / TCP 2202 as the receivers above, but a P10T is a
# transmitter: no battery, no received-RF metric. What it reports is frequency,
# RF mute, RF power and a stereo input audio meter (AUDIO_IN_LVL_L / _R). A P10T
# rack unit carries two transmitters, addressed as channel 1 and 2. The RF is
# always stereo; "dual mono" is a usage pattern (a different mono mix on L vs R,
# each performer's pack panned to a side), not a transmitter mode. Config is an
# explicit `iem_packs` list -- one row per physical pack, carrying the label
# printed on the bodypack -- so a dual-mono transmitter contributes two rows
# (side "left" / "right", each showing its own meter) and a stereo transmitter
# one row (side "stereo", showing the louder of L/R). Config lives at
# settings.iem = {"enabled": bool, "packs": [ {id,label,host,port,transmitter,
# side}, ... ]}. Two protocol quirks vs the receivers: commands must be
# CRLF-terminated, and box-level replies (no channel index, e.g. DEVICE_NAME)
# don't match FRAME -- we don't rely on them.

PSM_QUERY_KEYS = ("CHAN_NAME", "FREQUENCY", "RF_MUTE", "RF_TX_LVL")

# AUDIO_IN_LVL_L/_R is a linear-amplitude reading whose full scale (0 dBFS) is
# PSM_AUDIO_FULL_SCALE; convert with dBFS = 20*log10(raw / FS). Bench-calibrated
# 2026-09-02 against an A&H dLive signal generator into a P10T (.221 tx1): 5-point
# sweep 0..-40 dBFS read off the console aux meter, fit to within 0.2 dB. Silence
# idles ~300 (~-62 dBFS). The published command-strings page does not document this.
PSM_AUDIO_FULL_SCALE = 400000


def psm_audio_percent(value: str, floor: int = -48, ceiling: int = 0) -> int:
    """PSM1000 AUDIO_IN_LVL_L/_R linear-amplitude meter -> 0-100%.

    Convert to dBFS against PSM_AUDIO_FULL_SCALE, then window onto [floor, ceiling] dB.
    """
    try:
        raw = int(str(value).strip())
    except (TypeError, ValueError):
        return 0
    if raw <= 0:
        return 0
    dbfs = 20 * math.log10(raw / PSM_AUDIO_FULL_SCALE)
    return max(0, min(100, round((dbfs - floor) / (ceiling - floor) * 100)))


def psm_rf_muted(value: str) -> bool:
    """RF_MUTE reports 1 = muted, 0 = unmuted (value may be zero-padded)."""
    token = (value or "").strip()
    return token.lstrip("0") == "1" or token.upper() == "ON"


def psm_rf_power(value: str) -> str:
    """RF_TX_LVL -> a display string like '10 mW' (pass raw through if non-numeric)."""
    token = (value or "").strip()
    trimmed = token.lstrip("0") or "0"
    return f"{int(trimmed)} mW" if trimmed.isdigit() else token


def psm_pack_card(row: dict[str, Any], tx: dict[str, Any], *, online: bool = True, error: str = "") -> dict[str, Any]:
    """Build one pack card from a configured `iem_packs` row and its transmitter state."""
    side = str(row.get("side") or "stereo").strip().lower()
    transmitter = int(row.get("transmitter") or 1)
    label = str(row.get("label") or "").strip() or f"Pack {transmitter}"
    if side in ("left", "l"):
        audio = int(tx.get("audio_l") or 0)
    elif side in ("right", "r"):
        audio = int(tx.get("audio_r") or 0)
    else:
        audio = max(int(tx.get("audio_l") or 0), int(tx.get("audio_r") or 0))
    errors = [error] if error else []
    present = bool(online and tx.get("frequency"))
    if online and not present and not errors:
        errors.append("Transmitter not responding")
    return {
        "id": str(row.get("id") or f"{row.get('host')}-{transmitter}-{side}"),
        "name": label,
        "receiver": str(row.get("rack_name") or row.get("host") or "PSM1000"),
        "channel": transmitter,
        "model": "psm1000",
        "pack": True,
        "battery_percent": None,
        "rf": None,
        "audio": audio,
        "frequency": str(tx.get("frequency") or ""),
        "muted": bool(tx.get("rf_mute")),
        "rf_power": str(tx.get("rf_power") or ""),
        "online": present,
        "receiver_online": bool(online),
        "default_photo": "",
        "errors": errors,
    }


class PSM1000Client:
    """Poll Shure PSM1000 P10T rack transmitters via command strings over TCP 2202."""

    def __init__(self, settings: dict[str, Any]):
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.get("enabled") and self.settings.get("packs"))

    def _racks(self) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, int], dict[str, Any]] = {}
        for row in self.settings.get("packs") or []:
            host = str(row.get("host") or "").strip()
            if not host:
                continue
            port = int(row.get("port") or 2202)
            rack = grouped.setdefault((host, port), {"host": host, "port": port, "rows": []})
            rack["rows"].append(row)
        return list(grouped.values())

    async def status(self) -> list[dict[str, Any]]:
        results = await asyncio.gather(*(self._rack(rack) for rack in self._racks()))
        return [card for result in results for card in result]

    async def _rack(self, rack: dict[str, Any]) -> list[dict[str, Any]]:
        rows = rack.get("rows") or []
        transmitters = sorted({int(row.get("transmitter") or 1) for row in rows})
        tx_states: dict[int, dict[str, Any]] = {tx: {} for tx in transmitters}
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(str(rack.get("host", "")), int(rack.get("port", 2202))), timeout=2)
            # Unlike the QLX/ULX/Axient receivers, a P10T only acts on a command
            # that is terminated by CRLF, and ignores run-on strings. Start metering
            # first so AUDIO_IN_LVL reports stream in alongside the GET replies.
            for tx in transmitters:
                writer.write(f"< SET {tx} METER_RATE 00100 >\r\n".encode())
                for key in PSM_QUERY_KEYS:
                    writer.write(f"< GET {tx} {key} >\r\n".encode())
            await writer.drain()
            raw = b""
            deadline = asyncio.get_running_loop().time() + 1.25
            try:
                while len(raw) < 32768:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        break
                    chunk = await asyncio.wait_for(reader.read(4096), timeout=min(0.45, remaining))
                    if not chunk:
                        break
                    raw += chunk
                    seen = {(int(m.group(1)), m.group(2)) for m in FRAME.finditer(raw.decode(errors="ignore"))}
                    # RF_TX_LVL is the last GET per transmitter (so the config values
                    # already landed); also wait for one audio meter report per side.
                    if all((tx, "RF_TX_LVL") in seen and (tx, "AUDIO_IN_LVL_L") in seen for tx in transmitters):
                        break
            except asyncio.TimeoutError:
                pass
            writer.close()
            await writer.wait_closed()
            for match in FRAME.finditer(raw.decode(errors="ignore")):
                tx, key, value = int(match.group(1)), match.group(2), (match.group(3) or "").strip()
                state = tx_states.get(tx)
                if state is None:
                    continue
                if key == "CHAN_NAME": state["chan_name"] = value.replace("_", " ").strip()
                elif key == "FREQUENCY": state["frequency"] = format_frequency(value)
                elif key == "RF_MUTE": state["rf_mute"] = psm_rf_muted(value)
                elif key == "RF_TX_LVL": state["rf_power"] = psm_rf_power(value)
                elif key == "AUDIO_IN_LVL_L": state["audio_l"] = psm_audio_percent(value)
                elif key == "AUDIO_IN_LVL_R": state["audio_r"] = psm_audio_percent(value)
        except (OSError, asyncio.TimeoutError) as exc:
            return [psm_pack_card(row, {}, online=False, error=str(exc) or "Transmitter unavailable") for row in rows]
        return [psm_pack_card(row, tx_states.get(int(row.get("transmitter") or 1), {}), online=True) for row in rows]
