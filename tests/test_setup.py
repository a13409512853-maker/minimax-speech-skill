import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/minimax-speech/scripts"
sys.path.insert(0, str(SCRIPT))
import credentials
import minimax_speech as speech


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, filename)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


installer = module("installer", ROOT / "install.py")
release = module("release", ROOT / "tools/check_release.py")


class MemoryKeyring:
    priority = 5

    def __init__(self):
        self.value = None

    def get_password(self, service, account):
        return self.value

    def set_password(self, service, account, key):
        self.value = key

    def delete_password(self, service, account):
        self.value = None


class CredentialTests(unittest.TestCase):
    def test_missing_and_locked_are_different_states(self):
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(credentials, "stored_key", return_value=None):
            self.assertEqual(credentials.status()["status"], "missing")
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(credentials, "stored_key",
                             side_effect=credentials.CredentialError("locked")):
            result = credentials.status()
            self.assertEqual(result["status"], "unavailable")
            self.assertNotIn("prompt", result)

    def test_environment_key_has_priority_without_persisting(self):
        value = "test-" + secrets.token_hex(16)
        with patch.dict(os.environ, {"MINIMAX_API_KEY": value}), \
                patch.object(credentials, "stored_key") as stored:
            self.assertEqual(credentials.get_key(), value)
            self.assertEqual(credentials.status()["source"], "environment")
            stored.assert_not_called()

    def test_supported_keyring_roundtrip_replace_and_forget(self):
        for platform in ("darwin", "linux"):
            backend = MemoryKeyring()
            with self.subTest(platform=platform), \
                    patch.object(credentials.sys, "platform", platform), \
                    patch.object(credentials, "system_keyring", return_value=backend):
                credentials.save_key("fictional-test-value")
                self.assertEqual(credentials.get_key(), "fictional-test-value")
                with self.assertRaises(credentials.CredentialError):
                    credentials.save_key("new-test-value")
                credentials.save_key("new-test-value", replace=True)
                self.assertEqual(credentials.get_key(), "new-test-value")
                self.assertTrue(credentials.forget_key())
                self.assertFalse(credentials.forget_key())

    def test_unavailable_store_does_not_write_a_file(self):
        with tempfile.TemporaryDirectory() as name, \
                patch.object(credentials.sys, "platform", "linux"), \
                patch.object(credentials, "system_keyring",
                             side_effect=credentials.CredentialError("unavailable")):
            with self.assertRaises(credentials.CredentialError):
                credentials.save_key("test")
            self.assertEqual(list(Path(name).iterdir()), [])

    def test_stdin_configuration_does_not_echo_key(self):
        value = "test-" + secrets.token_hex(16)
        output = io.StringIO()
        with patch.object(sys, "argv", ["speech", "configure", "--stdin"]), \
                patch.object(sys, "stdin", io.StringIO(value + "\n")), \
                patch.object(credentials, "save_key") as save, \
                contextlib.redirect_stdout(output):
            speech.main()
        self.assertEqual(save.call_args.args[0], value)
        self.assertNotIn(value, output.getvalue())

    def test_hidden_input_refuses_nonterminal_instead_of_echo_fallback(self):
        with patch.object(sys, "argv", ["speech", "configure"]), \
                patch.object(sys, "stdin", io.StringIO("fictional")), \
                patch.object(speech.getpass, "getpass") as prompt:
            with self.assertRaises(speech.SpeechError):
                speech.main()
            prompt.assert_not_called()

    def test_multiline_or_control_values_are_rejected(self):
        for value in ("", "one\ntwo", "one two", "one\0two"):
            with self.subTest(value=value), self.assertRaises(credentials.CredentialError):
                credentials.validate(value)

    @unittest.skipUnless(sys.platform == "win32", "Windows DPAPI native test")
    def test_windows_real_encrypted_roundtrip_and_deletion(self):
        value = "fictional-" + secrets.token_hex(24)
        with tempfile.TemporaryDirectory() as name:
            target = Path(name) / "credentials.dpapi"
            credentials.save_key(value, target)
            self.assertNotIn(value.encode(), target.read_bytes())
            self.assertEqual(credentials.stored_key(target), value)
            with self.assertRaises(credentials.CredentialError):
                credentials.save_key("replacement", target)
            credentials.save_key("replacement", target, replace=True)
            self.assertEqual(credentials.stored_key(target), "replacement")
            self.assertTrue(credentials.forget_key(target))
            self.assertFalse(target.exists())


