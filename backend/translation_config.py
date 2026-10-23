import base64
import ctypes
import json
import os
from pathlib import Path


class Blob(ctypes.Structure):
    _fields_ = [("size", ctypes.c_ulong), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def protect_secret(value: str, decrypt=False) -> str:
    if os.name != "nt":
        raise RuntimeError("Use the DEEPSEEK_API_KEY environment variable on non-Windows systems")
    raw = base64.b64decode(value) if decrypt else value.encode("utf-8")
    buffer = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    function = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise RuntimeError("Windows could not access the locally protected API key")
    try:
        result = ctypes.string_at(target.data, target.size)
        return result.decode("utf-8") if decrypt else base64.b64encode(result).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(target.data)


class TranslationConfig:
    def __init__(self, directory: Path):
        self.path = directory / "translation.local.json"

    def read(self):
        if self.path.is_file():
            return json.loads(self.path.read_text(encoding="utf-8"))
        return {"total_budget_cny": 5.0}

    def api_key(self):
        stored = self.read()
        if "protected_api_key" in stored:
            encrypted = stored["protected_api_key"]
            return protect_secret(encrypted, decrypt=True) if encrypted else ""
        environment = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        return environment

    def key_source(self):
        return "local" if "protected_api_key" in self.read() else "environment"

    def update(self, api_key=None, total_budget_cny=None):
        value = self.read()
        if api_key is not None:
            value["protected_api_key"] = protect_secret(api_key.strip()) if api_key.strip() else ""
        if total_budget_cny is not None:
            value["total_budget_cny"] = total_budget_cny
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
        temporary.replace(self.path)
