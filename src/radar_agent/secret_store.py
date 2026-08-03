import ctypes
import os
from ctypes import wintypes
from pathlib import Path


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


_CRYPTPROTECT_LOCAL_MACHINE = 0x4


def _require_windows() -> None:
    if os.name != "nt":
        raise RuntimeError("DPAPI secret storage is only available on Windows")


def _transform(data: bytes, *, protect: bool) -> bytes:
    _require_windows()
    if not data:
        raise ValueError("Secret payload must not be empty")

    input_buffer = ctypes.create_string_buffer(data, len(data))
    input_blob = _DataBlob(
        len(data),
        ctypes.cast(input_buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    output_blob = _DataBlob()

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    function = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    function.restype = wintypes.BOOL

    if protect:
        success = function(
            ctypes.byref(input_blob),
            "VNPAY RADAR Scanner Agent",
            None,
            None,
            None,
            _CRYPTPROTECT_LOCAL_MACHINE,
            ctypes.byref(output_blob),
        )
    else:
        success = function(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(output_blob),
        )

    if not success:
        error_code = ctypes.get_last_error()
        raise OSError(error_code, ctypes.FormatError(error_code))

    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


def protect_secret(secret: str, destination: Path) -> None:
    protected = _transform(secret.encode("utf-8"), protect=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(protected)


def unprotect_secret(source: Path) -> str:
    protected = source.read_bytes()
    return _transform(protected, protect=False).decode("utf-8")
