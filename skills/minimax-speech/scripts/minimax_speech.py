#!/usr/bin/env python3
"""MiniMax Speech: TTS, voice design, cloning, and OS-encrypted credentials."""

import argparse
import copy
from datetime import datetime, timezone
import getpass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import warnings
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave

import credentials

MODEL = "speech-2.8-hd"
HTTP_URL = "https://api.minimax.cn/v1/t2a_v2"
WS_URL = "wss://api.minimax.cn/ws/v1/t2a_v2"
VOICE_URL = "https://api.minimax.cn/v1/get_voice"
DESIGN_URL = "https://api.minimax.cn/v1/voice_design"
CLONE_URL = "https://api.minimax.cn/v1/voice_clone"
UPLOAD_URL = "https://api.minimax.cn/v1/files/upload"
EMOTIONS = {"happy", "sad", "angry", "fearful", "disgusted", "surprised", "calm"}
TAGS = {
    "laughs", "chuckle", "coughs", "clear-throat", "groans", "breath", "pant",
    "inhale", "exhale", "gasps", "sniffs", "sighs", "snorts", "burps",
    "lip-smacking", "humming", "hissing", "emm", "sneezes",
}
PAUSE = re.compile(r"<#(\d+(?:\.\d{1,2})?)#>")
ACTIVE_KEY = ""


class SpeechError(Exception):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def clean(value):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key.lower() in {"authorization", "api_key", "apikey", "access_token"}:
                result[key] = "[REDACTED]"
            elif key in {"audio", "trial_audio"} and isinstance(item, str):
                result[key] = {"hex_characters": len(item)}
            elif key in {"subtitle_file", "demo_audio"} and isinstance(item, str):
                result[key] = "[temporary result URL omitted]" if item else ""
            else:
                result[key] = clean(item)
        return result
    if isinstance(value, list):
        return [clean(item) for item in value]
    if isinstance(value, str):
        if ACTIVE_KEY:
            value = value.replace(ACTIVE_KEY, "[REDACTED]")
        return re.sub(r"sk-api-[A-Za-z0-9_-]+", "[REDACTED]", value)
    return value


