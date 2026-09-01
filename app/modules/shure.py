from __future__ import annotations

import asyncio
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

    The floor/ceiling windows the callers pass are first-guess and need AD4Q/AD600 bench
    confirmation before they can be trusted for anything beyond a rough bar.
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
                        state["rf"] = max(axient_meter_percent(parts[6], -100, -40), axient_meter_percent(parts[8], -100, -40))
                        state["audio"] = axient_meter_percent(parts[3], -50, 0)
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
