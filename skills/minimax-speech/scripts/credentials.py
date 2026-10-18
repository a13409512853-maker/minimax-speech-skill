"""Local credential storage. Never select a keyring plaintext fallback."""

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys
import tempfile

SERVICE = "minimax-speech"
ACCOUNT = "official-api-key"
REGISTER_URL = "https://platform.minimax.cn/login?source=platform_docs"
KEY_URL = "https://platform.minimax.cn/user-center/basic-information/interface-key"
GUIDE_URL = "https://platform.minimaxi.com/docs/guides/quickstart-preparation"


class CredentialError(Exception):
    pass


def validate(key):
    if not isinstance(key, str) or not key or len(key) > 8192:
        raise CredentialError("API key must contain 1-8192 characters.")
    if any(c.isspace() or ord(c) < 32 for c in key):
        raise CredentialError("API key contains whitespace or control characters.")
    return key


def credential_path(override=None):
    if sys.platform != "win32":
        raise CredentialError("--credential-file is only supported with Windows DPAPI.")
    if override:
        return Path(override).expanduser().resolve()
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        raise CredentialError("LOCALAPPDATA is unavailable.")
    return Path(base) / "MiniMaxSpeech" / "credentials.dpapi"


def dpapi(data, encrypt):
    if sys.platform != "win32":
        raise CredentialError("Windows DPAPI is unavailable on this platform.")

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(data)
    incoming = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = Blob()
    library = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if encrypt:
        operation = library.CryptProtectData
        operation.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR,
                              ctypes.POINTER(Blob), ctypes.c_void_p,
                              ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        success = operation(ctypes.byref(incoming), "MiniMax Speech API key",
                            None, None, None, 1, ctypes.byref(outgoing))
    else:
        operation = library.CryptUnprotectData
        operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p,
                              ctypes.POINTER(Blob), ctypes.c_void_p,
                              ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        success = operation(ctypes.byref(incoming), None, None, None, None,
                            1, ctypes.byref(outgoing))
    if not success:
        raise CredentialError("Windows DPAPI failed. Run as the same local user "
                              "with access to the Windows credential service.")
    try:
        return ctypes.string_at(outgoing.pbData, outgoing.cbData)
    finally:
        kernel.LocalFree(outgoing.pbData)


def system_keyring():
    try:
        if sys.platform == "darwin":
            from keyring.backends.macOS import Keyring
        elif sys.platform.startswith("linux"):
            from keyring.backends.SecretService import Keyring
        else:
            raise CredentialError("No supported OS credential store.")
        backend = Keyring()
        if backend.priority <= 0:
            raise CredentialError("OS credential store is unavailable.")
        return backend
    except CredentialError:
        raise
    except Exception:
        raise CredentialError(
            "OS credential store is unavailable or locked. Install requirements, "
            "then unlock macOS Keychain or Linux Secret Service in your user session. "
            "Plaintext storage is never used.") from None


def stored_key(path=None):
    if sys.platform == "win32":
        target = credential_path(path)
        if not target.exists():
            return None
        try:
            return validate(dpapi(target.read_bytes(), False).decode("utf-8"))
        except (OSError, UnicodeError):
            raise CredentialError("Stored DPAPI credential is unreadable.") from None
    if path:
        credential_path(path)
    try:
        key = system_keyring().get_password(SERVICE, ACCOUNT)
        return validate(key) if key is not None else None
    except CredentialError:
        raise
    except Exception:
        raise CredentialError("Cannot read the OS credential store; unlock it and retry.") from None


def save_key(key, path=None, replace=False):
    key = validate(key)
    if stored_key(path) is not None and not replace:
        raise CredentialError("Credential already exists; use --replace intentionally.")
    if sys.platform == "win32":
        target = credential_path(path)
        encrypted = dpapi(key.encode("utf-8"), True)
        if dpapi(encrypted, False).decode("utf-8") != key:
            raise CredentialError("Credential encryption verification failed.")
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".credential-", dir=target.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encrypted)
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)
    else:
        if path:
            credential_path(path)
        try:
            system_keyring().set_password(SERVICE, ACCOUNT, key)
        except CredentialError:
            raise
        except Exception:
            raise CredentialError("OS credential store refused the write; no plaintext saved.") from None
    if stored_key(path) != key:
        raise CredentialError("Stored credential could not be verified.")


def forget_key(path=None):
    if sys.platform == "win32":
        target = credential_path(path)
        existed = target.exists()
        target.unlink(missing_ok=True)
        return existed
    if path:
        credential_path(path)
    if stored_key() is None:
        return False
    try:
        system_keyring().delete_password(SERVICE, ACCOUNT)
    except CredentialError:
        raise
    except Exception:
        raise CredentialError("OS credential store refused deletion.") from None
    if stored_key() is not None:
        raise CredentialError("Credential deletion could not be verified.")
    return True


def get_key(path=None):
    key = os.environ.get("MINIMAX_API_KEY")
    if key:
        return validate(key)
    key = stored_key(path)
    if key is None:
        raise CredentialError("No API key. Run onboard for registration and setup instructions.")
    return key


def status(path=None):
    backend = ("windows-dpapi" if sys.platform == "win32" else
               "macos-keychain" if sys.platform == "darwin" else "linux-secret-service")
    try:
        environment = os.environ.get("MINIMAX_API_KEY")
        key = validate(environment) if environment else stored_key(path)
        state = "ready" if key else "missing"
        error = None
    except CredentialError as exc:
        state, error = "unavailable", str(exc)
    result = {"status": state, "credential_readable": state == "ready",
              "source": "environment" if os.environ.get("MINIMAX_API_KEY") else backend,
              "network_request": False,
              "api_authentication": "not_checked",
              "registration_url": REGISTER_URL, "api_key_url": KEY_URL,
              "official_guide": GUIDE_URL}
    if state == "missing":
        result["prompt"] = ("请配置你自己的 MiniMax 官方按量付费 API Key。"
                            "未注册请先打开 registration_url，按 official_guide 创建账号与密钥。"
                            "使用 configure 在本机隐藏输入，随后加密保存。")
    if error:
        result["error"] = error
    return result