class InstallTests(unittest.TestCase):
    def test_copy_verification_repeat_install_and_changed_file_protection(self):
        with tempfile.TemporaryDirectory() as name:
            target = Path(name) / "Chinese space folder" / "minimax-speech"
            self.assertEqual(installer.install(target), "installed")
            self.assertEqual(installer.files(target), installer.files(installer.SOURCE))
            self.assertEqual(installer.install(target), "already_installed")
            (target / "SKILL.md").write_text("user customizations", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                installer.install(target)
            self.assertEqual((target / "SKILL.md").read_text(), "user customizations")

    def test_noninteractive_installer_reports_onboarding_without_prompt(self):
        with tempfile.TemporaryDirectory() as name:
            env = dict(os.environ)
            env.pop("MINIMAX_API_KEY", None)
            env["LOCALAPPDATA"] = str(Path(name) / "local")
            process = subprocess.run(
                [sys.executable, str(ROOT / "install.py"), "--no-deps",
                 "--non-interactive", "--json", "--dest", str(Path(name) / "skills")],
                input="", capture_output=True, text=True, encoding="utf-8", env=env, timeout=30)
            self.assertEqual(process.returncode, 0, process.stderr)
            result = json.loads(process.stdout)
            self.assertEqual(result["generation_performed"], False)
            self.assertNotEqual(result["credential"]["status"], "ready")
            self.assertEqual(result["next_action"],
                             "ask_user_to_configure_own_official_api_key"
                             if result["credential"]["status"] == "missing"
                             else "repair_local_credential_store")
            self.assertTrue(result["credential"]["registration_url"].startswith("https://"))

    def test_installer_routes_missing_and_unavailable_to_different_actions(self):
        actions = {
            "ready": "ready_for_user_requested_generation",
            "missing": "ask_user_to_configure_own_official_api_key",
            "unavailable": "repair_local_credential_store",
        }
        for status, action in actions.items():
            output = io.StringIO()
            with self.subTest(status=status), \
                    patch.object(installer, "install", return_value="installed"), \
                    patch.object(installer, "setup_runtime"), \
                    patch.object(installer, "local_status", return_value={"status": status}), \
                    patch.object(installer.subprocess, "call") as prompt, \
                    contextlib.redirect_stdout(output):
                code = installer.main(["--non-interactive", "--json"])
                self.assertEqual(code, 0)
                record = json.loads(output.getvalue())
                self.assertEqual(record["next_action"], action)
                self.assertFalse(record["generation_performed"])
                prompt.assert_not_called()

    def test_release_excludes_cache_and_rejects_secrets_without_echo(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            for rel in ("README.md", "AGENTS.md", "LICENSE", ".gitignore", "install.py",
                        "skills/minimax-speech/SKILL.md",
                        "skills/minimax-speech/scripts/credentials.py"):
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("public", encoding="utf-8")
            cache = root / "__pycache__/test.pyc"
            cache.parent.mkdir()
            cache.write_bytes(b"private cache")
            self.assertNotIn("__pycache__/test.pyc", release.collect(root))
            value = "sk-" + "api-" + secrets.token_hex(32)
            (root / "README.md").write_text(value)
            with self.assertRaises(ValueError) as error:
                release.collect(root)
            self.assertNotIn(value, str(error.exception))
            self.assertIn("credential-like", str(error.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
