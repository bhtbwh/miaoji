from __future__ import annotations

import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from server.asr import TranscriptUpdate
from server.transcript import TranscriptAssembler, merge_fragment


class CoreFlowTest(unittest.TestCase):
    def test_mock_recording_flow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["MIAOJI_MOCK_ASR"] = "1"
            os.environ["MIAOJI_DATA_DIR"] = temp_dir

            import server.config
            import server.app

            importlib.reload(server.config)
            app_module = importlib.reload(server.app)
            client = TestClient(app_module.app)

            health = client.get("/api/health")
            self.assertEqual(health.status_code, 200)
            self.assertTrue(health.json()["mock_asr"])

            home = client.get("/")
            self.assertEqual(home.status_code, 200)
            self.assertIn("秒记", home.text)

            pcm_second = b"\x00\x00" * 16_000
            with client.websocket_connect("/ws/record?title=test") as websocket:
                started = websocket.receive_json()
                self.assertEqual(started["type"], "meeting_started")
                meeting_id = started["meeting"]["id"]

                websocket.send_bytes(pcm_second)
                update = websocket.receive_json()
                self.assertEqual(update["type"], "transcript")
                self.assertIn("已收到1秒音频", update["segment"]["text"])

                websocket.send_text(json.dumps({"type": "stop"}))
                finished = websocket.receive_json()
                if finished["type"] == "transcript":
                    finished = websocket.receive_json()
                self.assertEqual(finished["type"], "meeting_finished")

            meeting_dir = Path(temp_dir) / meeting_id
            self.assertTrue((meeting_dir / "audio.wav").exists())
            transcript = (meeting_dir / "transcript.txt").read_text(encoding="utf-8").strip()
            self.assertTrue(transcript)

            saved = json.loads((meeting_dir / "meeting.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["title"], "test")
            self.assertEqual(saved["duration_seconds"], 1)
            self.assertGreaterEqual(len(saved["transcript"]), 1)

    def test_streaming_fragments_are_assembled(self) -> None:
        class SettingsStub:
            transcript_min_chars = 8
            transcript_max_chars = 40

        assembler = TranscriptAssembler(SettingsStub())  # type: ignore[arg-type]
        updates = []
        updates.extend(assembler.accept(TranscriptUpdate("今天我们", False, 1.0)))
        updates.extend(assembler.accept(TranscriptUpdate("今天我们讨论一下项目进度。", False, 2.0)))

        self.assertEqual(updates[-1].text, "今天我们讨论一下项目进度。")
        self.assertTrue(updates[-1].is_final)
        self.assertEqual(merge_fragment("今天我们讨论", "讨论一下"), "今天我们讨论一下")


if __name__ == "__main__":
    unittest.main()
