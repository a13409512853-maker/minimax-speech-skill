import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

SCRIPT = Path(__file__).resolve().parents[1] / "skills/minimax-speech/scripts"
sys.path.insert(0, str(SCRIPT))
import minimax_speech as speech


def make_wav(path, seconds):
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\0\0" * round(8000 * seconds))
    return path


class VoiceCreationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.design = {"prompt": "Clear, warm adult narrator.",
                       "preview_text": "Welcome to our campus."}
        self.clone = {"authorized": True, "file_id": 123, "voice_id": "CampusVoice001"}

    def resolve(self, config, operation="voice-clone"):
        return speech.resolve_creation(config, operation, self.root)

    def invoke(self, config, operation, name="result", dry_run=False):
        job = self.root / (name + ".json")
        job.write_text(json.dumps(config), encoding="utf-8")
        args = argparse.Namespace(job=str(job), command=operation, dry_run=dry_run,
                                  out=str(self.root / name), credential_file=None)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            speech.create_voice(args)
        return self.root / name, json.loads(output.getvalue())

    def test_design_schema_and_limit(self):
        payload, uploads = self.resolve(self.design, "voice-design")
        self.assertEqual(payload, self.design)
        self.assertEqual(uploads, [])
        self.resolve({**self.design, "preview_text": "a" * 500}, "voice-design")
        for field in ({"model": speech.MODEL}, {"instructions": "warm"},
                      {"preview_text": "a" * 501}, {"prompt": " "},
                      {"aigc_watermark": 1}, {"voice_id": ""}):
            with self.subTest(field=field), self.assertRaises(speech.SpeechError):
                self.resolve({**self.design, **field}, "voice-design")

    def test_clone_requires_consent_and_valid_unique_id_shape(self):
        for field in ({"authorized": False}, {"authorized": 1},
                      {"voice_id": "short"}, {"voice_id": "1CampusVoice"},
                      {"voice_id": "CampusVoice_"}, {"voice_id": "Campus Voice"},
                      {"voice_id": "A" * 257}, {"file_id": True}, {"file_id": 0},
                      {"audio_path": "also.wav"}):
            with self.subTest(field=field), self.assertRaises(speech.SpeechError):
                self.resolve({**self.clone, **field})
        for voice_id in ("A1234567", "A" * 256, "Voice-001", "Voice_001"):
            payload, _ = self.resolve({**self.clone, "voice_id": voice_id})
            self.assertEqual(payload["voice_id"], voice_id)
            self.assertNotIn("authorized", payload)

    def test_clone_preview_model_and_asr_validation(self):
        payload, _ = self.resolve({**self.clone, "text": "Hello.(crying)",
                                   "text_validation": "Hello.", "accuracy": 0})
        self.assertEqual(payload["model"], speech.MODEL)
        self.assertEqual(payload["accuracy"], 0)
        self.assertNotIn("model", self.resolve(self.clone)[0])
        for field in ({"model": speech.MODEL}, {"text": "x" * 1001},
                      {"text": "Hello.", "model": "speech-2.8-turbo"},
                      {"accuracy": 0.7}, {"text_validation": "x" * 201},
                      {"text_validation": "Hello.", "accuracy": float("nan")},
                      {"need_noise_reduction": "true"}, {"language_boost": ""}):
            with self.subTest(field=field), self.assertRaises(speech.SpeechError):
                self.resolve({**self.clone, **field})

    def test_prompt_requires_paired_audio_and_punctuated_transcript(self):
        payload, _ = self.resolve({**self.clone, "clone_prompt":
                                  {"prompt_audio": 456, "prompt_text": "Hello."}})
        self.assertEqual(payload["clone_prompt"]["prompt_audio"], 456)
        for prompt in ({}, {"prompt_audio": 456, "prompt_text": "Hello"},
                       {"prompt_audio": 456, "prompt_text": "Hello.", "extra": True},
                       {"prompt_audio": 456, "audio_path": "x.wav", "prompt_text": "Hello."},
                       {"prompt_audio": False, "prompt_text": "Hello."}):
            with self.subTest(prompt=prompt), self.assertRaises(speech.SpeechError):
                self.resolve({**self.clone, "clone_prompt": prompt})

    def test_wav_duration_boundaries_and_relative_path(self):
        path = self.root / "main.wav"
        config = {k: v for k, v in self.clone.items() if k != "file_id"}
        config["audio_path"] = "main.wav"
        for seconds in (10, 300):
            make_wav(path, seconds)
            payload, uploads = self.resolve(config)
            self.assertEqual(uploads[0]["duration_seconds"], seconds)
            self.assertEqual(uploads[0]["path"], str(path.resolve()))
            self.assertNotIn("audio_path", payload)
        for seconds in (9.99, 300.01):
            make_wav(path, seconds)
            with self.subTest(seconds=seconds), self.assertRaises(speech.SpeechError):
                self.resolve(config)
        for seconds in (0.01, 7.99):
            make_wav(path, seconds)
            speech.inspect_reference(path, "prompt_audio", self.root)
        for seconds in (0, 8):
            make_wav(path, seconds)
            with self.subTest(seconds=seconds), self.assertRaises(speech.SpeechError):
                speech.inspect_reference(path, "prompt_audio", self.root)

    def test_invalid_oversized_and_truncated_recordings_are_rejected(self):
        path = self.root / "main.wav"
        path.write_bytes(b"not a WAV")
        with self.assertRaises(speech.SpeechError):
            speech.inspect_reference(path, "voice_clone", self.root)
        make_wav(path, 10)
        with path.open("r+b") as audio:
            audio.truncate(100)
        with self.assertRaisesRegex(speech.SpeechError, "truncated"):
            speech.inspect_reference(path, "voice_clone", self.root)
        with path.open("wb") as audio:
            audio.truncate(20_000_001)
        with self.assertRaisesRegex(speech.SpeechError, "20 MB"):
            speech.inspect_reference(path, "voice_clone", self.root)
        path = self.root / "main.ogg"
        path.write_bytes(b"audio")
        with self.assertRaises(speech.SpeechError):
            speech.inspect_reference(path, "voice_clone", self.root)

    def test_mp3_duration_uses_ffprobe_without_shell(self):
        path = self.root / "main.mp3"
        path.write_bytes(b"ID3fixture")
        probe = self.root / "ffprobe"
        probe.touch()
        result = argparse.Namespace(returncode=0, stdout=b'{"format":{"duration":"10.5"}}')
        with patch.dict(os.environ, {"MINIMAX_FFPROBE": str(probe)}), \
                patch.object(speech.subprocess, "run", return_value=result) as run:
            reference = speech.inspect_reference(path, "voice_clone", self.root)
        self.assertEqual(reference["duration_seconds"], 10.5)
        self.assertTrue(Path(run.call_args.args[0][-1]).samefile(path))
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_dry_run_never_reads_credentials_writes_output_or_calls_network(self):
        for operation, config in (("voice-design", self.design), ("voice-clone", self.clone)):
            with self.subTest(operation=operation), \
                    patch.object(speech, "key_for") as key, \
                    patch.object(speech, "post") as post, \
                    patch.object(speech, "upload_reference") as upload:
                out, result = self.invoke(config, operation, name=operation, dry_run=True)
                self.assertFalse(result["network_request"])
                self.assertFalse(out.exists())
                key.assert_not_called()
                post.assert_not_called()
                upload.assert_not_called()

    def test_design_request_uses_bearer_and_json(self):
        response = io.BytesIO(json.dumps({"base_resp": {"status_code": 0}}).encode())
        response.headers = {}
        with patch.object(speech.urllib.request, "build_opener") as build:
            build.return_value.open.return_value = response
            speech.post(speech.DESIGN_URL, self.design, "fictional-test")
        request = build.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, speech.DESIGN_URL)
        self.assertEqual(request.get_header("Authorization"), "Bearer fictional-test")
        self.assertEqual(json.loads(request.data), self.design)
        with self.assertRaises(speech.SpeechError):
            speech.post("https://example.invalid", {}, "fictional-test")

    def test_multipart_upload_has_purpose_binary_and_generic_filename(self):
        path = make_wav(self.root / "private-personal-name.wav", 10)
        reference = speech.inspect_reference(path, "voice_clone", self.root)
        with patch.object(speech, "request_json") as request:
            speech.upload_reference(reference, "fictional-test")
        url, data, content_type, key = request.call_args.args
        self.assertEqual(url, speech.UPLOAD_URL)
        self.assertEqual(key, "fictional-test")
        self.assertTrue(content_type.startswith("multipart/form-data; boundary="))
        self.assertIn(b"\r\n\r\nvoice_clone\r\n", data)
        self.assertIn(b'filename="reference.wav"', data)
        self.assertIn(path.read_bytes(), data)
        self.assertNotIn(b"private-personal-name", data)
        path.write_bytes(b"changed after validation")
        with patch.object(speech, "request_json") as request:
            with self.assertRaises(speech.SpeechError):
                speech.upload_reference(reference, "fictional-test")
            request.assert_not_called()

    def test_design_hex_audio_and_reusable_profile(self):
        raw = b"ID3mock-preview"
        response = {"voice_id": "DesignedVoice001", "trial_audio": raw.hex()}
        with patch.object(speech, "key_for", return_value="fictional-test"), \
                patch.object(speech, "post", return_value=response) as post:
            out, result = self.invoke(self.design, "voice-design")
        self.assertEqual(post.call_args.args[0], speech.DESIGN_URL)
        self.assertEqual(post.call_args.args[1], self.design)
        self.assertEqual((out / "preview.mp3").read_bytes(), raw)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["listening_review"], "pending")
        _, _, _, body = speech.resolve({"text": "Hello."}, [out / "profile.json"])
        self.assertEqual(body["voice_setting"]["voice_id"], "DesignedVoice001")
        self.assertEqual(body["model"], speech.MODEL)
        saved = speech.load(out / "response.json")
        self.assertEqual(saved["trial_audio"], {"hex_characters": len(raw.hex())})

    def test_clone_uploads_both_references_and_preserves_file_ids(self):
        make_wav(self.root / "main.wav", 10)
        make_wav(self.root / "prompt.wav", 3)
        config = {"authorized": True, "voice_id": "CampusVoice001", "audio_path": "main.wav",
                  "clone_prompt": {"audio_path": "prompt.wav", "prompt_text": "Hello."},
                  "text": "Welcome."}
        with patch.object(speech, "key_for", return_value="fictional-test"), \
                patch.object(speech, "upload_reference", side_effect=[
                    {"file": {"file_id": 100}}, {"file": {"file_id": 200}}]) as upload, \
                patch.object(speech, "post", return_value={
                    "input_sensitive": {"type": 0}, "demo_audio": "https://example.invalid/signed",
                    "extra_info": {"usage_characters": 8}}) as post, \
                patch.object(speech, "download_demo", return_value=b"ID3mock") as download:
            out, result = self.invoke(config, "voice-clone")
        self.assertEqual([call.args[0]["purpose"] for call in upload.call_args_list],
                         ["voice_clone", "prompt_audio"])
        url, payload, _ = post.call_args.args
        self.assertEqual(url, speech.CLONE_URL)
        self.assertEqual(payload["file_id"], 100)
        self.assertEqual(payload["clone_prompt"], {"prompt_audio": 200, "prompt_text": "Hello."})
        self.assertNotIn("authorized", payload)
        self.assertNotIn("audio_path", payload)
        self.assertEqual(result["status"], "completed")
        self.assertEqual([x["file_id"] for x in result["uploaded_files"]], [100, 200])
        self.assertEqual(speech.load(out / "request.json"), payload)
        self.assertEqual(result["extra_info"]["usage_characters"], 8)
        download.assert_called_once()
        self.assertNotIn("https://example.invalid/signed",
                         (out / "response.json").read_text(encoding="utf-8"))

    def test_clone_without_preview_does_not_download_or_synthesize(self):
        with patch.object(speech, "key_for", return_value="fictional-test"), \
                patch.object(speech, "post", return_value={"input_sensitive": False}) as post, \
                patch.object(speech, "download_demo") as download:
            out, result = self.invoke(self.clone, "voice-clone")
        post.assert_called_once()
        download.assert_not_called()
        self.assertTrue(result["voice_created"])
        self.assertFalse(list(out.glob("preview.*")))
        self.assertEqual(speech.load(out / "profile.json")["voice_id"], "CampusVoice001")

    def test_created_voice_survives_missing_or_invalid_design_preview(self):
        for index, audio in enumerate((None, "not hex", " ")):
            with self.subTest(audio=audio), \
                    patch.object(speech, "key_for", return_value="fictional-test"), \
                    patch.object(speech, "post", return_value={
                        "voice_id": "DesignedVoice001", "trial_audio": audio}) as post:
                out, result = self.invoke(self.design, "voice-design", name=f"design-{index}")
                self.assertEqual(result["status"], "completed_with_warnings")
                self.assertTrue(result["voice_created"])
                self.assertTrue((out / "profile.json").is_file())
                post.assert_called_once()

    def test_created_clone_survives_preview_download_failure(self):
        with patch.object(speech, "key_for", return_value="fictional-test"), \
                patch.object(speech, "post", return_value={"input_sensitive": False}) as post, \
                patch.object(speech, "download_demo", side_effect=OSError("offline")):
            out, result = self.invoke({**self.clone, "text": "Hello."}, "voice-clone")
        self.assertEqual(result["status"], "completed_with_warnings")
        self.assertTrue((out / "profile.json").is_file())
        post.assert_called_once()

    def test_sensitive_audio_does_not_claim_voice_creation(self):
        for index, response in enumerate(({"input_sensitive": True},
                                         {"input_sensitive": {"type": 2}},
                                         {"input_sensitive_type": 1})):
            name = f"sensitive-{index}"
            with self.subTest(response=response), \
                    patch.object(speech, "key_for", return_value="fictional-test"), \
                    patch.object(speech, "post", return_value=response):
                with self.assertRaises(speech.SpeechError):
                    self.invoke(self.clone, "voice-clone", name=name)
                out = self.root / name
                self.assertFalse(speech.load(out / "job.json")["voice_created"])
                self.assertFalse((out / "profile.json").exists())

    def test_unknown_creation_result_is_never_retried_and_upload_id_survives(self):
        make_wav(self.root / "main.wav", 10)
        config = {k: v for k, v in self.clone.items() if k != "file_id"}
        config["audio_path"] = "main.wav"
        with patch.object(speech, "key_for", return_value="fictional-test"), \
                patch.object(speech, "upload_reference", return_value={"file": {"file_id": 100}}), \
                patch.object(speech, "post", side_effect=TimeoutError("unknown")) as post:
            with self.assertRaises(TimeoutError):
                self.invoke(config, "voice-clone")
        state = speech.load(self.root / "result/job.json")
        self.assertEqual(state["status"], "failed_or_result_unknown")
        self.assertEqual(state["uploaded_files"][0]["file_id"], 100)
        self.assertEqual(speech.load(self.root / "result/request.json")["file_id"], 100)
        post.assert_called_once()

    def test_unknown_upload_result_is_never_retried_or_cloned(self):
        make_wav(self.root / "main.wav", 10)
        config = {k: v for k, v in self.clone.items() if k != "file_id"}
        config["audio_path"] = "main.wav"
        with patch.object(speech, "key_for", return_value="fictional-test"), \
                patch.object(speech, "upload_reference", side_effect=TimeoutError("unknown")) as upload, \
                patch.object(speech, "post") as post:
            with self.assertRaises(TimeoutError):
                self.invoke(config, "voice-clone")
        self.assertEqual(speech.load(self.root / "result/job.json")["status"],
                         "failed_or_result_unknown")
        upload.assert_called_once()
        post.assert_not_called()

    def test_demo_download_uses_https_without_authorization(self):
        response = io.BytesIO(b"ID3mock")
        with patch.object(speech.urllib.request, "build_opener") as build:
            build.return_value.open.return_value = response
            self.assertEqual(speech.download_demo("https://example.invalid/audio"), b"ID3mock")
            self.assertEqual(build.return_value.open.call_args.args[0],
                             "https://example.invalid/audio")
        for url in ("http://example.invalid/audio", None, "file:///tmp/audio"):
            with self.subTest(url=url), self.assertRaises(speech.SpeechError):
                speech.download_demo(url)


if __name__ == "__main__":
    unittest.main(verbosity=2)
