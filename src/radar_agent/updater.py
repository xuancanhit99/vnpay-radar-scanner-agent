import argparse
import logging
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from radar_agent.desktop_theme import (
    BLUE_BRIGHT,
    GREEN,
    MUTED,
    RED,
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
    preferred = program_data_directory() / "logs"
    fallback = Path(tempfile.gettempdir()) / "VNPAY" / "RadarScannerAgent" / "logs"
    handler: RotatingFileHandler | None = None
    log_path = preferred / "updater.log"
    for log_directory in (preferred, fallback):
        log_path = log_directory / "updater.log"
        try:
            log_directory.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(
                log_path,
                maxBytes=2 * 1024 * 1024,
                backupCount=2,
                encoding="utf-8",
            )
            break
        except OSError:
            continue
    if handler is None:
        raise OSError("Unable to open the Scanner Agent updater log")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    LOGGER.addHandler(handler)
    return log_path


class UpdaterWindow(QWidget):
    def __init__(self, installer: Path, target_version: str, *, auto_start: bool = True) -> None:
        super().__init__()
        self.installer = installer.resolve()
        self.target_version = target_version
        self.log_path = _configure_logging()
        self.process: subprocess.Popen[bytes] | None = None
        self.saw_installing_state = False
        self.post_exit_polls = 0
        self.installing = False
        self.step_markers: list[QLabel] = []
        self.step_states: list[QLabel] = []

        self.setWindowTitle(f"VNPAY RADAR Scanner Update {target_version}")
        self.setFixedSize(680, 520)
        apply_window_icon(self)
        self._build_ui()
        self._center_window()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.show()
        QTimer.singleShot(1200, self._release_topmost)
        if auto_start:
            QTimer.singleShot(250, self._start_installation)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 22)
        root.setSpacing(0)

        title = QLabel("Updating Scanner Agent")
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            f"Installing version {self.target_version}. Do not turn off this computer."
        )
        subtitle.setObjectName("PageSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)
        root.addSpacing(20)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 100)
        root.addWidget(self.progress)
        root.addSpacing(20)

        steps_panel = QFrame()
        steps_panel.setObjectName("Panel")
        steps = QGridLayout(steps_panel)
        steps.setContentsMargins(18, 14, 18, 14)
        steps.setHorizontalSpacing(12)
        steps.setVerticalSpacing(8)
        steps.setColumnStretch(1, 1)
        for index, step_title in enumerate(UPDATE_STEPS):
            marker = QLabel("●")
            marker.setStyleSheet(f"color: {MUTED}; font-size: 17px;")
            marker.setFixedWidth(16)
            self.step_markers.append(marker)
            label = QLabel(step_title)
            state = QLabel("WAITING")
            state.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            state.setFixedWidth(88)
            state.setStyleSheet(f"color: {MUTED}; font-weight: 600;")
            self.step_states.append(state)
            steps.addWidget(marker, index, 0)
            steps.addWidget(label, index, 1)
            steps.addWidget(state, index, 2)
        root.addWidget(steps_panel)
        root.addSpacing(16)

        self.status_label = QLabel("Preparing installation...")
        self.status_label.setObjectName("StatusBusy")
        self.detail_label = QLabel("")
        self.detail_label.setObjectName("MutedLabel")
        self.detail_label.setWordWrap(True)
        root.addWidget(self.status_label)
        root.addSpacing(3)
        root.addWidget(self.detail_label)
        root.addStretch()

        self.actions = QWidget()
        actions_layout = QHBoxLayout(self.actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        self.open_logs_button = QPushButton("Open logs")
        self.open_logs_button.clicked.connect(self._open_logs)
        self.retry_button = QPushButton("Retry")
        self.retry_button.setObjectName("PrimaryButton")
        self.retry_button.clicked.connect(self._retry)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        actions_layout.addWidget(self.open_logs_button)
        actions_layout.addStretch()
        actions_layout.addWidget(self.retry_button)
        actions_layout.addWidget(self.close_button)
        self.actions.hide()
        root.addWidget(self.actions)
        self._render_progress(ProgressState(completed=1, active=1))

    def _center_window(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())

    def _release_topmost(self) -> None:
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        self.show()

    def _render_progress(self, state: ProgressState) -> None:
        colors = {
            "done": GREEN,
            "active": BLUE_BRIGHT,
            "failed": RED,
            "waiting": MUTED,
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
            marker.setStyleSheet(f"color: {colors[key]}; font-size: 17px;")
            label.setText(text)
            label.setStyleSheet(f"color: {colors[key]}; font-weight: 600;")
        self.progress.setValue(int(state.completed * 100 / len(UPDATE_STEPS)))

    def _start_installation(self) -> None:
        self.actions.hide()
        self.installing = True
        self.saw_installing_state = False
        self.post_exit_polls = 0
        self.status_label.setText("Starting installer...")
        self.status_label.setObjectName("StatusBusy")
        self._refresh_label_style(self.status_label)
        self.detail_label.clear()
        self._render_progress(ProgressState(completed=1, active=1))
        try:
            self.process = start_installer(self.installer)
        except OSError as exc:
            self._show_failure(str(exc), ProgressState(completed=1, active=None, failed=1))
            return
        LOGGER.info("Started installer for version %s", self.target_version)
        QTimer.singleShot(250, self._poll_installer)

    def _poll_installer(self) -> None:
        if self.process is None:
            return
        status = read_installer_status()
        relevant = status is not None and status.version == self.target_version
        if relevant and status.state == "installing":
            self.saw_installing_state = True
            state = progress_state(status, self.target_version)
            self._render_progress(state)
            if state.active is not None:
                self.status_label.setText(f"Step {state.active + 1} of {len(UPDATE_STEPS)}")

        exit_code = self.process.poll()
        if exit_code is None:
            QTimer.singleShot(250, self._poll_installer)
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
            QTimer.singleShot(250, self._poll_installer)
            return
        detail = f"Installer exited with code {exit_code} without a final status."
        LOGGER.error(detail)
        current = progress_state(
            status if self.saw_installing_state else None,
            self.target_version,
        )
        failed = current.active if current.active is not None else 1
        self._show_failure(detail, ProgressState(current.completed, None, failed))

    def _show_success(self) -> None:
        self.installing = False
        self._render_progress(ProgressState(completed=len(UPDATE_STEPS), active=None))
        self.status_label.setText(f"Version {self.target_version} installed successfully")
        self.status_label.setObjectName("StatusSuccess")
        self._refresh_label_style(self.status_label)
        self.detail_label.setText("Scanner Manager is reopening with the new version.")
        LOGGER.info("Installation completed successfully")
        QTimer.singleShot(2500, self.close)

    def _show_failure(self, detail: str, state: ProgressState) -> None:
        self.installing = False
        self._render_progress(state)
        self.status_label.setText(f"Update to version {self.target_version} failed")
        self.status_label.setObjectName("StatusError")
        self._refresh_label_style(self.status_label)
        self.detail_label.setText(detail)
        self.actions.show()
        LOGGER.error("Installation failed: %s", detail)

    def _refresh_label_style(self, label: QLabel) -> None:
        label.style().unpolish(label)
        label.style().polish(label)

    def _retry(self) -> None:
        if not self.installing:
            self._start_installation()

    def _open_logs(self) -> None:
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.log_path.parent))):
            QMessageBox.critical(self, "Open logs", "Windows could not open the log folder.")

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.installing:
            QMessageBox.warning(
                self,
                "Installation in progress",
                "The updater cannot be closed while application files are being replaced.",
            )
            event.ignore()
            return
        event.accept()


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
    application = QApplication(sys.argv)
    application.setApplicationName("VNPAY RADAR Scanner Updater")
    configure_radar_theme(application)
    window = UpdaterWindow(arguments.installer, arguments.version)
    window.show()
    raise SystemExit(application.exec())