def dump(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(obj), ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def runtime_path():
    if os.name == "nt":
        return Path(os.environ["LOCALAPPDATA"]) / "MiniMaxSpeech" / "runtime.json"
    return Path.home() / ".config" / "minimax-speech" / "runtime.json"


def find_ffmpeg():
    configured = os.environ.get("MINIMAX_FFMPEG") or shutil.which("ffmpeg")
    if not configured and runtime_path().is_file():
        configured = load(runtime_path()).get("ffmpeg")
    if not configured or not Path(configured).is_file():
        raise SpeechError("WebSocket MP3/FLAC finalization requires FFmpeg. "
                          "Set MINIMAX_FFMPEG or run configure-runtime --ffmpeg PATH. "
                          "PCM uses the standard library instead.")
    return str(Path(configured).resolve())


def run_ffmpeg(arguments):
    result = subprocess.run(
        [find_ffmpeg(), "-hide_banner", "-nostdin", "-v", "error", "-y", *arguments],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise SpeechError("FFmpeg failed: " +
                          result.stderr.decode("utf-8", errors="replace")[-2000:])


def key_for(path=None):
    key = credentials.get_key(path)
    global ACTIVE_KEY
    ACTIVE_KEY = key
    return key


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SpeechError("API redirect refused; credential was not forwarded.")


def check_response(obj):
    base = obj.get("base_resp")
    if not isinstance(base, dict) or base.get("status_code") != 0:
        code = base.get("status_code") if isinstance(base, dict) else "missing"
        message = base.get("status_msg", "") if isinstance(base, dict) else ""
        raise SpeechError(f"MiniMax status {code}: {clean(message)}; "
                          f"trace_id={obj.get('trace_id', '')}")


def request_json(url, data, content_type, key, timeout=90):
    # Only these fixed official endpoints receive the Authorization header.
    if url not in {HTTP_URL, VOICE_URL, DESIGN_URL, CLONE_URL, UPLOAD_URL}:
        raise SpeechError("Unapproved API endpoint.")
    req = urllib.request.Request(
        url, data=data,
        headers={"Authorization": "Bearer " + key,
                 "Content-Type": content_type}, method="POST")
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=timeout) as res:
            obj = json.load(res)
            if res.headers.get("trace_id") and "trace_id" not in obj:
                obj["trace_id"] = res.headers["trace_id"]
    except urllib.error.HTTPError as exc:
        try:
            details = clean(json.loads(exc.read()))
        except (ValueError, UnicodeError):
            details = {"message": "non-JSON error body omitted"}
        raise SpeechError(f"HTTP {exc.code}: {json.dumps(details, ensure_ascii=False)}")
    check_response(obj)
    return obj


def post(url, payload, key, timeout=90):
    return request_json(url, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                        "application/json", key, timeout)


def merge(base, override):
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def tones_of(value):
    if isinstance(value, dict):
        value = value.get("tone", [])
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise SpeechError("Pronunciation dictionary must contain a tone string list.")
    return value


def merge_tones(sources):
    result = {}
    for source in sources:
        for entry in tones_of(source):
            term, separator, pronunciation = entry.partition("/")
            if not separator or not term or not pronunciation:
                raise SpeechError("Dictionary entry must be term/pronunciation.")
            if term in result and result[term] != entry:
                raise SpeechError(f"Conflicting pronunciation for {term!r}.")
            result[term] = entry
    return list(result.values())


def numeric(value, low, high, name, integer=False, exclusive_low=False):
    valid = isinstance(value, (int, float)) and not isinstance(value, bool)
    if not valid or not math.isfinite(value):
        raise SpeechError(name + " must be a finite number.")
    if value < low or value > high or (exclusive_low and value == low):
        raise SpeechError(name + " is outside the supported range.")
    if integer and not isinstance(value, int):
        raise SpeechError(name + " must be an integer.")


def validate_text(text, tags=TAGS):
    if not isinstance(text, str) or not text.strip() or len(text) >= 10000:
        raise SpeechError("Each text must contain 1-9999 characters.")
    if "sk-api-" in text:
        raise SpeechError("Credential-like text refused.")
    residual = PAUSE.sub("", text)
    if "<#" in residual or "#>" in residual:
        raise SpeechError("Malformed pause; use <#0.35#> with up to two decimals.")
    matches = list(PAUSE.finditer(text))
    for match in matches:
        numeric(float(match.group(1)), 0.01, 99.99, "pause")
        before = PAUSE.sub("", text[:match.start()])
        after = PAUSE.sub("", text[match.end():])
        if not re.search(r"\w", before) or not re.search(r"\w", after):
            raise SpeechError("Pauses must be between speakable text.")
    if re.search(r"<#[^>]+#>\s*<#[^>]+#>", text):
        raise SpeechError("Consecutive pauses are not supported.")
    for name in re.findall(r"\(([a-z][a-z-]*)\)", text):
        if name not in tags:
            raise SpeechError(f"Unknown English parenthetical/tag ({name}); "
                              "remove it or use a documented tag.")


def resolve(config, profiles=(), dictionaries=()):
    result = {}
    tone_sources = []
    for profile in profiles:
        obj = load(profile)
        if not isinstance(obj, dict):
            raise SpeechError("Profile must be a JSON object.")
        tone_sources.append(obj.get("pronunciation_dict", []))
        result = merge(result, obj)
    if not isinstance(config, dict):
        raise SpeechError("Job must be a JSON object.")
    result = merge(result, config)
    allowed = {"model", "transport", "text", "segments", "original_text", "direction",
               "voice_id", "voice_setting", "audio_setting", "language_boost",
               "text_normalization_mode", "subtitle_enable", "subtitle_type",
               "pronunciation_dict"}
    unknown = set(result) - allowed
    if unknown:
        raise SpeechError("Unsupported job fields: " + ", ".join(sorted(unknown)))
    if "sk-api-" in json.dumps(result, ensure_ascii=False):
        raise SpeechError("Credential-like content refused in job/profile.")
    if result.get("model", MODEL) != MODEL:
        raise SpeechError("This skill is fixed to " + MODEL + ".")
    transport = result.get("transport", "http")
    if transport not in {"http", "websocket"}:
        raise SpeechError("transport must be http or websocket.")
    if "text" in result and "segments" in result:
        raise SpeechError("Choose text or segments, not both.")
    texts = result.get("segments", [result.get("text", "")])
    if not isinstance(texts, list) or not texts:
        raise SpeechError("segments must be a nonempty list.")
    if transport == "http" and len(texts) != 1:
        raise SpeechError("HTTP accepts one text; use separate jobs for long documents.")
    for text in texts:
        validate_text(text)
    voice = merge({"voice_id": result.get("voice_id", ""),
                   "speed": 1.0, "vol": 1.0, "pitch": 0},
                  result.get("voice_setting", {}))
    if set(voice) - {"voice_id", "speed", "vol", "pitch", "emotion"}:
        raise SpeechError("Unknown voice_setting field.")
    if not isinstance(voice["voice_id"], str) or not voice["voice_id"].strip():
        raise SpeechError("Specify a real voice_id from the voice query.")
    numeric(voice["speed"], 0.5, 2, "speed")
    numeric(voice["vol"], 0, 10, "vol", exclusive_low=True)
    numeric(voice["pitch"], -12, 12, "pitch", integer=True)
    if "emotion" in voice and voice["emotion"] not in EMOTIONS:
        raise SpeechError("Unsupported Speech 2.8 emotion.")
    audio = merge({"sample_rate": 32000, "bitrate": 128000,
                   "format": "mp3", "channel": 1}, result.get("audio_setting", {}))
    if set(audio) - {"sample_rate", "bitrate", "format", "channel"}:
        raise SpeechError("Unknown audio_setting field.")
    if audio["sample_rate"] not in {8000, 16000, 22050, 24000, 32000, 44100}:
        raise SpeechError("Unsupported sample_rate.")
    if audio["bitrate"] not in {32000, 64000, 128000, 256000}:
        raise SpeechError("Unsupported bitrate.")
    formats = {"mp3", "flac", "pcm"} if transport == "websocket" else {
        "mp3", "flac", "pcm", "wav"}
    if audio["format"] not in formats or audio["channel"] not in {1, 2}:
        raise SpeechError("Unsupported audio format/channel for this transport.")
    normalization = result.get("text_normalization_mode",
                               "quality" if transport == "http" else "basic")
    if normalization not in {"quality", "basic"}:
        raise SpeechError("Unknown text_normalization_mode.")
    if transport == "websocket" and normalization != "basic":
        raise SpeechError("WebSocket uses basic normalization.")
    subtitle = result.get("subtitle_enable", True)
    if not isinstance(subtitle, bool):
        raise SpeechError("subtitle_enable must be true or false.")
    subtitle_type = result.get("subtitle_type", "sentence")
    if subtitle_type not in {"sentence", "word", "word_streaming"}:
        raise SpeechError("Unsupported subtitle_type.")
    if transport == "http" and subtitle_type == "word_streaming":
        raise SpeechError("word_streaming requires WebSocket in this client.")
    language = result.get("language_boost", "Chinese")
    if not isinstance(language, str):
        raise SpeechError("language_boost must be a string.")
    for field in ("original_text", "direction"):
        if field in result and not isinstance(result[field], str):
            raise SpeechError(field + " must be a string.")
    tone_sources.extend(load(path) for path in dictionaries)
    tone_sources.append(config.get("pronunciation_dict", []))
    tones = merge_tones(tone_sources)
    payload = {"model": MODEL, "voice_setting": voice, "audio_setting": audio,
               "language_boost": language, "text_normalization_mode": normalization,
               "subtitle_enable": subtitle, "subtitle_type": subtitle_type}
    if tones:
        payload["pronunciation_dict"] = {"tone": tones}
    if transport == "http":
        payload.update(text=texts[0], stream=False, output_format="hex")
    else:
        payload["event"] = "task_start"
    return result, transport, texts, payload


def creation_string(value, name, limit=None):
    if not isinstance(value, str) or not value.strip():
        raise SpeechError(name + " must be a nonempty string.")
    if limit is not None and len(value) > limit:
        raise SpeechError(f"{name} must contain at most {limit} characters.")
    return value


def creation_id(value, name):
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise SpeechError(name + " must be a positive integer.")
    return value


def inspect_reference(filename, purpose, base):
    path = Path(filename).expanduser()
    if not path.is_absolute():
        path = base / path
    path = path.resolve()
    if not path.is_file() or path.suffix.lower() not in {".mp3", ".m4a", ".wav"}:
        raise SpeechError("Reference must be an existing MP3, M4A, or WAV file.")
    size = path.stat().st_size
    if not 0 < size <= 20_000_000:
        raise SpeechError("Reference must be nonempty and no larger than 20 MB.")
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as audio:
                duration = audio.getnframes() / audio.getframerate()
                expected = audio.getnframes() * audio.getnchannels() * audio.getsampwidth()
                actual = 0
                while block := audio.readframes(65536):
                    actual += len(block)
                if actual != expected:
                    raise SpeechError("WAV reference is truncated; no upload was sent.")
        except (wave.Error, EOFError):
            raise SpeechError("Cannot read WAV duration; use a valid PCM WAV.") from None
    else:
        probe = os.environ.get("MINIMAX_FFPROBE") or shutil.which("ffprobe")
        if not probe:
            ffmpeg = os.environ.get("MINIMAX_FFMPEG") or shutil.which("ffmpeg")
            if not ffmpeg and runtime_path().is_file():
                ffmpeg = load(runtime_path()).get("ffmpeg")
            if ffmpeg:
                probe = str(Path(ffmpeg).with_name(
                    "ffprobe.exe" if os.name == "nt" else "ffprobe"))
        if not probe or not Path(probe).is_file():
            raise SpeechError("MP3/M4A duration checks require FFprobe. Set "
                              "MINIMAX_FFPROBE, configure FFmpeg with FFprobe beside it, "
                              "or supply PCM WAV.")
        result = subprocess.run(
            [str(probe), "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(path)], capture_output=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            raise SpeechError("FFprobe could not read the reference audio.")
        try:
            duration = float(json.loads(result.stdout)["format"]["duration"])
        except (ValueError, TypeError, KeyError):
            raise SpeechError("Reference has no reliable audio duration.") from None
    if purpose == "voice_clone":
        numeric(duration, 10, 300, "main reference duration (seconds)")
    else:
        numeric(duration, 0, 8, "prompt reference duration (seconds)", exclusive_low=True)
        if duration >= 8:
            raise SpeechError("Prompt reference must be shorter than 8 seconds.")
    return {"path": str(path), "purpose": purpose, "bytes": size,
            "duration_seconds": duration,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def resolve_creation(config, operation, base):
    if not isinstance(config, dict):
        raise SpeechError("Voice creation job must be a JSON object.")
    if "sk-api-" in json.dumps(config, ensure_ascii=False):
        raise SpeechError("Credential-like content refused in voice creation job.")
    boolean_fields = {"aigc_watermark"}
    if operation == "voice-design":
        allowed = {"prompt", "preview_text", "voice_id", *boolean_fields}
    else:
        boolean_fields |= {"need_noise_reduction", "need_volume_normalization"}
        allowed = {"audio_path", "file_id", "voice_id", "authorized", "clone_prompt",
                   "text", "model", "language_boost", "text_validation", "accuracy",
                   *boolean_fields}
    unknown = set(config) - allowed
    if unknown:
        raise SpeechError("Unsupported voice creation fields: " + ", ".join(sorted(unknown)))
    for field in boolean_fields & config.keys():
        if not isinstance(config[field], bool):
            raise SpeechError(field + " must be true or false.")
    payload, uploads = copy.deepcopy(config), []
    if operation == "voice-design":
        creation_string(config.get("prompt"), "prompt")
        creation_string(config.get("preview_text"), "preview_text", 500)
        if "voice_id" in config:
            creation_string(config["voice_id"], "voice_id")
        return payload, uploads
    if config.get("authorized") is not True:
        raise SpeechError("Set authorized=true only after the user confirms the right "
                          "to upload and clone the reference voice.")
    payload.pop("authorized")
    voice_id = creation_string(config.get("voice_id"), "voice_id")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{6,254}[A-Za-z0-9]", voice_id):
        raise SpeechError("Clone voice_id must be 8-256 ASCII characters, start with a "
                          "letter, contain letters/digits/-/_, and end with a letter/digit.")
    if ("audio_path" in config) == ("file_id" in config):
        raise SpeechError("Choose exactly one of audio_path or previously uploaded file_id.")
    if "audio_path" in config:
        creation_string(config["audio_path"], "audio_path")
        uploads.append(inspect_reference(config["audio_path"], "voice_clone", base))
        payload.pop("audio_path")
        payload["file_id"] = "<uploaded voice_clone file_id>"
    else:
        creation_id(config["file_id"], "file_id")
    if "clone_prompt" in config:
        prompt = config["clone_prompt"]
        if not isinstance(prompt, dict) or set(prompt) - {
                "audio_path", "prompt_audio", "prompt_text"}:
            raise SpeechError("clone_prompt accepts audio_path or prompt_audio, plus prompt_text.")
        text = creation_string(prompt.get("prompt_text"), "clone_prompt.prompt_text")
        if not re.search(r"[.!?;:。！？；：…][\"'”’）)]?$", text.rstrip()):
            raise SpeechError("clone_prompt.prompt_text must end with punctuation.")
        if ("audio_path" in prompt) == ("prompt_audio" in prompt):
            raise SpeechError("Choose clone_prompt.audio_path or clone_prompt.prompt_audio.")
        if "audio_path" in prompt:
            creation_string(prompt["audio_path"], "clone_prompt.audio_path")
            uploads.append(inspect_reference(prompt["audio_path"], "prompt_audio", base))
            payload["clone_prompt"] = {"prompt_audio": "<uploaded prompt_audio file_id>",
                                       "prompt_text": text}
        else:
            creation_id(prompt["prompt_audio"], "clone_prompt.prompt_audio")
    if "text" in config:
        creation_string(config["text"], "text", 1000)
        validate_text(config["text"], TAGS | {"whistles", "crying", "applause"})
        if config.get("model", MODEL) != MODEL:
            raise SpeechError("Clone preview model is fixed to " + MODEL + ".")
        payload["model"] = MODEL
    elif "model" in config:
        raise SpeechError("model is only used with clone preview text.")
    if "language_boost" in config:
        creation_string(config["language_boost"], "language_boost")
    if "text_validation" in config:
        creation_string(config["text_validation"], "text_validation", 200)
    if "accuracy" in config:
        if "text_validation" not in config:
            raise SpeechError("accuracy requires text_validation.")
        numeric(config["accuracy"], 0, 1, "accuracy")
    return payload, uploads


def upload_reference(reference, key):
    path = Path(reference["path"])
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != reference["sha256"]:
        raise SpeechError("Reference changed since validation; no upload was sent.")
    boundary = "minimax-speech-" + uuid.uuid4().hex
    purpose = reference["purpose"]
    # A generic filename keeps personal local paths out of multipart headers.
    header = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"purpose\"\r\n\r\n"
              f"{purpose}\r\n--{boundary}\r\n"
              f"Content-Disposition: form-data; name=\"file\"; "
              f"filename=\"reference{path.suffix.lower()}\"\r\n"
              "Content-Type: application/octet-stream\r\n\r\n").encode("ascii")
    body = header + raw + f"\r\n--{boundary}--\r\n".encode("ascii")
    return request_json(UPLOAD_URL, body, "multipart/form-data; boundary=" + boundary,
                        key, timeout=180)


def audio_extension(raw):
    if raw.startswith(b"RIFF") and raw[8:12] == b"WAVE":
        return "wav"
    if raw.startswith(b"fLaC"):
        return "flac"
    if raw.startswith(b"OggS"):
        return "ogg"
    if len(raw) >= 12 and raw[4:8] == b"ftyp":
        return "m4a"
    if raw.startswith(b"ID3") or (len(raw) > 1 and raw[0] == 255 and raw[1] & 224 == 224):
        return "mp3"
    return "bin"


def download_demo(url):
    if not isinstance(url, str) or urllib.parse.urlsplit(url).scheme != "https":
        raise SpeechError("Preview download requires HTTPS.")
    # Signed result downloads never receive the API key.
    with urllib.request.build_opener(NoRedirect).open(url, timeout=45) as response:
        raw = response.read(50_000_001)
    if not raw or len(raw) > 50_000_000:
        raise SpeechError("Preview download was empty or exceeded 50 MB.")
    return raw


def create_voice(args):
    source = Path(args.job).resolve()
    resolved = load(source)
    payload, uploads = resolve_creation(resolved, args.command, source.parent)
    endpoint = DESIGN_URL if args.command == "voice-design" else CLONE_URL
    if args.dry_run:
        print(json.dumps(clean({
            "operation": args.command, "endpoint": endpoint, "request": payload,
            "uploads": uploads, "network_request": False,
            "note": "Upload placeholders are replaced with official file_id values before submission.",
        }), ensure_ascii=False, indent=2))
        return
    if not args.out:
        raise SpeechError("--out NEW_DIRECTORY is required unless --dry-run is used.")
    key = key_for(args.credential_file)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    dump(out / "resolved-job.json", resolved)
    dump(out / "request.json", payload)
    state = {"operation": args.command, "endpoint": endpoint, "created_at": now(),
             "status": "prepared", "uploaded_files": [], "voice_created": False}
    dump(out / "job.json", state)
    try:
        for reference in uploads:
            purpose = reference["purpose"]
            state.update(status="upload_submitted_result_unknown", upload_purpose=purpose)
            dump(out / "job.json", state)
            response = upload_reference(reference, key)
            dump(out / ("upload-" + purpose + ".json"), response)
            file_id = creation_id((response.get("file") or {}).get("file_id"), "uploaded file_id")
            state["uploaded_files"].append(
                {"file_id": file_id, **{k: v for k, v in reference.items() if k != "path"}})
            if purpose == "voice_clone":
                payload["file_id"] = file_id
            else:
                payload["clone_prompt"]["prompt_audio"] = file_id
            state["status"] = "upload_complete"
            dump(out / "request.json", payload)
            dump(out / "job.json", state)
        state["status"] = "submitted_result_unknown"
        dump(out / "job.json", state)
        response = post(endpoint, payload, key, timeout=180)
        dump(out / "response.json", response)
        if args.command == "voice-clone":
            sensitive = response.get("input_sensitive")
            if sensitive is True or (isinstance(sensitive, dict) and sensitive.get("type", 0)) \
                    or response.get("input_sensitive_type", 0):
                raise SpeechError("Official service flagged the reference; voice creation unconfirmed.")
        voice_id = creation_string(
            response.get("voice_id") if args.command == "voice-design" else payload["voice_id"],
            "returned voice_id")
        state.update(status="voice_created", voice_id=voice_id, voice_created=True,
                     trace_id=response.get("trace_id"), extra_info=response.get("extra_info", {}))
        dump(out / "job.json", state)
        dump(out / "voice.json", {"voice_id": voice_id, "operation": args.command,
                                  "created_at": state["created_at"], "tts_model": MODEL})
        dump(out / "profile.json", {"voice_id": voice_id, "model": MODEL})
        notes = []
        try:
            if args.command == "voice-design":
                audio = response.get("trial_audio")
                if not isinstance(audio, str) or not audio:
                    raise SpeechError("Voice created, but no trial_audio was returned.")
                raw = bytes.fromhex(audio)
            elif "text" in payload:
                raw = download_demo(response.get("demo_audio"))
            else:
                raw = None
            if raw is not None:
                if not raw:
                    raise SpeechError("Voice created, but preview audio is empty.")
                extension = audio_extension(raw)
                filename = "preview." + extension
                (out / filename).write_bytes(raw)
                state.update(preview_audio=filename, audio_bytes=len(raw),
                             audio_sha256=hashlib.sha256(raw).hexdigest(),
                             listening_review="pending")
                if extension == "bin":
                    notes.append("Preview preserved as binary; codec could not be identified.")
        except Exception as exc:
            notes.append("Voice created; preview could not be saved: " + str(clean(str(exc))))
        if args.command == "voice-clone":
            state["retention_note"] = (
                "Official docs: cloned voices unused for formal TTS within 7 days are deleted. "
                "Creation/preview is not recorded as formal TTS use; no automatic activation.")
        state.update(status="completed_with_warnings" if notes else "completed",
                     warnings=notes, finished_at=now())
    except (Exception, KeyboardInterrupt) as exc:
        state.update(status="voice_created_with_error" if state["voice_created"]
                     else "failed_or_result_unknown", error=clean(str(exc)), finished_at=now(),
                     retry_note="No automatic retry. Inspect saved responses and uploaded file IDs "
                                "before another request; reuse a created voice instead of recreating it.")
        dump(out / "job.json", state)
        raise
    dump(out / "job.json", state)
    print(json.dumps(clean({"output": str(out), **state}), ensure_ascii=False, indent=2))


def subtitle_rows(obj):
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        for key in ("subtitles", "subtitle", "data"):
            if key in obj:
                return subtitle_rows(obj[key])
        if "text" in obj and ("time_begin" in obj or "begin_time" in obj):
            return [obj]
    raise SpeechError("Unrecognized subtitle JSON; raw file was preserved.")


def caption_time(ms, vtt=False):
    total = round(float(ms))
    hours, remainder = divmod(total, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02}{'.' if vtt else ','}{milliseconds:03}"


def export_subtitles(obj, out):
    rows = subtitle_rows(obj)
    srt, vtt = [], ["WEBVTT\n"]
    previous = -1
    for index, row in enumerate(rows, 1):
        start = row.get("time_begin", row.get("begin_time", row.get("start")))
        end = row.get("time_end", row.get("end_time", row.get("end")))
        if start is None or end is None or start < 0 or end < start or start < previous:
            raise SpeechError("Invalid subtitle timestamps; raw file was preserved.")
        if start < previous - 1:
            raise SpeechError("Overlapping subtitle timestamps; raw file was preserved.")
        previous = end
        text = str(row["text"]).strip()
        text = re.sub(r"\(([a-z][a-z-]*)\)",
                      lambda match: "" if match.group(1) in TAGS else match.group(0),
                      text)
        text = PAUSE.sub("", text)
        srt.append(f"{index}\n{caption_time(start)} --> {caption_time(end)}\n{text}\n")
        vtt.append(f"{caption_time(start, True)} --> {caption_time(end, True)}\n{text}\n")
    (out / "subtitles.srt").write_text("\n".join(srt), encoding="utf-8")
    (out / "subtitles.vtt").write_text("\n".join(vtt), encoding="utf-8")
    return len(rows)


def download_subtitles(url):
    # Signed result URLs receive no API Authorization header.
    if urllib.parse.urlsplit(url).scheme != "https":
        raise SpeechError("Subtitle download requires HTTPS.")
    with urllib.request.urlopen(url, timeout=45) as res:
        return json.load(res)


def finalize_websocket(out, payload, raw_path):
    """Rebuild from recorded chunks without another paid API request."""
    fmt = payload["audio_setting"]["format"]
    settings = payload["audio_setting"]
    records = [json.loads(line) for line in
               (out / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    sizes, subtitles, infos = [], [], []
    current = -1
    for event in records:
        if event.get("direction") == "send" and event.get("event") == "task_continue":
            current += 1
            sizes.append(0)
            subtitles.append({})
        if event.get("direction") != "receive" or current < 0:
            continue
        data = event.get("data") or {}
        if data.get("audio"):
            sizes[current] += data["audio"]["hex_characters"] // 2
        if data.get("subtitle"):
            for row in subtitle_rows(data["subtitle"]):
                subtitles[current][row.get("text_begin", 0)] = row
        if event.get("is_final") and event.get("extra_info"):
            infos.append({"segment": current, **event["extra_info"]})
    if not any(event.get("event") == "task_finished" and
               event.get("direction") == "receive" for event in records):
        raise SpeechError("No task_finished in saved stream; result remains incomplete.")
    if sum(sizes) != raw_path.stat().st_size:
        raise SpeechError("Saved audio size does not match the recorded chunks.")
    parts = out / "segments"
    parts.mkdir(exist_ok=True)
    durations = []
    master_path = out / "audio.master.wav"
    with raw_path.open("rb") as source, wave.open(str(master_path), "wb") as master:
        master.setnchannels(settings["channel"])
        master.setsampwidth(2)
        master.setframerate(settings["sample_rate"])
        for index, size in enumerate(sizes):
            part = parts / f"{index + 1:04}.{fmt}"
            part.write_bytes(source.read(size))
            if not size:
                raise SpeechError("A completed segment contained no audio.")
            if fmt == "pcm":
                pcm = part.read_bytes()
                frame_size = settings["channel"] * 2
                if len(pcm) % frame_size:
                    raise SpeechError("PCM data has an incomplete sample frame.")
                frames = len(pcm) // frame_size
                master.writeframes(pcm)
            else:
                decoded = parts / f"{index + 1:04}.wav"
                run_ffmpeg(["-i", str(part), "-acodec", "pcm_s16le",
                            "-ar", str(settings["sample_rate"]),
                            "-ac", str(settings["channel"]), str(decoded)])
                with wave.open(str(decoded), "rb") as audio:
                    frames = audio.getnframes()
                    while block := audio.readframes(65536):
                        master.writeframes(block)
            durations.append(frames * 1000 / settings["sample_rate"])
    timeline, raw_subtitles, offset = [], [], 0.0
    for index, rows in enumerate(subtitles):
        for row in rows.values():
            raw_subtitles.append({"segment": index, "subtitle": row})
            adjusted = copy.deepcopy(row)
            for field in ("time_begin", "time_end"):
                adjusted[field] += offset
            for word in adjusted.get("timestamped_words") or []:
                for field in ("time_begin", "time_end"):
                    word[field] += offset
            adjusted["segment_index"] = index
            timeline.append(adjusted)
        offset += durations[index]
    warnings = []
    if raw_subtitles:
        dump(out / "subtitles.raw.json", raw_subtitles)
        dump(out / "subtitles.timeline.json", timeline)
        try:
            export_subtitles(timeline, out)
        except SpeechError as exc:
            warnings.append(str(exc))
    elif payload["subtitle_enable"]:
        warnings.append("API returned no WebSocket subtitles.")
    if fmt == "pcm":
        final_path = master_path
    else:
        final_path = out / ("audio." + fmt)
        options = ["-codec:a", "libmp3lame", "-b:a", str(settings["bitrate"])
                   ] if fmt == "mp3" else ["-codec:a", "flac"]
        run_ffmpeg(["-i", str(master_path), *options, str(final_path)])
    return final_path, {
        "segment_decoded_duration_ms": durations, "decoded_duration_ms": sum(durations),
        "segment_extra_info": infos,
        "usage_characters_total": sum(item.get("usage_characters", 0) for item in infos),
        "usage_note": "Sum of final per-task_continue usage records; no currency estimate.",
        "subtitle_count": len(timeline), "warnings": warnings,
        "audio_master": str(master_path.name),
        "audio_final": str(final_path.name),
        "audio_note": "Each segment decoded independently and joined as PCM; "
                      "MP3/FLAC final is encoded once from the PCM master.",
    }


def synthesize_http(payload, key, out, state):
    state["status"] = "submitted_result_unknown"
    dump(out / "job.json", state)
    obj = post(HTTP_URL, payload, key)
    dump(out / "response.json", obj)
    audio = (obj.get("data") or {}).get("audio")
    if not audio:
        raise SpeechError("API returned success without audio.")
    try:
        raw = bytes.fromhex(audio)
    except ValueError:
        raise SpeechError("API returned invalid hexadecimal audio.")
    if not raw:
        raise SpeechError("Decoded audio is empty.")
    (out / ("audio." + payload["audio_setting"]["format"])).write_bytes(raw)
    state.update(status="audio_complete", trace_id=obj.get("trace_id"),
                 extra_info=obj.get("extra_info", {}))
    dump(out / "job.json", state)
    warnings = []
    if payload["subtitle_enable"]:
        url = (obj.get("data") or {}).get("subtitle_file")
        if url:
            try:
                sub = download_subtitles(url)
                dump(out / "subtitles.raw.json", sub)
                state["subtitle_count"] = export_subtitles(sub, out)
            except Exception as exc:
                warnings.append("Audio complete; subtitle retrieval/export failed: "
                                + str(clean(str(exc))))
        else:
            warnings.append("Audio complete; API returned no subtitle_file.")
    state["warnings"] = warnings
    return raw


def synthesize_ws(payload, texts, key, out, state):
    try:
        from websockets.sync.client import connect
    except ImportError:
        raise SpeechError("Install optional WebSocket dependency: "
                          "python -m pip install 'websockets>=15,<18'")
    state["status"] = "submitted_result_unknown"
    dump(out / "job.json", state)
    subtitles = {}
    final_infos = []
    audio_path = out / ("stream.partial." + payload["audio_setting"]["format"])
    traces = []
    segment = 0
    with (out / "events.jsonl").open("w", encoding="utf-8") as log:
        with audio_path.open("wb") as audio_file:
            with connect(WS_URL, additional_headers={"Authorization": "Bearer " + key},
                         open_timeout=30, close_timeout=10, max_size=32 * 1024 * 1024,
                         proxy=None) as ws:
                def send(message):
                    log.write(json.dumps({"at": now(), "direction": "send",
                                          **clean(message)}, ensure_ascii=False) + "\n")
                    log.flush()
                    ws.send(json.dumps(message, ensure_ascii=False))

                def receive():
                    obj = json.loads(ws.recv(timeout=90))
                    log.write(json.dumps({"at": now(), "direction": "receive",
                                          **clean(obj)}, ensure_ascii=False) + "\n")
                    log.flush()
                    check_response(obj)
                    if obj.get("event") == "task_failed":
                        raise SpeechError("WebSocket task_failed.")
                    if obj.get("trace_id"):
                        traces.append(obj["trace_id"])
                    data = obj.get("data") or {}
                    if data.get("audio"):
                        audio_file.write(bytes.fromhex(data["audio"]))
                        audio_file.flush()
                    for sub in ([data["subtitle"]] if data.get("subtitle") else []):
                        for row in subtitle_rows(sub):
                            subtitles[(segment, row.get("text_begin", 0))] = row
                    if obj.get("is_final") and obj.get("extra_info"):
                        final_infos.append({"segment": segment, **obj["extra_info"]})
                    return obj

                if receive().get("event") != "connected_success":
                    raise SpeechError("Expected connected_success.")
                send(payload)
                if receive().get("event") != "task_started":
                    raise SpeechError("Expected task_started.")
                for segment, text in enumerate(texts):
                    send({"event": "task_continue", "text": text})
                    while True:
                        obj = receive()
                        if obj.get("is_final"):
                            break
                        if obj.get("event") == "task_finished":
                            raise SpeechError("Unexpected task_finished during text.")
                send({"event": "task_finish"})
                while receive().get("event") != "task_finished":
                    pass
    if not audio_path.stat().st_size:
        raise SpeechError("WebSocket completed without audio.")
    raw_path = out / ("stream.raw." + payload["audio_setting"]["format"])
    audio_path.rename(raw_path)
    state.update(status="audio_complete", trace_ids=list(dict.fromkeys(traces)),
                 segment_extra_info=final_infos)
    dump(out / "job.json", state)
    final_path, metadata = finalize_websocket(out, payload, raw_path)
    state.update(metadata)
    return final_path.read_bytes()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credential-file", help="Override local DPAPI credential path")
    commands = parser.add_subparsers(dest="command", required=True)
    config_parser = commands.add_parser("configure", help="Encrypt key in OS credential store")
    config_parser.add_argument("--replace", action="store_true")
    config_parser.add_argument("--stdin", action="store_true",
                               help="Read from a trusted pipe, never a shell argument")
    for command in ("credential-status", "onboard"):
        status_parser = commands.add_parser(command, help="Check setup without an API request")
        status_parser.add_argument("--json", action="store_true")
    commands.add_parser("forget-credential", help="Delete this skill's locally saved API key")
    runtime = commands.add_parser("configure-runtime", help="Save local FFmpeg location")
    runtime.add_argument("--ffmpeg", required=True)
    repair = commands.add_parser("repair-websocket", help="Finalize saved WS data offline")
    repair.add_argument("--out", required=True)
    voices = commands.add_parser("voices", help="Query official voices")
    voices.add_argument("--type", choices=["system", "voice_cloning", "voice_generation", "all"],
                        default="system")
    voices.add_argument("--out", required=True)
    voices.add_argument("--search", default="")
    for name in ("voice-design", "voice-clone"):
        cmd = commands.add_parser(name, help="Create a custom voice with the official API")
        cmd.add_argument("--job", required=True)
        cmd.add_argument("--out", help="New output directory")
        cmd.add_argument("--dry-run", action="store_true",
                         help="Validate and preview locally, without credentials or network")
    for name in ("preview", "generate"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--job", required=True)
        cmd.add_argument("--profile", action="append", default=[])
        cmd.add_argument("--dict", dest="dictionaries", action="append", default=[])
        if name == "generate":
            cmd.add_argument("--out", required=True, help="New output directory")
    args = parser.parse_args()
    if args.command in {"voice-design", "voice-clone"}:
        return create_voice(args)
    if args.command == "configure-runtime":
        executable = Path(args.ffmpeg).resolve()
        if not executable.is_file():
            raise SpeechError("FFmpeg executable does not exist.")
        dump(runtime_path(), {"ffmpeg": str(executable)})
        print("Local FFmpeg path saved; no API request.")
        return
    if args.command == "repair-websocket":
        out = Path(args.out).resolve()
        payload = load(out / "request.json")
        fmt = payload["audio_setting"]["format"]
        raw_path = out / ("stream.raw." + fmt)
        if not raw_path.exists():
            original = out / ("audio." + fmt)
            if not original.is_file():
                raise SpeechError("No saved raw stream available.")
            shutil.copyfile(original, raw_path)
        final_path, metadata = finalize_websocket(out, payload, raw_path)
        state = load(out / "job.json")
        state.update(metadata, audio_bytes=final_path.stat().st_size,
                     audio_sha256=hashlib.sha256(final_path.read_bytes()).hexdigest(),
                     offline_repaired_at=now(),
                     status="completed_with_warnings" if metadata["warnings"] else "completed")
        dump(out / "job.json", state)
        print(json.dumps(clean(state), ensure_ascii=False, indent=2))
        return
    if args.command == "configure":
        if args.stdin:
            if sys.stdin.isatty():
                raise SpeechError("--stdin requires a trusted pipe; use hidden input instead.")
            key = sys.stdin.read(8194).rstrip("\r\n")
        else:
            if not sys.stdin.isatty():
                raise SpeechError("A terminal is required for hidden input. "
                                  "A trusted process may use configure --stdin.")
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                try:
                    key = getpass.getpass("MiniMax API key (hidden): ")
                except getpass.GetPassWarning:
                    raise SpeechError("Hidden input is unavailable; no key was read.") from None
        credentials.save_key(key, args.credential_file, args.replace)
        print("Credential encrypted and verified locally; API authentication not checked.")
        return
    if args.command in {"credential-status", "onboard"}:
        result = credentials.status(args.credential_file)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("Credential status: " + result["status"] + ". No API request performed.")
            if result.get("prompt"):
                print(result["prompt"])
                print("Register: " + result["registration_url"])
                print("Create API key: " + result["api_key_url"])
                print("Official guide: " + result["official_guide"])
                print("Local guide: " + str(Path(__file__).resolve().parents[1] /
                                            "references/setup.md"))
                print("Run: python <skill>/run.py configure")
            if result.get("error"):
                print(result["error"])
        return {"ready": 0, "missing": 2, "unavailable": 3}[result["status"]]
    if args.command == "forget-credential":
        deleted = credentials.forget_key(args.credential_file)
        print(json.dumps({"local_credential_deleted": deleted,
                          "environment_key_still_present": bool(os.environ.get("MINIMAX_API_KEY")),
                          "official_key_revoked": False, "network_request": False}))
        return
    if args.command == "voices":
        target = Path(args.out)
        if target.exists():
            raise SpeechError("Voice output already exists; choose a new path.")
        obj = post(VOICE_URL, {"voice_type": args.type}, key_for(args.credential_file))
        dump(target, obj)
        matches = [row for name, rows in obj.items() if isinstance(rows, list)
                   for row in rows if isinstance(row, dict) and
                   args.search.casefold() in json.dumps(row, ensure_ascii=False).casefold()]
        print(json.dumps(clean({"voice_count": len(matches),
                                "matches": matches[:8], "saved": str(target)}),
                         ensure_ascii=False))
        return
    resolved, transport, texts, payload = resolve(
        load(args.job), args.profile, args.dictionaries)
    if args.command == "preview":
        print(json.dumps(clean({"transport": transport, "request": payload,
                                "segments": texts if transport == "websocket" else None,
                                "input_characters": sum(map(len, texts)),
                                "network_request": False}), ensure_ascii=False, indent=2))
        return
    key = key_for(args.credential_file)
    if transport == "websocket":
        try:
            import websockets.sync.client  # noqa: F401
        except ImportError:
            raise SpeechError("Install websockets>=15,<18 before submitting.")
        if payload["audio_setting"]["format"] != "pcm":
            find_ffmpeg()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    dump(out / "resolved-job.json", resolved)
    dump(out / "request.json", payload)
    (out / "original.txt").write_text(
        resolved.get("original_text", "\n".join(texts)), encoding="utf-8")
    (out / "spoken.txt").write_text("\n".join(texts), encoding="utf-8")
    if resolved.get("direction"):
        (out / "direction.txt").write_text(resolved["direction"], encoding="utf-8")
    state = {"model": MODEL, "transport": transport, "created_at": now(),
             "status": "prepared", "input_characters": sum(map(len, texts)),
             "endpoint": HTTP_URL if transport == "http" else WS_URL}
    dump(out / "job.json", state)
    try:
        raw = (synthesize_http(payload, key, out, state) if transport == "http"
               else synthesize_ws(payload, texts, key, out, state))
        state.update(status="completed_with_warnings" if state.get("warnings") else "completed",
                     finished_at=now(), audio_bytes=len(raw),
                     audio_sha256=hashlib.sha256(raw).hexdigest(),
                     listening_review="pending")
    except (Exception, KeyboardInterrupt) as exc:
        state.update(status=("audio_complete_with_error"
                             if state["status"] == "audio_complete"
                             else "failed_or_result_unknown"),
                     error=clean(str(exc)), finished_at=now(),
                     retry_note="No automatic retry. Inspect saved result before resubmitting.")
        dump(out / "job.json", state)
        raise
    dump(out / "job.json", state)
    print(json.dumps(clean({"output": str(out), **state}), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except (SpeechError, credentials.CredentialError, OSError, ValueError,
            TypeError, KeyError, EOFError) as exc:
        print("ERROR: " + str(clean(str(exc))), file=sys.stderr)
        sys.exit(1)
