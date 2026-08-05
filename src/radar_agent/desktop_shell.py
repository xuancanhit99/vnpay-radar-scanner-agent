import ctypes
import os
import threading
from collections.abc import Callable

import pystray
from PIL import Image, ImageDraw

_ERROR_ALREADY_EXISTS = 183
_SW_SHOW = 5
_SW_RESTORE = 9
_MUTEX_NAME = r"Local\VNPAYRadarScannerManager"
_WINDOW_TITLE_PREFIX = "VNPAY RADAR Scanner Manager"


def create_radar_icon(size: int = 64) -> Image.Image:
    """Create the shared RADAR window/tray icon at the requested size."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = max(4, size // 10)
    center = size // 2
    blue = "#006CC2"
    muted_blue = "#0056A7"

    draw.ellipse(
        (margin, margin, size - margin, size - margin),
        outline=blue,
        width=max(2, size // 18),
    )
    draw.ellipse(
        (center - size // 5, center - size // 5, center + size // 5, center + size // 5),
        outline=muted_blue,
        width=max(1, size // 24),
    )
    draw.line(
        (center, center, size - margin - 2, margin + 4),
        fill="#10B981",
        width=max(2, size // 18),
    )
    dot = max(3, size // 11)
    draw.ellipse((center - dot, center - dot, center + dot, center + dot), fill="#E81D24")
    return image


class SingleInstance:
    """Windows named-mutex guard for the Scanner Manager process."""

    def __init__(self, name: str = _MUTEX_NAME) -> None:
        self._name = name
        self._handle: int | None = None

    def acquire(self) -> bool:
        if os.name != "nt":
            return True
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_bool

        handle = kernel32.CreateMutexW(None, False, self._name)
        if not handle:
            raise OSError(ctypes.get_last_error(), "Could not create Manager mutex")
        if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        self._handle = int(handle)
        return True

    def close(self) -> None:
        if os.name != "nt" or self._handle is None:
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_bool
        kernel32.CloseHandle(self._handle)
        self._handle = None

    def __enter__(self) -> "SingleInstance":
        if not self.acquire():
            raise RuntimeError("Scanner Manager is already running")
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def focus_existing_manager(title_prefix: str = _WINDOW_TITLE_PREFIX) -> bool:
    """Restore and focus the existing Manager window after a duplicate launch."""
    if os.name != "nt":
        return False
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    found: list[int] = []

    @callback_type
    def visit(window: int, _parameter: int) -> bool:
        length = user32.GetWindowTextLengthW(window)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(window, buffer, len(buffer))
        if buffer.value.startswith(title_prefix):
            found.append(int(window))
            return False
        return True

    user32.EnumWindows(visit, 0)
    if not found:
        return False
    window = found[0]
    user32.ShowWindow(window, _SW_SHOW)
    user32.ShowWindow(window, _SW_RESTORE)
    user32.SetForegroundWindow(window)
    return True


class TrayController:
    """Own the Windows notification-area icon and marshal actions to Tk."""

    def __init__(
        self,
        *,
        dispatch: Callable[[Callable[[], None]], None],
        open_manager: Callable[[], None],
        run_diagnostics: Callable[[], None],
        open_logs: Callable[[], None],
        check_updates: Callable[[], None],
        start_service: Callable[[], None],
        stop_service: Callable[[], None],
        restart_service: Callable[[], None],
        exit_application: Callable[[], None],
        actions_enabled: Callable[[], bool],
    ) -> None:
        self._dispatch = dispatch
        self._actions_enabled = actions_enabled

        def action(callback: Callable[[], None]):
            def invoke(_icon: pystray.Icon, _item: pystray.MenuItem) -> None:
                self._dispatch(callback)

            return invoke

        def enabled(_item: pystray.MenuItem) -> bool:
            return self._actions_enabled()

        self._icon = pystray.Icon(
            "vnpay-radar-scanner-manager",
            create_radar_icon(),
            "VNPAY RADAR Scanner Manager",
            menu=pystray.Menu(
                pystray.MenuItem("Open Scanner Manager", action(open_manager), default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Run diagnostics", action(run_diagnostics), enabled=enabled),
                pystray.MenuItem("Open logs", action(open_logs), enabled=enabled),
                pystray.MenuItem("Check for updates", action(check_updates), enabled=enabled),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Start service", action(start_service), enabled=enabled),
                pystray.MenuItem("Stop service", action(stop_service), enabled=enabled),
                pystray.MenuItem("Restart service", action(restart_service), enabled=enabled),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Exit", action(exit_application), enabled=enabled),
            ),
        )
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._icon.run,
            name="scanner-manager-tray",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._icon.stop()

    def notify_minimized(self) -> None:
        if self._icon.HAS_NOTIFICATION:
            self._icon.notify(
                "Scanner Manager is still running. Use this icon to reopen or exit.",
                "VNPAY RADAR Scanner Manager",
            )
