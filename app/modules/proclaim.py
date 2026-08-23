from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Any
import xml.etree.ElementTree as ET

import httpx


class ProclaimClient:
    """Client for Faithlife Proclaim's supported local App Command API."""

    def __init__(self, settings: dict[str, Any]):
        self.settings = settings
        self.host = str(settings.get("host") or "127.0.0.1").strip()
        self.port = int(settings.get("port") or 52195)
        self.password = str(settings.get("password") or "")
        self.configured = bool(settings.get("enabled") and self.host)
        self._token = ""
        self._client = httpx.AsyncClient(base_url=f"http://{self.host}:{self.port}", timeout=2.5)
        self._session_id = ""
        self._presentation: dict[str, Any] = {}
        self._presentation_revision = ""
        self._slide_text_cache: dict[tuple[str, str], list[str]] = {}
        self._presentation_db: Path | None = None
        self._active_item_id = ""
        self._active_item_started = 0.0

    async def close(self) -> None:
        await self._client.aclose()

    async def _authenticate(self) -> None:
        if not self.password or self._token:
            return
        response = await self._client.post("/appCommand/authenticate", json={"Password": self.password})
        response.raise_for_status()
        payload = response.json()
        self._token = str(payload.get("proclaimAuthToken") or payload.get("ProclaimAuthToken") or "")
        if not self._token:
            raise ValueError("Proclaim did not return an authentication token")

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        await self._authenticate()
        headers = dict(kwargs.pop("headers", {}))
        if self._token:
            headers["ProclaimAuthToken"] = self._token
        response = await self._client.request(method, path, headers=headers, **kwargs)
        if response.status_code in {401, 403} and self.password:
            self._token = ""
            await self._authenticate()
            headers["ProclaimAuthToken"] = self._token
            response = await self._client.request(method, path, headers=headers, **kwargs)
        response.raise_for_status()
        return response

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        """Decode Proclaim JSON, which is commonly prefixed with a UTF-8 BOM."""
        return response.json() if not response.content.startswith(b"\xef\xbb\xbf") else json.loads(response.content.decode("utf-8-sig"))

    async def _on_air_session_id(self) -> str:
        response = await self._request("GET", "/onair/session")
        try:
            payload = self._json(response)
        except ValueError:
            payload = response.content.decode("utf-8-sig").strip().strip('"')
        session_id = str(payload or "").strip()
        if not session_id:
            raise ValueError("Proclaim is not currently on air")
        if session_id != self._session_id:
            self._session_id = session_id
            self._presentation = {}
            self._presentation_revision = ""
        return session_id

    async def _on_air(self, path: str) -> Any:
        session_id = await self._on_air_session_id()
        response = await self._request("GET", path, headers={"OnAirSessionId": session_id})
        return self._json(response)

    def _find_presentation_db(self) -> Path | None:
        if self._presentation_db and self._presentation_db.exists():
            return self._presentation_db
        roots = [
            Path.home() / "Library" / "Application Support" / "Proclaim" / "Data",
            Path(os.environ.get("LOCALAPPDATA") or "") / "Proclaim" / "Data",
        ]
        candidates = [db for root in roots if str(root) and root.exists() for db in root.glob("*/PresentationManager/PresentationManager.db")]
        self._presentation_db = max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None
        return self._presentation_db

    @staticmethod
    def _plain_slides(xml: str) -> list[str]:
        if not xml:
            return []
        try:
            root = ET.fromstring(f"<ProclaimText>{xml}</ProclaimText>")
        except ET.ParseError:
            return []
        paragraphs = []
        for paragraph in root:
            line = " ".join(str(run.attrib.get("Text") or "") for run in paragraph.iter("Run")).strip()
            paragraphs.append(line)
        slides: list[str] = []
        current: list[str] = []
        for line in paragraphs:
            if line:
                current.append(line)
            elif current:
                slides.append("\n".join(current))
                current = []
        if current:
            slides.append("\n".join(current))
        return slides

    def _slide_texts(self, item_id: str, item_kind: str, revision: str) -> list[str]:
        cache_key = (item_id, revision)
        if cache_key in self._slide_text_cache:
            return self._slide_text_cache[cache_key]
        database = self._find_presentation_db()
        if not database:
            return []
        content_keys = {
            "SongLyrics": "_richtextfield:Lyrics",
            "Content": "_richtextfield:Main Content",
            "BiblePassage": "_richtextfield:Passage",
        }
        try:
            with sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=.25) as connection:
                row = connection.execute(
                    "SELECT Content FROM ServiceItems WHERE ServiceItemId = ? LIMIT 1",
                    (item_id.replace("-", ""),),
                ).fetchone()
            content = json.loads(row[0]) if row and row[0] else {}
            slides = self._plain_slides(str(content.get(content_keys.get(item_kind, "")) or ""))
        except (OSError, sqlite3.Error, ValueError, TypeError):
            slides = []
        self._slide_text_cache[cache_key] = slides
        return slides

    @staticmethod
    def _duration_seconds(value: Any) -> int:
        import re
        match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", str(value or "").upper())
        if not match:
            return 0
        hours, minutes, seconds = match.groups()
        return round(int(hours or 0) * 3600 + int(minutes or 0) * 60 + float(seconds or 0))

    def _item_content_settings(self, item_id: str) -> dict[str, Any]:
        database = self._find_presentation_db()
        if not database or not item_id:
            return {}
        try:
            with sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=.25) as connection:
                row = connection.execute(
                    "SELECT Content FROM ServiceItems WHERE lower(replace(ServiceItemId, '-', '')) = ? ORDER BY RecordId DESC LIMIT 1",
                    (item_id.replace("-", "").casefold(),),
                ).fetchone()
            return json.loads(row[0]) if row and row[0] else {}
        except (OSError, sqlite3.Error, ValueError, TypeError, json.JSONDecodeError):
            return {}

    async def status(self) -> dict[str, Any]:
        if not self.configured:
            return {"connected": False, "on_air": False, "error": "Proclaim is not enabled"}
        try:
            live_status = await self._on_air("/onair/statusChanged")
        except (ValueError, httpx.HTTPStatusError) as exc:
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code != 404:
                raise
            return {"connected": True, "on_air": False, "session_id": "", "current": {}, "next": {}, "error": ""}

        revision = str(live_status.get("presentationLocalRevision") or "")
        if not self._presentation or revision != self._presentation_revision:
            presentation = await self._on_air("/presentations/onair")
            self._presentation = presentation if isinstance(presentation, dict) else {}
            self._presentation_revision = revision

        state = live_status.get("status") or {}
        items = self._presentation.get("serviceItems") or []
        item_id = str(state.get("itemId") or "")
        item_index = next((index for index, item in enumerate(items) if str(item.get("id") or "") == item_id), -1)
        item = items[item_index] if item_index >= 0 else {}
        slide_index = max(0, int(state.get("slideIndex") or 0))
        slide_revision = str(((item.get("slides") or [{}])[0]).get("localRevision") or revision)
        slide_texts = self._slide_texts(item_id, str(item.get("kind") or ""), slide_revision) if item else []
        current = {
            "id": item.get("id"),
            "title": item.get("title") or "",
            "kind": item.get("kind") or "",
            "notes": item.get("notes") or "",
            "slide_index": slide_index,
            "slide_number": slide_index + 1,
            "total_slides": len(item.get("slides") or []),
            "text": slide_texts[slide_index] if slide_index < len(slide_texts) else "",
            "next_slide_text": slide_texts[slide_index + 1] if slide_index + 1 < len(slide_texts) else "",
            "item_index": item_index,
        } if item else {}
        next_payload: dict[str, Any] = {}
        if item and slide_index + 1 < len(item.get("slides") or []):
            next_payload = {
                "id": item.get("id"),
                "title": item.get("title") or "",
                "kind": item.get("kind") or "",
                "slide_index": slide_index + 1,
                "slide_number": slide_index + 2,
                "total_slides": len(item.get("slides") or []),
                "text": slide_texts[slide_index + 1] if slide_index + 1 < len(slide_texts) else "",
                "same_item": True,
            }
        elif item_index >= 0 and item_index + 1 < len(items):
            next_item = items[item_index + 1]
            next_revision = str(((next_item.get("slides") or [{}])[0]).get("localRevision") or revision)
            next_texts = self._slide_texts(str(next_item.get("id") or ""), str(next_item.get("kind") or ""), next_revision)
            next_payload = {
                "id": next_item.get("id"),
                "title": next_item.get("title") or "",
                "kind": next_item.get("kind") or "",
                "slide_index": 0,
                "slide_number": 1,
                "total_slides": len(next_item.get("slides") or []),
                "text": next_texts[0] if next_texts else "",
                "same_item": False,
            }
        playlist_items = []
        for index, service_item in enumerate(items):
            service_item_id = str(service_item.get("id") or "")
            service_item_revision = str(((service_item.get("slides") or [{}])[0]).get("localRevision") or revision)
            texts = self._slide_texts(service_item_id, str(service_item.get("kind") or ""), service_item_revision)
            slide_count = len(service_item.get("slides") or [])
            playlist_items.append({
                "id": service_item_id,
                "index": index,
                "title": service_item.get("title") or "",
                "kind": service_item.get("kind") or "",
                "active": index == item_index,
                "triggerable": str(service_item.get("kind") or "") != "StageDirectionCue",
                "slides": [{"index": slide + 1, "slide_index": slide, "text": texts[slide] if slide < len(texts) else ""} for slide in range(slide_count)],
            })

        current_settings = self._item_content_settings(item_id) if item else {}
        has_duration = str(current_settings.get("HasTargetDuration") or "").casefold() == "true"
        duration_seconds = self._duration_seconds(current_settings.get("TargetDuration")) if has_duration else 0
        if item_id != self._active_item_id:
            self._active_item_id, self._active_item_started = item_id, time.monotonic()
        elapsed = max(0, round(time.monotonic() - self._active_item_started)) if item_id else 0
        remaining = max(0, duration_seconds - elapsed) if duration_seconds else 0
        timers = [{
            "name": item.get("title") or "Current Proclaim item",
            "duration_seconds": duration_seconds,
            "elapsed_seconds": min(elapsed, duration_seconds),
            "remaining_seconds": remaining,
            "time": f"{remaining // 60:02d}:{remaining % 60:02d}",
            "state": "running" if str(state.get("mediaState") or "").casefold() == "playing" and remaining else "stopped",
        }] if duration_seconds else []
        return {
            "connected": True,
            "on_air": True,
            "session_id": self._session_id,
            "presentation_id": live_status.get("presentationId") or self._presentation.get("id"),
            "presentation_title": self._presentation.get("title") or "",
            "revision": state.get("revision"),
            "media_state": state.get("mediaState") or "",
            "current": current,
            "next": next_payload,
            "service_items": items,
            "playlist_items": playlist_items,
            "timers": timers,
            "error": "",
        }

    async def command(self, name: str, index: int | None = None) -> None:
        params: dict[str, Any] = {"appCommandName": name}
        if index is not None:
            params["index"] = int(index)
        await self._request("GET", "/appCommand/perform", params=params)
