import argparse
import logging
import os
import re
import subprocess
import tempfile
import tkinter as tk
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import messagebox, ttk

from radar_agent.desktop_theme import (
    BACKGROUND,
    BLUE_BRIGHT,
    BORDER,
    GREEN,
    INPUT,
    MUTED,
    RED,
    TEXT,
    apply_window_icon,
    configure_radar_theme,
)
from radar_agent.runtime_paths import program_data_directory
from radar_agent.update_service import InstallerStatus, read_installer_status

LOGGER = logging.getLogger("radar_agent.updater")
UPDATE_STEPS = (
    "Installation package ready",
    "Closing Scanner Manager",
    "Stopping Windows Service",
    "Installing application files",
    "Starting Windows Service",
    "Verifying installation",
)
_STAGE_INDEX = {
    "preparing": 1,
    "closing_manager": 1,
    "checking_service": 2,
    "stopping_service": 2,
    "installing_files": 3,
    "starting_service": 4,
    "verifying": 5,
}
_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


@dataclass(frozen=True)
class ProgressState:
    completed: int
    active: int | None
    failed: int | None = None


def progress_state(status: InstallerStatus | None, target_version: str) -> ProgressState:
    if status is None or status.version != target_version:
        return ProgressState(completed=1, active=1)
    if status.state == "success":
        return ProgressState(completed=len(UPDATE_STEPS), active=None)

    active = _STAGE_INDEX.get(status.stage, 1)
    if status.state == "failed":
        return ProgressState(completed=active, active=None, failed=active)
    return ProgressState(completed=active, active=active)


def start_installer(installer: Path) -> subprocess.Popen[bytes]:
    if os.name != "nt":
        raise OSError("The update installer is only supported on Windows")
    if not installer.is_file():
        raise OSError(f"Installer not found: {installer}")
    return subprocess.Popen(
        [str(installer), "/S", "/UPDATER_CHILD"],
        cwd=str(installer.parent),
        close_fds=True,
    )


