import asyncio
import math
import os
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError
from PySide6.QtCore import QObject, QRectF, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import (
    QBrush,
    QCloseEvent,
    QColor,
    QDesktopServices,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QStyle,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from radar_agent import __version__
from radar_agent.config_store import load_settings, plaintext_bootstrap, save_settings
from radar_agent.desktop_shell import (
    MANAGER_APP_USER_MODEL_ID,
    SingleInstance,
    TrayController,
    focus_existing_manager,
    set_windows_app_user_model_id,
)
from radar_agent.desktop_theme import (
    BLUE_BRIGHT,
    GREEN,
    MUTED,
    RED,
    apply_window_icon,
    configure_radar_theme,
    radar_icon,
    vnpay_logo_pixmap,
)
from radar_agent.diagnostics import DiagnosticResult, run_diagnostics
from radar_agent.runtime_paths import (
    SERVICE_NAME,
    default_config_path,
    package_root,
    program_data_directory,
    service_log_path,
    worker_executable,
)
from radar_agent.service_control import (
    ServiceState,
    install_service,
    query_service,
    read_service_log,
    service_action,
)
from radar_agent.settings import AgentSettings
from radar_agent.update_service import (
    InstallerStatus,
    UpdateInfo,
    check_for_update,
    download_installer,
    launch_installer,
    launch_updater,
    read_installer_status,
)

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_DIAGNOSTIC_STEPS = (
    ("sso", "VNPAY SSO"),
    ("scanner", "APK Scanner"),
    ("device", "Android device"),
    ("radar", "RADAR backend"),
)


def _diagnostic_steps(settings: AgentSettings) -> tuple[tuple[str, str], ...]:
    if settings.dast_enabled:
        return (*_DIAGNOSTIC_STEPS[:-1], ("dast", "DAST Engine"), _DIAGNOSTIC_STEPS[-1])
    return _DIAGNOSTIC_STEPS


def _diagnostic_spinner_icon(frame: int, size: int = 18) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    circle = QRectF(3, 3, size - 6, size - 6)
    base_pen = QPen(QColor(255, 255, 255, 75), 2)
    base_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(base_pen)
    painter.drawEllipse(circle)

    active_pen = QPen(QColor(255, 255, 255), 2)
    active_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(active_pen)
    start_angle = -int((frame % 12) * (2 * math.pi / 12) * 180 / math.pi * 16)
    painter.drawArc(circle, start_angle, -110 * 16)
    painter.end()
    return QIcon(pixmap)


class ManagerEvents(QObject):
    task_completed = Signal(str, object)
    task_failed = Signal(str, str)
    diagnostic_started = Signal(str, str)
    diagnostic_completed = Signal(object)
    update_progress = Signal(str, int)
    process_output = Signal(str)


class NumericStepper(QFrame):
    def __init__(self, minimum: int, maximum: int) -> None:
        super().__init__()
        self.setObjectName("NumericStepper")
        self.setFixedWidth(176)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.input = QSpinBox()
        self.input.setObjectName("StepperInput")
        self.input.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.input.setRange(minimum, maximum)
        layout.addWidget(self.input, 1)

        self.decrement_button = QToolButton()
        self.decrement_button.setObjectName("StepperButton")
        self.decrement_button.setText("-")
        self.decrement_button.setToolTip("Decrease")
        self.decrement_button.clicked.connect(self.input.stepDown)
        layout.addWidget(self.decrement_button)

        self.increment_button = QToolButton()
        self.increment_button.setObjectName("StepperButton")
        self.increment_button.setText("+")
        self.increment_button.setToolTip("Increase")
        self.increment_button.clicked.connect(self.input.stepUp)
        layout.addWidget(self.increment_button)

    def setValue(self, value: int) -> None:
        self.input.setValue(value)

    def value(self) -> int:
        return self.input.value()


class ManagerWindow(QMainWindow):
    def __init__(self, *, start_background_tasks: bool = True) -> None:
        super().__init__()
        self.setWindowTitle(f"VNPAY RADAR Scanner Manager {__version__}")
        self.resize(1120, 760)
        self.setMinimumSize(960, 660)
        apply_window_icon(self)

        self._package_root = package_root()
        self._config_path = default_config_path(self._package_root)
        self._configuration_error = ""
        self._settings = self._load_settings_safely()
        self._direct_process: subprocess.Popen[str] | None = None
        self._operation_running = False
        self._update_check_running = False
        self._update_install_running = False
        self._available_update: UpdateInfo | None = None
        self._diagnostics_running = False
        self._diagnostic_results: dict[str, DiagnosticResult] = {}
        self._diagnostic_rows: dict[str, int] = {}
        self._active_diagnostic_steps = _diagnostic_steps(self._settings)
        self._interaction_locked = False
        self._tray: TrayController | None = None
        self._tray_notice_shown = False
        self._exiting = False
        self._tasks: dict[
            str,
            tuple[Callable[[object], None], Callable[[str], None]],
        ] = {}

        self.events = ManagerEvents(self)
        self.events.task_completed.connect(self._task_completed)
        self.events.task_failed.connect(self._task_failed)
        self.events.diagnostic_started.connect(self._diagnostic_started)
        self.events.diagnostic_completed.connect(self._diagnostic_completed)
        self.events.update_progress.connect(self._show_update_progress)
        self.events.process_output.connect(self._append_log_text)

        self._build_ui()
        self._load_form()
        self._show_installer_status(read_installer_status())
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(4000)
        self._status_timer.timeout.connect(self.refresh_status)

        if start_background_tasks:
            self.refresh_status()
            self._status_timer.start()
            QTimer.singleShot(100, self._start_tray)
            installer_status = read_installer_status()
            if installer_status is None or installer_status.state == "success":
                delay = 5000 if installer_status else 1200
                QTimer.singleShot(delay, lambda: self.check_for_updates(silent=True))
        else:
            self._apply_status(ServiceState(False, "not-installed"))

    def _build_ui(self) -> None:
        central = QWidget(self)
        shell = QHBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        self.setCentralWidget(central)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(224)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(16, 20, 16, 16)
        sidebar_layout.setSpacing(6)

        brand = QHBoxLayout()
        brand.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(radar_icon(44).pixmap(44, 44))
        logo.setFixedSize(44, 44)
        brand.addWidget(logo)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        title = QLabel("RADAR Scanner")
        title.setObjectName("BrandTitle")
        subtitle = QLabel("Windows Manager")
        subtitle.setObjectName("BrandSubtitle")
        brand_text.addWidget(title)
        brand_text.addWidget(subtitle)
        brand.addLayout(brand_text)
        sidebar_layout.addLayout(brand)
        sidebar_layout.addSpacing(24)

        self.nav_buttons: list[QPushButton] = []
        nav_items = (
            ("Overview", QStyle.StandardPixmap.SP_ComputerIcon),
            ("Configuration", QStyle.StandardPixmap.SP_FileDialogDetailedView),
            ("Diagnostics", QStyle.StandardPixmap.SP_DialogApplyButton),
            ("Logs", QStyle.StandardPixmap.SP_FileIcon),
        )
        for index, (label, icon_type) in enumerate(nav_items):
            button = QPushButton(label)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setIcon(self.style().standardIcon(icon_type))
            button.setToolTip(f"Open {label}")
            button.clicked.connect(lambda _checked=False, page=index: self._select_page(page))
            sidebar_layout.addWidget(button)
            self.nav_buttons.append(button)
        self.nav_buttons[0].setChecked(True)
        sidebar_layout.addStretch()
        self.vnpay_brand_logo = QLabel()
        self.vnpay_brand_logo.setObjectName("VnpayBrandLogo")
        self.vnpay_brand_logo.setPixmap(vnpay_logo_pixmap(121))
        self.vnpay_brand_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.vnpay_brand_logo.setToolTip("VNPAY")
        sidebar_layout.addWidget(self.vnpay_brand_logo)
        sidebar_layout.addSpacing(8)
        version = QLabel(f"VERSION {__version__}")
        version.setObjectName("VersionLabel")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sidebar_layout.addWidget(version)
        shell.addWidget(self.sidebar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 18, 24, 24)
        content_layout.setSpacing(14)

        self.page_stack = QStackedWidget()
        self.overview_page = self._build_overview_page()
        self.configuration_page = self._build_configuration_page()
        self.diagnostics_page = self._build_diagnostics_page()
        self.logs_page = self._build_logs_page()
        for page in (
            self.overview_page,
            self.configuration_page,
            self.diagnostics_page,
            self.logs_page,
        ):
            self.page_stack.addWidget(page)
        content_layout.addWidget(self.page_stack, 1)
        shell.addWidget(content, 1)

    def _page(self, title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(14)
        heading = QLabel(title)
        heading.setObjectName("PageTitle")
        description = QLabel(subtitle)
        description.setObjectName("PageSubtitle")
        description.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(description)
        layout.addSpacing(2)
        return page, layout

    def _panel(
        self,
        title: str,
        subtitle: str = "",
    ) -> tuple[QFrame, QVBoxLayout]:
        panel = QFrame()
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)
        if subtitle:
            description = QLabel(subtitle)
            description.setObjectName("SectionSubtitle")
            description.setWordWrap(True)
            layout.addWidget(description)
        return panel, layout

    def _build_overview_page(self) -> QWidget:
        page, layout = self._page(
            "Overview",
            "Monitor the Scanner Agent and manage its local Windows runtime.",
        )
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 6, 0)
        body_layout.setSpacing(14)

        runtime, runtime_layout = self._panel("Runtime status")
        status_grid = QGridLayout()
        status_grid.setHorizontalSpacing(12)
        status_grid.setVerticalSpacing(10)
        status_grid.setColumnStretch(2, 1)
        self.service_dot, self.service_status = self._status_row(
            status_grid, 0, "Windows Service", "Checking..."
        )
        self.direct_dot, self.direct_status = self._status_row(
            status_grid, 1, "Direct process", "Checking..."
        )
        self.agent_status = self._metadata_row(status_grid, 2, "Agent ID")
        self.version_status = self._metadata_row(status_grid, 3, "Version", __version__)
        self.config_status = self._metadata_row(status_grid, 4, "Configuration")
        self.package_status = self._metadata_row(status_grid, 5, "Package")
        runtime_layout.addLayout(status_grid)
        body_layout.addWidget(runtime)

        update, update_layout = self._panel(
            "Software update",
            "Updates are verified against the SHA-256 checksum published on GitHub Releases.",
        )
        update_row = QHBoxLayout()
        self.update_status_label = QLabel("Checking for updates...")
        self.update_status_label.setWordWrap(True)
        update_row.addWidget(self.update_status_label, 1)
        self.check_update_button = QPushButton("Check again")
        self.check_update_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        self.check_update_button.clicked.connect(lambda: self.check_for_updates())
        self.install_update_button = QPushButton("Update now")
        self.install_update_button.setObjectName("PrimaryButton")
        self.install_update_button.setEnabled(False)
        self.install_update_button.hide()
        self.install_update_button.clicked.connect(self.install_available_update)
        update_row.addWidget(self.check_update_button)
        update_row.addWidget(self.install_update_button)
        update_layout.addLayout(update_row)
        self.update_progress_bar = QProgressBar()
        self.update_progress_bar.setTextVisible(False)
        self.update_progress_bar.setRange(0, 100)
        self.update_progress_bar.setValue(0)
        self.update_progress_bar.hide()
        update_layout.addWidget(self.update_progress_bar)
        body_layout.addWidget(update)

        service, service_layout = self._panel(
            "Windows Service",
            "Use the service for normal operation. It starts automatically with Windows.",
        )
        service_buttons = QHBoxLayout()
        self.install_button = QPushButton(text="Install / Reinstall")
        self.install_button.setObjectName("PrimaryButton")
        self.install_button.clicked.connect(self.install_or_upgrade_service)
        self.start_button = QPushButton("Start")
        self.start_button.clicked.connect(lambda: self.run_service_action("start"))
        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("DangerButton")
        self.stop_button.clicked.connect(lambda: self.run_service_action("stop"))
        self.restart_button = QPushButton("Restart")
        self.restart_button.clicked.connect(lambda: self.run_service_action("restart"))
        for button in (
            self.install_button,
            self.start_button,
            self.stop_button,
            self.restart_button,
        ):
            service_buttons.addWidget(button)
        service_buttons.addStretch()
        service_layout.addLayout(service_buttons)
        body_layout.addWidget(service)

        direct, direct_layout = self._panel(
            "Direct run",
            "Run the worker interactively only for setup and troubleshooting.",
        )
        direct_buttons = QHBoxLayout()
        self.direct_start_button = QPushButton("Run directly")
        self.direct_start_button.clicked.connect(self.start_direct)
        self.direct_stop_button = QPushButton("Stop direct process")
        self.direct_stop_button.clicked.connect(self.stop_direct)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh_status)
        direct_buttons.addWidget(self.direct_start_button)
        direct_buttons.addWidget(self.direct_stop_button)
        direct_buttons.addWidget(refresh_button)
        direct_buttons.addStretch()
        direct_layout.addLayout(direct_buttons)
        body_layout.addWidget(direct)
        body_layout.addStretch()
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        return page

    def _status_row(
        self,
        grid: QGridLayout,
        row: int,
        label: str,
        initial: str,
    ) -> tuple[QLabel, QLabel]:
        field = QLabel(label)
        field.setObjectName("FieldLabel")
        dot = QLabel("●")
        dot.setObjectName("StatusDotNeutral")
        value = QLabel(initial)
        value.setWordWrap(True)
        grid.addWidget(field, row, 0)
        grid.addWidget(dot, row, 1)
        grid.addWidget(value, row, 2)
        return dot, value

    def _metadata_row(
        self,
        grid: QGridLayout,
        row: int,
        label: str,
        initial: str = "",
    ) -> QLabel:
        field = QLabel(label)
        field.setObjectName("FieldLabel")
        value = QLabel(initial)
        value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        value.setWordWrap(True)
        grid.addWidget(field, row, 0)
        grid.addWidget(value, row, 1, 1, 2)
        return value

    def _build_configuration_page(self) -> QWidget:
        page, layout = self._page(
            "Configuration",
            "Configure RADAR, VNPAY SSO, the local APK Scanner and worker timing.",
        )
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 6, 0)

        panel, panel_layout = self._panel("Agent configuration")
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setHorizontalSpacing(28)
        form.setVerticalSpacing(12)

        self.base_url = self._line_edit("https://radar.example.com")
        self.agent_id = self._line_edit("windows-scanner-01")
        self.display_name = self._line_edit("Windows Scanner 01")
        self.scanner_url = self._line_edit("http://127.0.0.1:8000")
        self.token_url = self._line_edit("https://sso.example.com/realms/.../token")
        self.client_id = self._line_edit("vnpay-radar-agent")
        self.client_secret = self._line_edit()
        self.client_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.client_secret.setPlaceholderText("Leave blank to keep the protected value")
        self.heartbeat_interval = self._spinbox(5, 30)
        self.poll_wait = self._spinbox(0, 25)
        self.lease_interval = self._spinbox(5, 30)
        self.scanner_timeout = self._spinbox(30, 900)
        self.retry_delay = self._spinbox(1, 60)

        for label, widget in (
            ("RADAR URL", self.base_url),
            ("Agent ID", self.agent_id),
            ("Display name", self.display_name),
            ("APK Scanner URL", self.scanner_url),
            ("SSO token URL", self.token_url),
            ("Client ID", self.client_id),
            ("Client secret", self.client_secret),
            ("Heartbeat interval (seconds)", self.heartbeat_interval),
            ("Claim wait (seconds)", self.poll_wait),
            ("Lease renewal (seconds)", self.lease_interval),
            ("Scanner timeout (seconds)", self.scanner_timeout),
            ("Retry delay (seconds)", self.retry_delay),
        ):
            field_label = QLabel(label)
            field_label.setObjectName("FieldLabel")
            form.addRow(field_label, widget)

        self.verify_tls = QCheckBox("Verify TLS certificates")
        form.addRow(self._field_label("TLS"), self.verify_tls)
        panel_layout.addLayout(form)
        note = QLabel("Client secret is encrypted with Windows DPAPI when saved.")
        note.setObjectName("MutedLabel")
        panel_layout.addWidget(note)
        actions = QHBoxLayout()
        save_button = QPushButton("Save configuration")
        save_button.setObjectName("PrimaryButton")
        save_button.clicked.connect(lambda: self.save_configuration())
        reload_button = QPushButton("Reload")
        reload_button.clicked.connect(self.reload_configuration)
        actions.addWidget(save_button)
        actions.addWidget(reload_button)
        actions.addStretch()
        panel_layout.addLayout(actions)
        body_layout.addWidget(panel)

        dast_panel, dast_layout = self._panel(
            "DAST worker",
            "Runs as a second logical agent and connects only to the local DAST engine.",
        )
        self.dast_enabled = QCheckBox("Enable DAST worker")
        dast_layout.addWidget(self.dast_enabled)
        dast_form = QFormLayout()
        dast_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        dast_form.setHorizontalSpacing(28)
        dast_form.setVerticalSpacing(12)
        self.dast_agent_id = self._line_edit("windows-scanner-01-dast")
        self.dast_display_name = self._line_edit("Windows Scanner 01 DAST")
        self.dast_engine_url = self._line_edit("http://127.0.0.1:8010")
        self.dast_engine_api_key = self._line_edit()
        self.dast_engine_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.dast_engine_api_key.setPlaceholderText(
            "Leave blank to keep the protected value"
        )
        for label, widget in (
            ("DAST Agent ID", self.dast_agent_id),
            ("DAST display name", self.dast_display_name),
            ("DAST engine URL", self.dast_engine_url),
            ("Engine API key", self.dast_engine_api_key),
        ):
            dast_form.addRow(self._field_label(label), widget)
        dast_layout.addLayout(dast_form)
        dast_principals_label = QLabel("Protected principals JSON")
        dast_principals_label.setObjectName("FieldLabel")
        dast_layout.addWidget(dast_principals_label)
        self.dast_principals = QPlainTextEdit()
        self.dast_principals.setPlaceholderText(
            '{"projects":{"<project-uuid>":{"admin_user":{"token":"..."}}}}\n'
            "Leave blank to keep the protected value."
        )
        self.dast_principals.setMaximumHeight(120)
        dast_layout.addWidget(self.dast_principals)
        dast_note = QLabel(
            "The engine API key and principal credentials are encrypted with Windows DPAPI."
        )
        dast_note.setObjectName("MutedLabel")
        dast_layout.addWidget(dast_note)
        body_layout.addWidget(dast_panel)
        body_layout.addStretch()
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        return page

    def _field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        return label

    def _line_edit(self, placeholder: str = "") -> QLineEdit:
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        edit.setClearButtonEnabled(True)
        return edit

    def _spinbox(self, minimum: int, maximum: int) -> NumericStepper:
        return NumericStepper(minimum, maximum)

    def _build_diagnostics_page(self) -> QWidget:
        page, layout = self._page(
            "Diagnostics",
            "Run independent connectivity checks. Results appear as each component completes.",
        )
        toolbar = QHBoxLayout()
        self.diagnostic_button = QPushButton("Run checks")
        self.diagnostic_button.setObjectName("PrimaryButton")
        self._diagnostic_idle_icon = self.style().standardIcon(
            QStyle.StandardPixmap.SP_DialogApplyButton
        )
        self.diagnostic_button.setIcon(self._diagnostic_idle_icon)
        self.diagnostic_button.clicked.connect(self.run_checks)
        self._diagnostic_spinner_frame = 0
        self._diagnostic_spinner_timer = QTimer(self)
        self._diagnostic_spinner_timer.setInterval(80)
        self._diagnostic_spinner_timer.timeout.connect(self._advance_diagnostic_spinner)
        self.diagnostic_summary_label = QLabel("Not run")
        self.diagnostic_summary_label.setObjectName("MutedLabel")
        toolbar.addWidget(self.diagnostic_button)
        toolbar.addWidget(self.diagnostic_summary_label)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.diagnostic_table = QTableWidget(0, 4)
        self.diagnostic_table.setHorizontalHeaderLabels(
            ["Component", "Result", "Detail", "Latency"]
        )
        self.diagnostic_table.setAlternatingRowColors(True)
        self.diagnostic_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.diagnostic_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.diagnostic_table.verticalHeader().setVisible(False)
        self.diagnostic_table.verticalHeader().setDefaultSectionSize(46)
        header = self.diagnostic_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.diagnostic_table.setColumnWidth(0, 180)
        self.diagnostic_table.setColumnWidth(1, 116)
        self.diagnostic_table.setColumnWidth(3, 116)
        for column in range(self.diagnostic_table.columnCount()):
            alignment = (
                Qt.AlignmentFlag.AlignRight
                if column == 3
                else Qt.AlignmentFlag.AlignLeft
            )
            self.diagnostic_table.horizontalHeaderItem(column).setTextAlignment(
                alignment | Qt.AlignmentFlag.AlignVCenter
            )
        layout.addWidget(self.diagnostic_table, 1)
        return page

    def _build_logs_page(self) -> QWidget:
        page, layout = self._page(
            "Logs",
            "Review recent worker output without leaving Scanner Manager.",
        )
        toolbar = QHBoxLayout()
        self.log_search = QLineEdit()
        self.log_search.setPlaceholderText("Find in logs")
        self.log_search.setMaximumWidth(300)
        self.log_search.textChanged.connect(self._find_log_text)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_logs)
        copy = QPushButton("Copy")
        copy.clicked.connect(self._copy_logs)
        folder = QPushButton("Open folder")
        folder.clicked.connect(self.open_log_folder)
        self.log_autoscroll = QCheckBox("Auto-scroll")
        self.log_autoscroll.setChecked(True)
        toolbar.addWidget(self.log_search)
        toolbar.addWidget(refresh)
        toolbar.addWidget(copy)
        toolbar.addWidget(folder)
        toolbar.addStretch()
        toolbar.addWidget(self.log_autoscroll)
        layout.addLayout(toolbar)

        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_output.setStyleSheet("font-family: Consolas; font-size: 12px;")
        self.log_output.setPlaceholderText("No log output is available yet.")
        layout.addWidget(self.log_output, 1)
        return page

    def _select_page(self, index: int) -> None:
        self.page_stack.setCurrentIndex(index)
        if 0 <= index < len(self.nav_buttons):
            self.nav_buttons[index].setChecked(True)
        if index == 3:
            self.refresh_logs()

    def _load_settings_safely(self) -> AgentSettings:
        try:
            settings = load_settings(self._config_path)
            self._configuration_error = ""
            return settings
        except PermissionError:
            self._configuration_error = "Administrator access is required"
            return AgentSettings(_env_file=None)
        except Exception as exc:
            self._configuration_error = str(exc)
            return AgentSettings(_env_file=None)

    def _load_form(self) -> None:
        settings = self._settings
        self.base_url.setText(settings.base_url)
        self.agent_id.setText(settings.id)
        self.display_name.setText(settings.display_name)
        self.scanner_url.setText(settings.scanner_url)
        self.dast_enabled.setChecked(settings.dast_enabled)
        self.dast_agent_id.setText(settings.dast_agent_id)
        self.dast_display_name.setText(settings.dast_display_name)
        self.dast_engine_url.setText(settings.dast_engine_url)
        self.dast_engine_api_key.clear()
        self.dast_principals.clear()
        self.token_url.setText(settings.token_url)
        self.client_id.setText(settings.client_id)
        self.client_secret.clear()
        self.verify_tls.setChecked(settings.verify_tls)
        self.heartbeat_interval.setValue(settings.heartbeat_interval_seconds)
        self.poll_wait.setValue(settings.poll_wait_seconds)
        self.lease_interval.setValue(settings.lease_renew_interval_seconds)
        self.scanner_timeout.setValue(settings.scanner_timeout_seconds)
        self.retry_delay.setValue(settings.retry_delay_seconds)

    def _collect_settings(self) -> AgentSettings:
        secret_file = self._config_path.parent / "client-secret.dpapi"
        return AgentSettings(
            _env_file=None,
            base_url=self.base_url.text().strip(),
            id=self.agent_id.text().strip(),
            display_name=self.display_name.text().strip(),
            scanner_url=self.scanner_url.text().strip(),
            dast_enabled=self.dast_enabled.isChecked(),
            dast_agent_id=self.dast_agent_id.text().strip(),
            dast_display_name=self.dast_display_name.text().strip(),
            dast_engine_url=self.dast_engine_url.text().strip(),
            dast_engine_api_key=self.dast_engine_api_key.text(),
            dast_engine_api_key_file=self._settings.dast_engine_api_key_file,
            dast_principals_file=self._settings.dast_principals_file,
            dast_poll_interval_seconds=self._settings.dast_poll_interval_seconds,
            dast_timeout_seconds=self._settings.dast_timeout_seconds,
            token_url=self.token_url.text().strip(),
            client_id=self.client_id.text().strip(),
            client_secret=self.client_secret.text(),
            client_secret_file=secret_file if secret_file.exists() else None,
            database_path=self._config_path.parent / "agent.db",
            verify_tls=self.verify_tls.isChecked(),
            heartbeat_interval_seconds=self.heartbeat_interval.value(),
            poll_wait_seconds=self.poll_wait.value(),
            lease_renew_interval_seconds=self.lease_interval.value(),
            scanner_timeout_seconds=self.scanner_timeout.value(),
            retry_delay_seconds=self.retry_delay.value(),
        )

    def reload_configuration(self) -> None:
        self._config_path = default_config_path(self._package_root)
        self._settings = self._load_settings_safely()
        self._load_form()
        self.refresh_status()

    def save_configuration(self, *, show_message: bool = True) -> bool:
        try:
            settings = self._collect_settings()
            machine_scope = self._config_path.parent.resolve() == program_data_directory().resolve()
            save_settings(
                settings,
                self._config_path,
                client_secret=self.client_secret.text(),
                dast_engine_api_key=self.dast_engine_api_key.text(),
                dast_principals_json=self.dast_principals.toPlainText(),
                machine_scope=machine_scope,
            )
            self._settings = load_settings(self._config_path)
            self.client_secret.clear()
            self.dast_engine_api_key.clear()
            self.dast_principals.clear()
            if show_message:
                QMessageBox.information(self, "Configuration", "Configuration saved securely.")
            self.refresh_status()
            return True
        except (ValidationError, ValueError, OSError) as exc:
            QMessageBox.critical(self, "Configuration error", str(exc))
            return False

    def _start_task(
        self,
        key: str,
        operation: Callable[[], object],
        on_success: Callable[[object], None],
        on_error: Callable[[str], None],
    ) -> bool:
        if key in self._tasks:
            return False
        self._tasks[key] = (on_success, on_error)

        def worker() -> None:
            try:
                result = operation()
            except Exception as exc:
                self.events.task_failed.emit(key, str(exc))
            else:
                self.events.task_completed.emit(key, result)

        threading.Thread(target=worker, name=f"manager-{key}", daemon=True).start()
        return True

    @Slot(str, object)
    def _task_completed(self, key: str, result: object) -> None:
        callbacks = self._tasks.pop(key, None)
        if callbacks:
            callbacks[0](result)

    @Slot(str, str)
    def _task_failed(self, key: str, error: str) -> None:
        callbacks = self._tasks.pop(key, None)
        if callbacks:
            callbacks[1](error)

    def refresh_status(self) -> None:
        self._start_task(
            "status",
            query_service,
            lambda state: self._apply_status(state),
            lambda _error: self._apply_status(ServiceState(False, "unknown")),
        )

    def _apply_status(self, state: ServiceState) -> None:
        direct_running = self._direct_process is not None and self._direct_process.poll() is None
        self.service_status.setText(
            f"{state.status.title()} ({state.start_mode})" if state.installed else "Not installed"
        )
        service_tone = "success" if state.status == "running" else "warning"
        if not state.installed or state.status == "unknown":
            service_tone = "error"
        self._set_dot(self.service_dot, service_tone)
        self.direct_status.setText("Running" if direct_running else "Stopped")
        self._set_dot(self.direct_dot, "success" if direct_running else "neutral")
        self.agent_status.setText(self.agent_id.text() or self._settings.id)
        config_text = str(self._config_path)
        if self._configuration_error:
            config_text = f"{config_text} ({self._configuration_error})"
        self.config_status.setText(config_text)
        self.package_status.setText(str(self._package_root))
        if not self._interaction_locked:
            self.start_button.setEnabled(state.installed and state.status != "running")
            self.stop_button.setEnabled(state.installed and state.status == "running")
            self.restart_button.setEnabled(state.installed and state.status == "running")
            self.direct_start_button.setEnabled(not direct_running and state.status != "running")
            self.direct_stop_button.setEnabled(direct_running)

    def _set_dot(self, label: QLabel, tone: str) -> None:
        names = {
            "success": "StatusDotSuccess",
            "error": "StatusDotError",
            "warning": "StatusDotWarning",
            "neutral": "StatusDotNeutral",
        }
        label.setObjectName(names[tone])
        label.style().unpolish(label)
        label.style().polish(label)

    def _set_label_tone(self, label: QLabel, tone: str) -> None:
        names = {
            "success": "StatusSuccess",
            "error": "StatusError",
            "warning": "StatusWarning",
            "busy": "StatusBusy",
            "neutral": "",
        }
        label.setObjectName(names[tone])
        label.style().unpolish(label)
        label.style().polish(label)

    def _set_interaction_locked(self, locked: bool, message: str = "") -> None:
        self._interaction_locked = locked
        self.sidebar.setEnabled(not locked)
        self.page_stack.setEnabled(not locked)
        if locked:
            self.setCursor(Qt.CursorShape.WaitCursor)
            self.update_status_label.setText(message)
            self._set_label_tone(self.update_status_label, "busy")
            self.update_progress_bar.setRange(0, 0)
            self.update_progress_bar.show()
        else:
            self.unsetCursor()
            self.update_progress_bar.hide()
            self.update_progress_bar.setRange(0, 100)
            self.update_progress_bar.setValue(0)
            self.refresh_status()

    def check_for_updates(self, *, silent: bool = False) -> None:
        if self._update_check_running or self._update_install_running:
            return
        self._update_check_running = True
        self.check_update_button.setEnabled(False)
        self.install_update_button.setEnabled(False)
        self.update_status_label.setText("Checking for updates...")
        self._set_label_tone(self.update_status_label, "busy")
        self._start_task(
            "update-check",
            lambda: check_for_update(__version__),
            lambda result: self._show_update_result(result),
            lambda error: self._show_update_error(error, silent),
        )

    def _show_update_result(self, update: object) -> None:
        assert isinstance(update, UpdateInfo)
        self._update_check_running = False
        self.check_update_button.setEnabled(True)
        if update.available:
            self._available_update = update
            self.update_status_label.setText(f"Version {update.latest_version} is available")
            self._set_label_tone(self.update_status_label, "warning")
            self.install_update_button.show()
            self.install_update_button.setEnabled(True)
        else:
            self._available_update = None
            self.update_status_label.setText(f"Up to date ({__version__})")
            self._set_label_tone(self.update_status_label, "success")
            self.install_update_button.setEnabled(False)
            self.install_update_button.hide()

    def _show_update_error(self, error: str, silent: bool) -> None:
        self._update_check_running = False
        self.check_update_button.setEnabled(True)
        self.install_update_button.setVisible(self._available_update is not None)
        self.install_update_button.setEnabled(self._available_update is not None)
        self.update_status_label.setText("Unable to check for updates")
        self._set_label_tone(self.update_status_label, "error")
        if not silent:
            QMessageBox.critical(self, "Software update", error)

    def _show_installer_status(self, status: InstallerStatus | None) -> None:
        if status is None:
            return
        version = status.version or "unknown"
        if status.state == "success" and version == __version__:
            self.update_status_label.setText(f"Updated successfully to version {version}")
            self._set_label_tone(self.update_status_label, "success")
            return
        if status.state == "failed":
            detail = f": {status.message}" if status.message else ""
            text = f"Update to version {version} failed{detail}"
        elif status.state == "installing":
            text = f"Update to version {version} did not complete. Run the installer again."
        else:
            text = f"Setup reported version {version}, but Manager is version {__version__}"
        self.update_status_label.setText(text)
        self._set_label_tone(self.update_status_label, "error")

    def install_available_update(self) -> None:
        update = self._available_update
        if update is None or self._update_install_running:
            return
        if self._diagnostics_running or self._operation_running:
            QMessageBox.warning(
                self,
                "Software update",
                "Wait for the current operation to finish before updating.",
            )
            return
        answer = QMessageBox.question(
            self,
            "Software update",
            f"Install version {update.latest_version} now?\n\n"
            "The Manager will close and the Windows Service will restart automatically.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._update_install_running = True
        self._set_interaction_locked(
            True,
            f"Downloading Scanner Agent {update.latest_version}",
        )
        self.update_status_label.setText(f"Downloading version {update.latest_version}...")
        self._set_label_tone(self.update_status_label, "busy")

        def progress(received: int, total: int | None) -> None:
            if total:
                percent = min(100, int(received * 100 / total))
                message = f"Downloading Scanner Agent {update.latest_version} · {percent}%"
            else:
                percent = -1
                message = (
                    f"Downloading Scanner Agent {update.latest_version} · " f"{received // 1024} KB"
                )
            self.events.update_progress.emit(message, percent)

        self._start_task(
            "update-download",
            lambda: download_installer(
                update,
                program_data_directory() / "updates",
                progress=progress,
            ),
            lambda installer: self._launch_downloaded_update(
                Path(installer), update.latest_version
            ),
            self._update_download_failed,
        )

    @Slot(str, int)
    def _show_update_progress(self, message: str, percent: int = -1) -> None:
        self.update_status_label.setText(message)
        if percent >= 0:
            self.update_progress_bar.setRange(0, 100)
            self.update_progress_bar.setValue(percent)
        else:
            self.update_progress_bar.setRange(0, 0)

    def _update_download_failed(self, error: str) -> None:
        self._update_install_running = False
        self._set_interaction_locked(False)
        self.check_update_button.setEnabled(True)
        self.install_update_button.show()
        self.install_update_button.setEnabled(True)
        self.update_status_label.setText("Update download failed")
        self._set_label_tone(self.update_status_label, "error")
        QMessageBox.critical(self, "Software update", error)

    def _launch_downloaded_update(self, installer: Path, target_version: str) -> None:
        try:
            if self._direct_process is not None and self._direct_process.poll() is None:
                self.stop_direct()
            self.update_status_label.setText("Starting update progress window...")
            self.update_progress_bar.setRange(0, 0)
            updater = self._package_root / "radar-scanner-updater.exe"
            if updater.is_file():
                launch_updater(updater, installer, target_version)
            else:
                launch_installer(installer)
        except Exception as exc:
            self._update_download_failed(str(exc))
            return
        self.update_status_label.setText(
            "Updater started. Manager will close during installation..."
        )

    def _run_operation(
        self,
        operation: Callable[[], object],
        *,
        title: str,
        success_message: str,
    ) -> None:
        if self._operation_running:
            return
        self._operation_running = True

        def success(_result: object) -> None:
            QMessageBox.information(self, title, success_message)
            self._operation_finished()

        def failure(error: str) -> None:
            QMessageBox.critical(self, title, error)
            self._operation_finished()

        self._start_task("operation", operation, success, failure)

    def _operation_finished(self) -> None:
        self._operation_running = False
        self.reload_configuration()
        self.refresh_logs()

    def run_service_action(self, action: str) -> None:
        self._run_operation(
            lambda: service_action(action),
            title="Windows Service",
            success_message=f"Service {action} completed.",
        )

    def install_or_upgrade_service(self) -> None:
        if not self.save_configuration(show_message=False):
            return
        settings = load_settings(self._config_path)
        try:
            secret = settings.resolved_client_secret()
        except (ValueError, OSError) as exc:
            QMessageBox.critical(self, "Service installation error", str(exc))
            return

        def operation() -> None:
            temporary_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    suffix=".env",
                    prefix="radar-agent-install-",
                    delete=False,
                    encoding="utf-8",
                ) as temporary:
                    temporary.write(plaintext_bootstrap(settings, secret))
                    temporary_path = Path(temporary.name)
                os.chmod(temporary_path, 0o600)
                install_service(self._package_root, temporary_path)
            finally:
                if temporary_path and temporary_path.exists():
                    size = temporary_path.stat().st_size
                    temporary_path.write_bytes(b"\x00" * size)
                    temporary_path.unlink(missing_ok=True)

        self._run_operation(
            operation,
            title="Windows Service",
            success_message=f"{SERVICE_NAME} is installed and running.",
        )

    def start_direct(self) -> None:
        try:
            state = query_service()
        except Exception as exc:
            QMessageBox.critical(self, "Direct run error", str(exc))
            return
        if state.status == "running":
            QMessageBox.warning(
                self,
                "Direct run blocked",
                "Stop the Windows Service before starting a direct Agent process.",
            )
            return
        if not self.save_configuration(show_message=False):
            return
        executable = worker_executable(self._package_root)
        if not executable.exists():
            QMessageBox.critical(self, "Direct run error", f"Worker not found: {executable}")
            return
        try:
            self._direct_process = subprocess.Popen(
                [str(executable)],
                cwd=self._config_path.parent,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=_CREATE_NO_WINDOW,
            )
        except OSError as exc:
            QMessageBox.critical(self, "Direct run error", str(exc))
            return
        threading.Thread(target=self._read_process_output, daemon=True).start()
        self._select_page(3)
        self._set_log_text("")
        self.refresh_status()

    def _read_process_output(self) -> None:
        process = self._direct_process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            self.events.process_output.emit(line)
        process.wait()
        self.events.process_output.emit(
            f"\nDirect process exited with code {process.returncode}.\n"
        )

    def stop_direct(self) -> None:
        process = self._direct_process
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
        self.refresh_status()

    def run_checks(self) -> None:
        if self._diagnostics_running or self._interaction_locked:
            return
        try:
            settings = self._collect_settings()
            settings.validate_runtime()
        except (ValidationError, ValueError, OSError) as exc:
            QMessageBox.critical(self, "Diagnostics", str(exc))
            return
        self._diagnostics_running = True
        self._active_diagnostic_steps = _diagnostic_steps(settings)
        self._diagnostic_results.clear()
        self._diagnostic_rows.clear()
        self.diagnostic_button.setEnabled(False)
        self._set_diagnostics_running_visual(True)
        self.install_update_button.setEnabled(False)
        self.diagnostic_summary_label.setText(
            f"Running 0/{len(self._active_diagnostic_steps)} checks"
        )
        self._set_label_tone(self.diagnostic_summary_label, "busy")
        self.diagnostic_table.setRowCount(len(self._active_diagnostic_steps))
        for row, (key, label) in enumerate(self._active_diagnostic_steps):
            self._diagnostic_rows[key] = row
            self._set_diagnostic_row(row, label, "WAITING", "Waiting to run", "—", MUTED)

        def worker() -> list[DiagnosticResult]:
            return asyncio.run(
                run_diagnostics(
                    settings,
                    on_started=lambda key, label: self.events.diagnostic_started.emit(key, label),
                    on_result=lambda result: self.events.diagnostic_completed.emit(result),
                )
            )

        self._start_task(
            "diagnostics",
            worker,
            lambda results: self._diagnostics_finished(list(results)),
            self._diagnostics_failed,
        )

    def _set_diagnostic_row(
        self,
        row: int,
        component: str,
        result: str,
        detail: str,
        latency: str,
        color: str,
    ) -> None:
        values = (component, result, detail, latency)
        for column, value in enumerate(values):
            item = self.diagnostic_table.item(row, column) or QTableWidgetItem()
            item.setText(value)
            if column == 1:
                item.setForeground(QBrush(QColor(color)))
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            if column == 3:
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
            self.diagnostic_table.setItem(row, column, item)

    @Slot(str, str)
    def _diagnostic_started(self, key: str, label: str) -> None:
        row = self._diagnostic_rows.get(key)
        if row is not None:
            self._set_diagnostic_row(
                row,
                label,
                "RUNNING",
                "Checking connection...",
                "—",
                BLUE_BRIGHT,
            )

    @Slot(object)
    def _diagnostic_completed(self, result: object) -> None:
        assert isinstance(result, DiagnosticResult)
        self._diagnostic_results[result.key] = result
        row = self._diagnostic_rows.get(result.key)
        if row is not None:
            self._set_diagnostic_row(
                row,
                result.label,
                "PASSED" if result.success else "FAILED",
                result.detail,
                f"{result.duration_ms} ms",
                GREEN if result.success else RED,
            )
        passed = sum(item.success for item in self._diagnostic_results.values())
        completed = len(self._diagnostic_results)
        self.diagnostic_summary_label.setText(
            f"Running {completed}/{len(self._active_diagnostic_steps)} · {passed} passed"
        )

    def _diagnostics_finished(self, results: list[DiagnosticResult]) -> None:
        self._diagnostics_running = False
        self._set_diagnostics_running_visual(False)
        passed = sum(result.success for result in results)
        self.diagnostic_summary_label.setText(f"{passed}/{len(results)} checks passed")
        self._set_label_tone(
            self.diagnostic_summary_label,
            "success" if passed == len(results) else "error",
        )
        if not self._interaction_locked:
            self.diagnostic_button.setEnabled(True)
            self.install_update_button.setEnabled(self._available_update is not None)

    def _diagnostics_failed(self, error: str) -> None:
        self._diagnostics_running = False
        self._set_diagnostics_running_visual(False)
        self.diagnostic_summary_label.setText("Diagnostics failed")
        self._set_label_tone(self.diagnostic_summary_label, "error")
        if not self._interaction_locked:
            self.diagnostic_button.setEnabled(True)
            self.install_update_button.setEnabled(self._available_update is not None)
        QMessageBox.critical(self, "Diagnostics", error)

    def _set_diagnostics_running_visual(self, running: bool) -> None:
        if running:
            self._diagnostic_spinner_frame = 0
            self.diagnostic_button.setText("Running checks")
            self.diagnostic_button.setIcon(_diagnostic_spinner_icon(0))
            self._diagnostic_spinner_timer.start()
            return
        self._diagnostic_spinner_timer.stop()
        self.diagnostic_button.setText("Run checks")
        self.diagnostic_button.setIcon(self._diagnostic_idle_icon)

    def _advance_diagnostic_spinner(self) -> None:
        self._diagnostic_spinner_frame = (self._diagnostic_spinner_frame + 1) % 12
        self.diagnostic_button.setIcon(_diagnostic_spinner_icon(self._diagnostic_spinner_frame))

    def _set_log_text(self, content: str) -> None:
        self.log_output.setPlainText(content)
        if self.log_autoscroll.isChecked():
            QTimer.singleShot(0, self._scroll_logs_to_bottom_left)

    @Slot(str)
    def _append_log_text(self, content: str) -> None:
        cursor = QTextCursor(self.log_output.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(content)
        if self.log_autoscroll.isChecked():
            QTimer.singleShot(0, self._scroll_logs_to_bottom_left)

    def _scroll_logs_to_bottom_left(self) -> None:
        vertical = self.log_output.verticalScrollBar()
        horizontal = self.log_output.horizontalScrollBar()
        vertical.setValue(vertical.maximum())
        horizontal.setValue(horizontal.minimum())

    def refresh_logs(self) -> None:
        if self._direct_process is not None and self._direct_process.poll() is None:
            return
        try:
            self._set_log_text(read_service_log())
        except OSError as exc:
            self._set_log_text(f"Unable to read logs: {exc}")

    def _find_log_text(self, query: str) -> None:
        if not query:
            return
        cursor = self.log_output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.log_output.setTextCursor(cursor)
        self.log_output.find(query)

    def _copy_logs(self) -> None:
        selected = self.log_output.textCursor().selectedText()
        QApplication.clipboard().setText(selected or self.log_output.toPlainText())

    def open_log_folder(self) -> None:
        folder = service_log_path().parent
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _start_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        try:
            self._tray = TrayController(
                parent=self,
                icon=radar_icon(),
                open_manager=self._show_manager,
                run_diagnostics=self._run_diagnostics_from_tray,
                open_logs=self._open_logs_from_tray,
                check_updates=self.check_for_updates,
                start_service=lambda: self.run_service_action("start"),
                stop_service=lambda: self.run_service_action("stop"),
                restart_service=lambda: self.run_service_action("restart"),
                exit_application=self._exit_application,
                actions_enabled=lambda: not self._interaction_locked,
            )
            self._tray.start()
        except Exception:
            self._tray = None

    def _show_manager(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _run_diagnostics_from_tray(self) -> None:
        if self._interaction_locked:
            return
        self._show_manager()
        self._select_page(2)
        self.run_checks()

    def _open_logs_from_tray(self) -> None:
        if self._interaction_locked:
            return
        self._show_manager()
        self._select_page(3)

    def _exit_application(self) -> None:
        if self._interaction_locked:
            QMessageBox.information(
                self,
                "Update in progress",
                "Scanner Manager cannot exit while an update is in progress.",
            )
            return
        direct_running = self._direct_process is not None and self._direct_process.poll() is None
        if direct_running:
            answer = QMessageBox.question(
                self,
                "Stop direct process?",
                "Exiting the Manager will stop the direct Agent process. Continue?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            self.stop_direct()
        self._exiting = True
        if self._tray is not None:
            self._tray.stop()
        QApplication.quit()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._exiting:
            event.accept()
            return
        if self._interaction_locked:
            QMessageBox.information(
                self,
                "Update in progress",
                "Wait for the update process to open before closing Scanner Manager.",
            )
            event.ignore()
            return
        if self._tray is None:
            self._exit_application()
            event.accept()
            return
        self.hide()
        event.ignore()
        if not self._tray_notice_shown:
            self._tray_notice_shown = True
            self._tray.notify_minimized()


def main() -> None:
    set_windows_app_user_model_id(MANAGER_APP_USER_MODEL_ID)
    instance = SingleInstance()
    if not instance.acquire():
        focus_existing_manager()
        return
    try:
        application = QApplication(sys.argv)
        application.setApplicationName("VNPAY RADAR Scanner Manager")
        application.setApplicationVersion(__version__)
        application.setQuitOnLastWindowClosed(False)
        configure_radar_theme(application)
        window = ManagerWindow()
        window.show()
        raise SystemExit(application.exec())
    finally:
        instance.close()


if __name__ == "__main__":
    main()
