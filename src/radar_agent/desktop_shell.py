import ctypes
import os
from collections.abc import Callable

from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

_ERROR_ALREADY_EXISTS = 183
_SW_SHOW = 5
_SW_RESTORE = 9
_MUTEX_NAME = r"Local\VNPAYRadarScannerManager"
_WINDOW_TITLE_PREFIX = "VNPAY RADAR Scanner Manager"


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
    """Own the native Qt notification-area icon and its quick actions."""

    def __init__(
        self,
        *,
        parent: QWidget,
        icon,
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
        self._actions_enabled = actions_enabled
        self._icon = QSystemTrayIcon(icon, parent)
        self._icon.setToolTip("VNPAY RADAR Scanner Manager")
        self._menu = QMenu(parent)

        open_action = self._menu.addAction("Open Scanner Manager")
        open_action.triggered.connect(open_manager)
        self._menu.addSeparator()
        self._guarded_actions = []
        for label, callback in (
            ("Run diagnostics", run_diagnostics),
            ("Open logs", open_logs),
            ("Check for updates", check_updates),
        ):
            action = self._menu.addAction(label)
            action.triggered.connect(callback)
            self._guarded_actions.append(action)
        self._menu.addSeparator()
        for label, callback in (
            ("Start service", start_service),
            ("Stop service", stop_service),
            ("Restart service", restart_service),
        ):
            action = self._menu.addAction(label)
            action.triggered.connect(callback)
            self._guarded_actions.append(action)
        self._menu.addSeparator()
        exit_action = self._menu.addAction("Exit")
        exit_action.triggered.connect(exit_application)
        self._guarded_actions.append(exit_action)
        self._menu.aboutToShow.connect(self._refresh_actions)
        self._icon.setContextMenu(self._menu)
        self._icon.activated.connect(
            lambda reason: open_manager()
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick
            else None
        )

    def _refresh_actions(self) -> None:
        enabled = self._actions_enabled()
        for action in self._guarded_actions:
            action.setEnabled(enabled)

    def start(self) -> None:
        self._icon.show()

    def stop(self) -> None:
        self._icon.hide()

    def notify_minimized(self) -> None:
        if QSystemTrayIcon.supportsMessages():
            self._icon.showMessage(
                "VNPAY RADAR Scanner Manager",
                "Scanner Manager is still running. Use this icon to reopen or exit.",
                QSystemTrayIcon.MessageIcon.Information,
                5000,
            )
