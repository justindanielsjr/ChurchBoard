from __future__ import annotations

import asyncio
import json
import unittest

import httpx

from app.modules.proclaim import ProclaimClient


class ProclaimClientTests(unittest.TestCase):
    def test_plain_slides_preserve_lines_and_split_blank_paragraphs(self) -> None:
        xml = '<Paragraph><Run Text="Line one" /></Paragraph><Paragraph><Run Text="Line two" /></Paragraph><Paragraph><Run Text="" /></Paragraph><Paragraph><Run Text="Next slide" /></Paragraph>'
        self.assertEqual(ProclaimClient._plain_slides(xml), ["Line one\nLine two", "Next slide"])

    def test_status_follows_proclaims_on_air_item_and_slide(self) -> None:
        calls = {"presentation": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/onair/session":
                return httpx.Response(200, content=b"\xef\xbb\xbf\"session-1\"")
            if request.url.path == "/onair/statusChanged":
                self.assertEqual(request.headers.get("OnAirSessionId"), "session-1")
                return httpx.Response(200, json={
                    "presentationId": "presentation-1",
                    "presentationLocalRevision": 12,
                    "status": {"revision": 7, "itemId": "song-2", "slideIndex": 3, "mediaState": "Playing"},
                })
            if request.url.path == "/presentations/onair":
                calls["presentation"] += 1
                return httpx.Response(200, json={
                    "id": "presentation-1",
                    "title": "Sunday",
                    "serviceItems": [
                        {"id": "song-1", "title": "First Song", "kind": "SongLyrics", "slides": [{"index": 0}]},
                        {"id": "song-2", "title": "Second Song", "kind": "SongLyrics", "slides": [{"index": i} for i in range(6)]},
                        {"id": "message", "title": "Message", "kind": "Content", "slides": [{"index": 0}]},
                    ],
                })
            return httpx.Response(404)

        async def run() -> tuple[dict, dict]:
            client = ProclaimClient({"enabled": True, "host": "127.0.0.1", "port": 52195})
            await client._client.aclose()
            client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://proclaim")
            first = await client.status()
            second = await client.status()
            await client.close()
            return first, second

        first, second = asyncio.run(run())
        self.assertTrue(first["on_air"])
        self.assertEqual(first["current"]["title"], "Second Song")
        self.assertEqual(first["current"]["slide_number"], 4)
        self.assertEqual(first["current"]["total_slides"], 6)
        self.assertEqual(first["next"]["title"], "Second Song")
        self.assertEqual(first["next"]["slide_number"], 5)
        self.assertTrue(first["next"]["same_item"])
        self.assertEqual(second["revision"], 7)
        self.assertEqual(calls["presentation"], 1)


if __name__ == "__main__":
    unittest.main()