def _configure_logging() -> Path:
    log_directory = program_data_directory() / "logs"
    try:
        log_directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        log_directory = Path(tempfile.gettempdir()) / "VNPAY" / "RadarScannerAgent" / "logs"
        log_directory.mkdir(parents=True, exist_ok=True)
    log_path = log_directory / "updater.log"
    handler = RotatingFileHandler(
        log_path,
        maxBytes=2 * 1024 * 1024,
        backupCount=2,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    LOGGER.addHandler(handler)
    return log_path


class UpdaterWindow(tk.Tk):
    def __init__(self, installer: Path, target_version: str) -> None:
        super().__init__()
        self.installer = installer.resolve()
        self.target_version = target_version
        self.log_path = _configure_logging()
        self.process: subprocess.Popen[bytes] | None = None
        self.saw_installing_state = False
        self.post_exit_polls = 0
        self.installing = False
        self.step_markers: list[tk.Canvas] = []
        self.step_states: list[ttk.Label] = []

        self.title(f"VNPAY RADAR Scanner Update {target_version}")
        self.geometry("650x470")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._close_window)
        self._configure_style()
        apply_window_icon(self)
        self._build_ui()
        self._center_window()
        self.attributes("-topmost", True)
        self.after(1200, lambda: self.attributes("-topmost", False))
        self.after(250, self._start_installation)

    def _configure_style(self) -> None:
        style = configure_radar_theme(self)
        style.configure("UpdaterRoot.TFrame", background=BACKGROUND)
        style.configure(
            "UpdaterTitle.TLabel",
            background=BACKGROUND,
            foreground=TEXT,
            font=("Segoe UI Semibold", 18),
        )
        style.configure(
            "UpdaterSubtitle.TLabel",
            background=BACKGROUND,
            foreground=MUTED,
            font=("Segoe UI", 10),
        )
        style.configure(
            "Step.TLabel",
            background=BACKGROUND,
            foreground=TEXT,
            font=("Segoe UI", 10),
        )
        style.configure(
            "StepState.TLabel",
            background=BACKGROUND,
            foreground=MUTED,
            font=("Segoe UI Semibold", 9),
            anchor=tk.E,
        )
        style.configure(
            "UpdaterDetail.TLabel",
            background=BACKGROUND,
            foreground=MUTED,
            font=("Segoe UI", 9),
        )
        style.configure(
            "UpdaterSuccess.TLabel",
            background=BACKGROUND,
            foreground=GREEN,
            font=("Segoe UI Semibold", 10),
        )
        style.configure(
            "UpdaterError.TLabel",
            background=BACKGROUND,
            foreground=RED,
            font=("Segoe UI Semibold", 10),
        )
        style.configure(
            "Horizontal.TProgressbar",
            background=BLUE_BRIGHT,
            troughcolor=INPUT,
            bordercolor=BORDER,
        )

    def _build_ui(self) -> None:
        root = ttk.Frame(self, style="UpdaterRoot.TFrame", padding=(28, 24, 28, 22))
        root.pack(fill=tk.BOTH, expand=True)

        ttk.Label(root, text="Updating Scanner Agent", style="UpdaterTitle.TLabel").pack(
            anchor=tk.W
        )
        ttk.Label(
            root,
            text=f"Installing version {self.target_version}. Do not turn off this computer.",
            style="UpdaterSubtitle.TLabel",
        ).pack(anchor=tk.W, pady=(2, 18))

        self.progress = ttk.Progressbar(root, mode="determinate", maximum=100, value=0)
        self.progress.pack(fill=tk.X, pady=(0, 18))

        steps = ttk.Frame(root)
        steps.pack(fill=tk.X)
        steps.columnconfigure(1, weight=1)
        for index, title in enumerate(UPDATE_STEPS):
            marker = tk.Canvas(
                steps,
                width=18,
                height=18,
                background=BACKGROUND,
                borderwidth=0,
                highlightthickness=0,
            )
            marker.grid(row=index, column=0, padx=(0, 10), pady=5)
            marker.create_oval(3, 3, 15, 15, fill=BORDER, outline="")
            self.step_markers.append(marker)
            ttk.Label(steps, text=title, style="Step.TLabel").grid(
                row=index,
                column=1,
                sticky=tk.W,
                pady=5,
            )
            state = ttk.Label(steps, text="WAITING", width=10, style="StepState.TLabel")
            state.grid(row=index, column=2, sticky=tk.E, pady=5)
            self.step_states.append(state)

        self.status_text = tk.StringVar(value="Preparing installation...")
        self.status_label = ttk.Label(
            root,
            textvariable=self.status_text,
            style="UpdaterDetail.TLabel",
        )
        self.status_label.pack(anchor=tk.W, pady=(18, 2))

        self.detail_text = tk.StringVar(value="")
        ttk.Label(
            root,
            textvariable=self.detail_text,
            style="UpdaterDetail.TLabel",
            wraplength=590,
        ).pack(anchor=tk.W)

        self.actions = ttk.Frame(root, style="UpdaterRoot.TFrame")
        self.actions.pack(fill=tk.X, side=tk.BOTTOM, pady=(14, 0))
        self.open_logs_button = ttk.Button(self.actions, text="Open logs", command=self._open_logs)
        self.retry_button = ttk.Button(self.actions, text="Retry", command=self._retry)
        self.close_button = ttk.Button(self.actions, text="Close", command=self.destroy)
        self.open_logs_button.pack(side=tk.LEFT)
        self.close_button.pack(side=tk.RIGHT)
        self.retry_button.pack(side=tk.RIGHT, padx=(0, 8))
        self.actions.pack_forget()

        self._render_progress(ProgressState(completed=1, active=1))

    def _center_window(self) -> None:
        self.update_idletasks()
        x = max(0, (self.winfo_screenwidth() - self.winfo_width()) // 2)
        y = max(0, (self.winfo_screenheight() - self.winfo_height()) // 2)
        self.geometry(f"+{x}+{y}")

    def _render_progress(self, state: ProgressState) -> None:
        colors = {
            "done": GREEN,
            "active": BLUE_BRIGHT,
            "failed": RED,
            "waiting": BORDER,
        }
        for index, (marker, label) in enumerate(
            zip(self.step_markers, self.step_states, strict=True)
        ):
            if state.failed == index:
                key, text = "failed", "FAILED"
            elif index < state.completed:
                key, text = "done", "DONE"
            elif state.active == index:
                key, text = "active", "RUNNING"
            else:
                key, text = "waiting", "WAITING"
            marker.itemconfigure(1, fill=colors[key])
            label.configure(text=text, foreground=colors[key])
        self.progress["value"] = state.completed * 100 / len(UPDATE_STEPS)

    def _start_installation(self) -> None:
        self.actions.pack_forget()
        self.installing = True
        self.saw_installing_state = False
        self.post_exit_polls = 0
        self.status_text.set("Starting installer...")
        self.status_label.configure(style="UpdaterDetail.TLabel")
        self.detail_text.set("")
        self._render_progress(ProgressState(completed=1, active=1))
        try:
            self.process = start_installer(self.installer)
        except OSError as exc:
            self._show_failure(str(exc), ProgressState(completed=1, active=None, failed=1))
            return
        LOGGER.info("Started installer for version %s", self.target_version)
        self.after(250, self._poll_installer)

    def _poll_installer(self) -> None:
        if self.process is None:
            return
        status = read_installer_status()
        relevant = status is not None and status.version == self.target_version
        if relevant and status.state == "installing":
            self.saw_installing_state = True
            self._render_progress(progress_state(status, self.target_version))
            active = progress_state(status, self.target_version).active
            if active is not None:
                self.status_text.set(f"Step {active + 1} of {len(UPDATE_STEPS)}")

        exit_code = self.process.poll()
        if exit_code is None:
            self.after(250, self._poll_installer)
            return

        if relevant and status.state == "success":
            self._show_success()
            return
        if relevant and status.state == "failed":
            detail = status.message or f"Installer exited with code {exit_code}."
            self._show_failure(detail, progress_state(status, self.target_version))
            return

        self.post_exit_polls += 1
        if self.post_exit_polls < 20:
            self.after(250, self._poll_installer)
            return
        detail = f"Installer exited with code {exit_code} without a final status."
        LOGGER.error(detail)
        current = progress_state(status if self.saw_installing_state else None, self.target_version)
        failed = current.active if current.active is not None else 1
        self._show_failure(detail, ProgressState(current.completed, None, failed))

    def _show_success(self) -> None:
        self.installing = False
        self._render_progress(ProgressState(completed=len(UPDATE_STEPS), active=None))
        self.status_text.set(f"Version {self.target_version} installed successfully")
        self.status_label.configure(style="UpdaterSuccess.TLabel")
        self.detail_text.set("Scanner Manager is reopening with the new version.")
        LOGGER.info("Installation completed successfully")
        self.after(2500, self.destroy)

    def _show_failure(self, detail: str, state: ProgressState) -> None:
        self.installing = False
        self._render_progress(state)
        self.status_text.set(f"Update to version {self.target_version} failed")
        self.status_label.configure(style="UpdaterError.TLabel")
        self.detail_text.set(detail)
        self.actions.pack(fill=tk.X, side=tk.BOTTOM, pady=(14, 0))
        LOGGER.error("Installation failed: %s", detail)

    def _retry(self) -> None:
        if not self.installing:
            self._start_installation()

    def _open_logs(self) -> None:
        try:
            os.startfile(str(self.log_path.parent))
        except OSError as exc:
            messagebox.showerror("Open logs", str(exc), parent=self)

    def _close_window(self) -> None:
        if self.installing:
            messagebox.showwarning(
                "Installation in progress",
                "The updater cannot be closed while application files are being replaced.",
                parent=self,
            )
            return
        self.destroy()


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="VNPAY RADAR Scanner Agent updater")
    parser.add_argument("--installer", required=True, type=Path)
    parser.add_argument("--version", required=True)
    arguments = parser.parse_args()
    if not _VERSION_PATTERN.fullmatch(arguments.version):
        parser.error("--version must use MAJOR.MINOR.PATCH format")
    return arguments


def main() -> None:
    arguments = _parse_arguments()
    window = UpdaterWindow(arguments.installer, arguments.version)
    window.mainloop()
