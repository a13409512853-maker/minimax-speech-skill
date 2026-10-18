import importlib.util
import io
import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch
import wave

SCRIPT = Path(__file__).resolve().parents[1] / "skills/minimax-speech/scripts/minimax_speech.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("speech", SCRIPT)
speech = importlib.util.module_from_spec(spec)
spec.loader.exec_module(speech)


class FakeWS:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.sent = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def recv(self, timeout):
        return json.dumps(next(self.replies))

    def send(self, obj):
        self.sent.append(json.loads(obj))


def event(name, **kw):
    return {"event": name, "base_resp": {"status_code": 0}, **kw}


class SpeechTests(unittest.TestCase):
    def test_dictionary_merge_and_conflict(self):
        self.assertEqual(speech.merge_tones([["重庆/(chong2)(qing4)"],
                                             ["重庆/(chong2)(qing4)"]]),
                         ["重庆/(chong2)(qing4)"])
        with self.assertRaises(speech.SpeechError):
            speech.merge_tones([["重庆/a"], ["重庆/b"]])

    def test_profile_dictionary_reaches_request(self):
        with tempfile.TemporaryDirectory() as name:
            profile = Path(name) / "profile.json"
            profile.write_text(json.dumps({"voice_id": "test",
                                          "pronunciation_dict": {"tone": ["重庆/a"]}}),
                               encoding="utf-8")
            _, _, _, body = speech.resolve(
                {"text": "重庆。", "pronunciation_dict": {"tone": ["宁夏/b"]}}, [profile])
            self.assertEqual(body["pronunciation_dict"]["tone"], ["重庆/a", "宁夏/b"])
            self.assertNotIn("direction", body)

    def test_model_emotion_and_normalization_guards(self):
        for field in ({"model": "speech-2.8-turbo"},
                      {"voice_setting": {"emotion": "whisper"}},
                      {"transport": "websocket", "text_normalization_mode": "quality"},
                      {"voice_setting": {"speed": float("nan")}}):
            with self.subTest(field=field), self.assertRaises(speech.SpeechError):
                speech.resolve({"text": "测试。", "voice_id": "test", **field})

    def test_pause_and_tag_validation(self):
        speech.validate_text("欢迎。<#0.35#>继续。(chuckle)")
        for text in ("<#0.3#>欢迎", "欢迎<#0.3#>", "欢迎<#100#>继续",
                     "欢迎<#0.123#>继续", "欢迎<#0.2#><#0.3#>继续",
                     "欢迎(whistles)继续"):
            with self.subTest(text=text), self.assertRaises(speech.SpeechError):
                speech.validate_text(text)

    def test_credential_text_rejected_before_archiving(self):
        with self.assertRaises(speech.SpeechError):
            speech.resolve({"text": "测试。", "voice_id": "test",
                            "direction": "sk-api-example"})

    def test_business_error_is_not_retried(self):
        response = io.BytesIO(json.dumps(
            {"base_resp": {"status_code": 1004, "status_msg": "bad key"}}).encode())
        response.headers = {}
        with patch.object(speech.urllib.request, "build_opener") as build:
            build.return_value.open.return_value = response
            with self.assertRaises(speech.SpeechError):
                speech.post(speech.HTTP_URL, {}, "dummy")
            self.assertEqual(build.return_value.open.call_count, 1)

    def test_http_audio_survives_subtitle_failure(self):
        response = {"data": {"audio": "010203", "subtitle_file": "https://example.invalid"},
                    "trace_id": "test", "extra_info": {"usage_characters": 2}}
        with tempfile.TemporaryDirectory() as name, \
                patch.object(speech, "post", return_value=response), \
                patch.object(speech, "download_subtitles", side_effect=OSError("offline")):
            state = {}
            raw = speech.synthesize_http(
                {"audio_setting": {"format": "mp3"}, "subtitle_enable": True},
                "dummy", Path(name), state)
            self.assertEqual(raw, b"\x01\x02\x03")
            self.assertTrue((Path(name) / "audio.mp3").is_file())
            self.assertEqual(state["status"], "audio_complete")
            self.assertEqual(len(state["warnings"]), 1)

    def test_srt_removes_controls_and_rejects_overlap(self):
        with tempfile.TemporaryDirectory() as name:
            out = Path(name)
            speech.export_subtitles([{"text": "好。(chuckle)", "time_begin": 0,
                                      "time_end": 200}], out)
            self.assertNotIn("(chuckle)", (out / "subtitles.srt").read_text(encoding="utf-8"))
            with self.assertRaises(speech.SpeechError):
                speech.export_subtitles([
                    {"text": "一", "time_begin": 0, "time_end": 500},
                    {"text": "二", "time_begin": 100, "time_end": 600}], out)

    def test_ws_drains_finish_and_offsets_second_segment(self):
        pcm = b"\x01\x00" * 3200  # 100 ms at 32 kHz
        sub = {"text": "测试", "text_begin": 0, "time_begin": 0, "time_end": 90}
        fake = FakeWS([
            event("connected_success"), event("task_started"),
            event("task_continued", data={"audio": pcm.hex(), "subtitle": sub}),
            event("task_continued", is_final=True, extra_info={"usage_characters": 4}),
            event("task_continued", data={"audio": pcm.hex(), "subtitle": sub}),
            event("task_continued", is_final=True, extra_info={"usage_characters": 5}),
            event("task_continued", data={"audio": "0100"}),
            event("task_finished"),
        ])
        _, _, texts, body = speech.resolve(
            {"transport": "websocket", "segments": ["第一段。", "第二段。"],
             "voice_id": "test", "audio_setting": {"format": "pcm"}})
        with tempfile.TemporaryDirectory() as name, \
                patch("websockets.sync.client.connect", return_value=fake):
            out = Path(name)
            state = {}
            speech.synthesize_ws(body, texts, "dummy", out, state)
            self.assertEqual([obj["event"] for obj in fake.sent],
                             ["task_start", "task_continue", "task_continue", "task_finish"])
            with wave.open(str(out / "audio.master.wav"), "rb") as audio:
                self.assertEqual(audio.getnframes(), 6401)
            timeline = speech.load(out / "subtitles.timeline.json")
            self.assertEqual(timeline[1]["time_begin"], 100)
            self.assertEqual(state["usage_characters_total"], 9)
            self.assertEqual(list(fake.replies), [])

    def test_incomplete_ws_cannot_be_repaired_as_complete(self):
        with tempfile.TemporaryDirectory() as name:
            out = Path(name)
            raw = out / "stream.raw.pcm"
            raw.write_bytes(b"\0\0")
            (out / "events.jsonl").write_text(
                json.dumps({"direction": "send", "event": "task_continue"}) + "\n")
            with self.assertRaises(speech.SpeechError):
                speech.finalize_websocket(
                    out, {"audio_setting": {"format": "pcm"}}, raw)


if __name__ == "__main__":
    unittest.main(verbosity=2)
