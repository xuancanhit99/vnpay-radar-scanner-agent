import asyncio
import os
import queue
import subprocess
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from pydantic import ValidationError

from radar_agent import __version__
from radar_agent.config_store import (
    load_settings,
    plaintext_bootstrap,
    save_settings,
)
from radar_agent.desktop_shell import SingleInstance, TrayController, focus_existing_manager
from radar_agent.desktop_theme import (
    BACKGROUND,
    BLUE_BRIGHT,
    GREEN,
    INPUT,
    MUTED,
    RED,
    TEXT,
    apply_window_icon,
    configure_radar_theme,
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


class ManagerWindow(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"VNPAY RADAR Scanner Manager {__version__}")
        self.geometry("1080x760")
        self.minsize(920, 640)

        self._package_root = package_root()
        self._config_path = default_config_path(self._package_root)
        self._configuration_error = ""
        self._settings = self._load_settings_safely()
        self._direct_process: subprocess.Popen[str] | None = None
        self._process_output: queue.Queue[str] = queue.Queue()
        self._operation_running = False
        self._update_check_running = False
        self._update_install_running = False
        self._available_update: UpdateInfo | None = None
        self._status_refresh_running = False
        self._diagnostics_running = False
        self._diagnostic_results: dict[str, DiagnosticResult] = {}
        self._diagnostic_items: dict[str, str] = {}
        self._interaction_locked = False
        self._locked_widget_states: dict[ttk.Widget, bool] = {}
        self._logs_built = False
        self._tray: TrayController | None = None
        self._tray_notice_shown = False

        self._configure_style()
        apply_window_icon(self)
        self._build_ui()
        self._load_form()
        self.refresh_status()
        installer_status = read_installer_status()
        self._show_installer_status(installer_status)
        self.protocol("WM_DELETE_WINDOW", self._close_window)
        self.after(500, self._drain_process_output)
        if installer_status is None or installer_status.state == "success":
            delay = 5000 if installer_status else 1200
            self.after(delay, lambda: self.check_for_updates(silent=True))
        self.after(200, self._start_tray)
        self.after(4000, self._status_tick)

    def _configure_style(self) -> None:
        style = configure_radar_theme(self)
        style.configure(
            "Version.TLabel",
            background=INPUT,
            foreground=BLUE_BRIGHT,
            padding=(10, 5),
            font=("Segoe UI Semibold", 9),
        )
        style.configure("Page.TFrame", background=BACKGROUND)

    def _build_ui(self) -> None:
        root = ttk.Frame(self, style="Root.TFrame", padding=(20, 16, 20, 20))
        root.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(root, style="Root.TFrame")
        header.pack(fill=tk.X)
        heading = ttk.Frame(header, style="Root.TFrame")
        heading.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(heading, text="VNPAY RADAR Scanner Manager", style="Title.TLabel").pack(
            anchor=tk.W
        )
        ttk.Label(
            heading,
            text="WINDOWS EDGE SCANNER CONTROL",
            style="Subtitle.TLabel",
        ).pack(anchor=tk.W)
        ttk.Label(header, text=f"VERSION {__version__}", style="Version.TLabel").pack(
            side=tk.RIGHT, anchor=tk.N, pady=(3, 0)
        )
        self.busy_status = tk.StringVar()
        ttk.Label(
            root,
            textvariable=self.busy_status,
            style="Busy.TLabel",
        ).pack(anchor=tk.W, pady=(5, 8))

        self.tabs = ttk.Notebook(root)
        self.tabs.pack(fill=tk.BOTH, expand=True)
        self.overview_tab = ttk.Frame(self.tabs, style="Page.TFrame", padding=18)
        self.configuration_tab = ttk.Frame(self.tabs, style="Page.TFrame", padding=18)
        self.diagnostics_tab = ttk.Frame(self.tabs, style="Page.TFrame", padding=18)
        self.logs_tab = ttk.Frame(self.tabs, style="Page.TFrame", padding=18)
        self.tabs.add(self.overview_tab, text="Overview")
        self.tabs.add(self.configuration_tab, text="Configuration")
        self.tabs.add(self.diagnostics_tab, text="Diagnostics")
        self.tabs.add(self.logs_tab, text="Logs")

        self._build_overview_tab()
        self._build_configuration_tab()
        self._build_diagnostics_tab()
        self.tabs.bind("<<NotebookTabChanged>>", self._tab_changed)

    def _build_overview_tab(self) -> None:
        page = self.overview_tab
        page.columnconfigure(0, weight=1)
        status = ttk.LabelFrame(page, text="Runtime status", style="Section.TLabelframe")
        status.grid(row=0, column=0, sticky="nsew")
        status.columnconfigure(1, weight=1)

        self.service_status = tk.StringVar(value="Checking...")
        self.direct_status = tk.StringVar(value="Checking...")
        self.agent_status = tk.StringVar()
        self.version_status = tk.StringVar(value=__version__)
        self.config_status = tk.StringVar()
        self.package_status = tk.StringVar()
        rows = (
            ("Windows Service", self.service_status),
            ("Direct process", self.direct_status),
            ("Agent ID", self.agent_status),
            ("Version", self.version_status),
            ("Configuration", self.config_status),
            ("Package", self.package_status),
        )
        for row, (label, variable) in enumerate(rows):
            ttk.Label(status, text=label, style="Field.TLabel").grid(
                row=row, column=0, sticky=tk.W, padx=(0, 24), pady=6
            )
            ttk.Label(status, textvariable=variable, style="Status.TLabel").grid(
                row=row, column=1, sticky=tk.W, pady=6
            )

        update = ttk.LabelFrame(page, text="Software update", style="Section.TLabelframe")
        update.grid(row=1, column=0, sticky="ew", pady=(16, 0))
        update.columnconfigure(0, weight=1)
        self.update_status = tk.StringVar(value="Checking for updates...")
        self.update_status_label = ttk.Label(
            update,
            textvariable=self.update_status,
            style="Status.TLabel",
            justify=tk.LEFT,
            wraplength=620,
        )
        self.update_status_label.grid(row=0, column=0, sticky=tk.W, padx=(0, 16))
        self.check_update_button = ttk.Button(
            update,
            text="Check again",
            command=self.check_for_updates,
        )
        self.check_update_button.grid(row=0, column=1, padx=(0, 9))
        self.install_update_button = ttk.Button(
            update,
            text="Update now",
            command=self.install_available_update,
            state=tk.DISABLED,
            style="Primary.TButton",
        )
        self.install_update_button.grid(row=0, column=2)

        service = ttk.LabelFrame(page, text="Windows Service", style="Section.TLabelframe")
        service.grid(row=2, column=0, sticky="ew", pady=(16, 0))
        self.install_button = ttk.Button(
            service,
            text="Install / Reinstall",
            command=self.install_or_upgrade_service,
            style="Primary.TButton",
        )
        self.start_button = ttk.Button(
            service, text="Start", command=lambda: self.run_service_action("start")
        )
        self.stop_button = ttk.Button(
            service,
            text="Stop",
            command=lambda: self.run_service_action("stop"),
            style="Danger.TButton",
        )
        self.restart_button = ttk.Button(
            service, text="Restart", command=lambda: self.run_service_action("restart")
        )
        for column, button in enumerate(
            (self.install_button, self.start_button, self.stop_button, self.restart_button)
        ):
            button.grid(row=0, column=column, padx=(0, 9))

        direct = ttk.LabelFrame(page, text="Direct run", style="Section.TLabelframe")
        direct.grid(row=3, column=0, sticky="ew", pady=(16, 0))
        self.direct_start_button = ttk.Button(
            direct, text="Run directly", command=self.start_direct
        )
        self.direct_stop_button = ttk.Button(
            direct, text="Stop direct process", command=self.stop_direct
        )
        refresh_button = ttk.Button(direct, text="Refresh", command=self.refresh_status)
        self.direct_start_button.grid(row=0, column=0, padx=(0, 9))
        self.direct_stop_button.grid(row=0, column=1, padx=(0, 9))
        refresh_button.grid(row=0, column=2)

        note = (
            "Use the Windows Service for normal operation. Direct run is intended for "
            "setup and diagnostics and is disabled while the service is running."
        )
        ttk.Label(page, text=note, style="Subtitle.TLabel", wraplength=820).grid(
            row=4, column=0, sticky=tk.W, pady=(16, 0)
        )

    def _build_configuration_tab(self) -> None:
        page = self.configuration_tab
        page.columnconfigure(0, weight=1)
        form = ttk.LabelFrame(page, text="Agent configuration", style="Section.TLabelframe")
        form.grid(row=0, column=0, sticky="nsew")
        form.columnconfigure(1, weight=1)
        self.base_url = tk.StringVar()
        self.agent_id = tk.StringVar()
        self.display_name = tk.StringVar()
        self.scanner_url = tk.StringVar()
        self.token_url = tk.StringVar()
        self.client_id = tk.StringVar()
        self.client_secret = tk.StringVar()
        self.device_model = tk.StringVar()
        self.verify_tls = tk.BooleanVar(value=True)
        self.heartbeat_interval = tk.IntVar(value=10)
        self.poll_wait = tk.IntVar(value=20)
        self.lease_interval = tk.IntVar(value=15)
        self.scanner_timeout = tk.IntVar(value=400)
        self.retry_delay = tk.IntVar(value=5)

        fields: tuple[tuple[str, tk.Variable, str], ...] = (
            ("RADAR URL", self.base_url, "entry"),
            ("Agent ID", self.agent_id, "entry"),
            ("Display name", self.display_name, "entry"),
            ("APK Scanner URL", self.scanner_url, "entry"),
            ("SSO token URL", self.token_url, "entry"),
            ("Client ID", self.client_id, "entry"),
            ("Client secret", self.client_secret, "secret"),
            ("Device model fallback", self.device_model, "entry"),
            ("Heartbeat interval (seconds)", self.heartbeat_interval, "spin:5:30"),
            ("Claim wait (seconds)", self.poll_wait, "spin:0:25"),
            ("Lease renewal (seconds)", self.lease_interval, "spin:5:30"),
            ("Scanner timeout (seconds)", self.scanner_timeout, "spin:30:900"),
            ("Retry delay (seconds)", self.retry_delay, "spin:1:60"),
        )
        for row, (label, variable, kind) in enumerate(fields):
            ttk.Label(form, text=label, style="Field.TLabel").grid(
                row=row, column=0, sticky=tk.W, padx=(0, 22), pady=6
            )
            if kind.startswith("spin:"):
                _, minimum, maximum = kind.split(":")
                widget = ttk.Spinbox(
                    form,
                    textvariable=variable,
                    from_=int(minimum),
                    to=int(maximum),
                    width=12,
                )
                widget.grid(row=row, column=1, sticky=tk.W, pady=6)
            else:
                widget = ttk.Entry(
                    form,
                    textvariable=variable,
                    show="*" if kind == "secret" else "",
                )
                widget.grid(row=row, column=1, sticky="ew", pady=6)

        tls_row = len(fields)
        ttk.Label(form, text="TLS", style="Field.TLabel").grid(
            row=tls_row, column=0, sticky=tk.W, padx=(0, 22), pady=6
        )
        ttk.Checkbutton(
            form,
            text="Verify TLS certificates",
            variable=self.verify_tls,
            style="Card.TCheckbutton",
        ).grid(row=tls_row, column=1, sticky=tk.W, pady=6)

        buttons = ttk.Frame(form, style="Card.TFrame")
        buttons.grid(row=tls_row + 1, column=1, sticky=tk.W, pady=(16, 0))
        ttk.Button(
            buttons,
            text="Save configuration",
            command=self.save_configuration,
            style="Primary.TButton",
        ).pack(side=tk.LEFT, padx=(0, 9))
        ttk.Button(buttons, text="Reload", command=self.reload_configuration).pack(side=tk.LEFT)
        ttk.Label(
            form,
            text="Leave Client secret blank to keep the existing DPAPI-protected value.",
            style="CardSubtitle.TLabel",
        ).grid(row=tls_row + 2, column=1, sticky=tk.W, pady=(10, 0))

    def _build_diagnostics_tab(self) -> None:
        page = self.diagnostics_tab
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        toolbar = ttk.Frame(page, style="Card.TFrame", padding=(12, 8))
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self.diagnostic_button = ttk.Button(
            toolbar,
            text="Run checks",
            command=self.run_checks,
            style="Primary.TButton",
        )
        self.diagnostic_button.pack(side=tk.LEFT)
        self.diagnostic_summary = tk.StringVar(value="Not run")
        self.diagnostic_summary_label = ttk.Label(
            toolbar, textvariable=self.diagnostic_summary, style="Status.TLabel"
        )
        self.diagnostic_summary_label.pack(side=tk.LEFT, padx=14)

        columns = ("component", "result", "detail", "latency")
        self.diagnostic_table = ttk.Treeview(page, columns=columns, show="headings")
        headings = {
            "component": "Component",
            "result": "Result",
            "detail": "Detail",
            "latency": "Latency",
        }
        for column, heading in headings.items():
            self.diagnostic_table.heading(column, text=heading)
        self.diagnostic_table.column("component", width=150, stretch=False)
        self.diagnostic_table.column("result", width=90, stretch=False)
        self.diagnostic_table.column("detail", width=520, stretch=True)
        self.diagnostic_table.column("latency", width=90, stretch=False, anchor=tk.E)
        self.diagnostic_table.tag_configure("waiting", foreground=MUTED)
        self.diagnostic_table.tag_configure("running", foreground=BLUE_BRIGHT)
        self.diagnostic_table.tag_configure("passed", foreground=GREEN)
        self.diagnostic_table.tag_configure("failed", foreground=RED)
        scrollbar = ttk.Scrollbar(page, orient=tk.VERTICAL, command=self.diagnostic_table.yview)
        self.diagnostic_table.configure(yscrollcommand=scrollbar.set)
        self.diagnostic_table.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")

    def _build_logs_tab(self) -> None:
        if self._logs_built:
            return
        self._logs_built = True
        page = self.logs_tab
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        toolbar = ttk.Frame(page, style="Card.TFrame", padding=(12, 8))
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ttk.Button(toolbar, text="Refresh", command=self.refresh_logs).pack(
            side=tk.LEFT, padx=(0, 9)
        )
        ttk.Button(toolbar, text="Open log folder", command=self.open_log_folder).pack(
            side=tk.LEFT
        )
        log_frame = ttk.Frame(page)
        log_frame.grid(row=1, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_output = tk.Text(
            log_frame,
            wrap=tk.NONE,
            state=tk.DISABLED,
            font=("Consolas", 9),
            background=INPUT,
            foreground=TEXT,
            insertbackground=TEXT,
            borderwidth=0,
            padx=10,
            pady=10,
        )
        vertical = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_output.yview)
        horizontal = ttk.Scrollbar(log_frame, orient=tk.HORIZONTAL, command=self.log_output.xview)
        self.log_output.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.log_output.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")

    def _tab_changed(self, _event: tk.Event | None = None) -> None:
        if self.tabs.select() != str(self.logs_tab):
            return
        self._build_logs_tab()
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
        self.base_url.set(settings.base_url)
        self.agent_id.set(settings.id)
        self.display_name.set(settings.display_name)
        self.scanner_url.set(settings.scanner_url)
        self.token_url.set(settings.token_url)
        self.client_id.set(settings.client_id)
        self.client_secret.set("")
        self.device_model.set(settings.device_model)
        self.verify_tls.set(settings.verify_tls)
        self.heartbeat_interval.set(settings.heartbeat_interval_seconds)
        self.poll_wait.set(settings.poll_wait_seconds)
        self.lease_interval.set(settings.lease_renew_interval_seconds)
        self.scanner_timeout.set(settings.scanner_timeout_seconds)
        self.retry_delay.set(settings.retry_delay_seconds)

    def _collect_settings(self) -> AgentSettings:
        secret_file = self._config_path.parent / "client-secret.dpapi"
        return AgentSettings(
            _env_file=None,
            base_url=self.base_url.get().strip(),
            id=self.agent_id.get().strip(),
            display_name=self.display_name.get().strip(),
            scanner_url=self.scanner_url.get().strip(),
            token_url=self.token_url.get().strip(),
            client_id=self.client_id.get().strip(),
            client_secret=self.client_secret.get(),
            client_secret_file=secret_file if secret_file.exists() else None,
            device_model=self.device_model.get().strip(),
            database_path=self._config_path.parent / "agent.db",
            verify_tls=self.verify_tls.get(),
            heartbeat_interval_seconds=self.heartbeat_interval.get(),
            poll_wait_seconds=self.poll_wait.get(),
            lease_renew_interval_seconds=self.lease_interval.get(),
            scanner_timeout_seconds=self.scanner_timeout.get(),
            retry_delay_seconds=self.retry_delay.get(),
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
                client_secret=self.client_secret.get(),
                machine_scope=machine_scope,
            )
            self._settings = load_settings(self._config_path)
            self.client_secret.set("")
            if show_message:
                messagebox.showinfo("Configuration", "Configuration saved securely.", parent=self)
            self.refresh_status()
            return True
        except (ValidationError, ValueError, OSError) as exc:
            messagebox.showerror("Configuration error", str(exc), parent=self)
            return False

    def refresh_status(self) -> None:
        if self._status_refresh_running:
            return
        self._status_refresh_running = True

        def worker() -> None:
            try:
                state = query_service()
            except Exception:
                state = ServiceState(False, "unknown")
            self.after(0, lambda: self._apply_status(state))

        threading.Thread(target=worker, name="manager-status-refresh", daemon=True).start()

    def _apply_status(self, state: ServiceState) -> None:
        self._status_refresh_running = False
        direct_running = self._direct_process is not None and self._direct_process.poll() is None
        self.service_status.set(
            f"{state.status} ({state.start_mode})" if state.installed else "Not installed"
        )
        self.direct_status.set("Running" if direct_running else "Stopped")
        self.agent_status.set(self.agent_id.get() or self._settings.id)
        config_text = str(self._config_path)
        if self._configuration_error:
            config_text = f"{config_text} ({self._configuration_error})"
        self.config_status.set(config_text)
        self.package_status.set(str(self._package_root))
        if not self._interaction_locked:
            self.start_button.configure(
                state=tk.NORMAL if state.installed and state.status != "running" else tk.DISABLED
            )
            self.stop_button.configure(
                state=tk.NORMAL if state.installed and state.status == "running" else tk.DISABLED
            )
            self.restart_button.configure(
                state=tk.NORMAL if state.installed and state.status == "running" else tk.DISABLED
            )
            self.direct_start_button.configure(
                state=tk.NORMAL if not direct_running and state.status != "running" else tk.DISABLED
            )
            self.direct_stop_button.configure(state=tk.NORMAL if direct_running else tk.DISABLED)

    def _status_tick(self) -> None:
        if self.winfo_exists():
            self.refresh_status()
            self.after(4000, self._status_tick)

    def _set_interaction_locked(self, locked: bool, message: str = "") -> None:
        interactive_types = (
            ttk.Button,
            ttk.Checkbutton,
            ttk.Entry,
            ttk.Notebook,
            ttk.Scrollbar,
            ttk.Spinbox,
            ttk.Treeview,
        )
        if locked:
            if self._interaction_locked:
                self.busy_status.set(message)
                return
            self._interaction_locked = True
            self._locked_widget_states.clear()
            pending = list(self.winfo_children())
            while pending:
                widget = pending.pop()
                pending.extend(widget.winfo_children())
                if isinstance(widget, interactive_types):
                    self._locked_widget_states[widget] = "disabled" in widget.state()
                    widget.state(["disabled"])
            self.configure(cursor="wait")
            self.busy_status.set(message)
            return

        for widget, was_disabled in self._locked_widget_states.items():
            if widget.winfo_exists():
                widget.state(["disabled"] if was_disabled else ["!disabled"])
        self._locked_widget_states.clear()
        self._interaction_locked = False
        self.configure(cursor="")
        self.busy_status.set("")
        self.refresh_status()

    def check_for_updates(self, *, silent: bool = False) -> None:
        if self._update_check_running or self._update_install_running:
            return
        self._update_check_running = True
        self.check_update_button.configure(state=tk.DISABLED)
        self.install_update_button.configure(state=tk.DISABLED)
        self.update_status.set("Checking for updates...")
        self.update_status_label.configure(style="Status.TLabel")

        def worker() -> None:
            try:
                update = check_for_update(__version__)
            except Exception as exc:
                error = str(exc)
                self.after(0, lambda message=error: self._show_update_error(message, silent))
            else:
                self.after(0, lambda: self._show_update_result(update))

        threading.Thread(target=worker, daemon=True).start()

    def _show_update_result(self, update: UpdateInfo) -> None:
        self._update_check_running = False
        self.check_update_button.configure(state=tk.NORMAL)
        if update.available:
            self._available_update = update
            self.update_status.set(f"Version {update.latest_version} is available")
            self.update_status_label.configure(style="Update.TLabel")
            self.install_update_button.configure(state=tk.NORMAL)
        else:
            self._available_update = None
            self.update_status.set(f"Up to date ({__version__})")
            self.update_status_label.configure(style="Success.TLabel")
            self.install_update_button.configure(state=tk.DISABLED)

    def _show_update_error(self, error: str, silent: bool) -> None:
        self._update_check_running = False
        self.check_update_button.configure(state=tk.NORMAL)
        self.install_update_button.configure(
            state=tk.NORMAL if self._available_update else tk.DISABLED
        )
        self.update_status.set("Unable to check for updates")
        self.update_status_label.configure(style="Error.TLabel")
        if not silent:
            messagebox.showerror("Software update", error, parent=self)

    def _show_installer_status(self, status: InstallerStatus | None) -> None:
        if status is None:
            return
        version = status.version or "unknown"
        if status.state == "success" and version == __version__:
            self.update_status.set(f"Updated successfully to version {version}")
            self.update_status_label.configure(style="Success.TLabel")
            return
        if status.state == "failed":
            detail = f": {status.message}" if status.message else ""
            self.update_status.set(f"Update to version {version} failed{detail}")
        elif status.state == "installing":
            self.update_status.set(
                f"Update to version {version} did not complete. Run the installer again."
            )
        else:
            self.update_status.set(
                f"Setup reported version {version}, but Manager is version {__version__}"
            )
        self.update_status_label.configure(style="Error.TLabel")

    def install_available_update(self) -> None:
        update = self._available_update
        if update is None or self._update_install_running:
            return
        if self._diagnostics_running or self._operation_running:
            messagebox.showwarning(
                "Software update",
                "Wait for the current operation to finish before updating.",
                parent=self,
            )
            return
        confirmed = messagebox.askyesno(
            "Software update",
            f"Install version {update.latest_version} now?\n\n"
            "The Manager will close and the Windows Service will restart automatically.",
            parent=self,
        )
        if not confirmed:
            return

        self._update_install_running = True
        self._set_interaction_locked(
            True,
            f"UPDATE IN PROGRESS · Downloading version {update.latest_version}",
        )
        self.update_status.set(f"Downloading version {update.latest_version}...")
        self.update_status_label.configure(style="Status.TLabel")

        def progress(received: int, total: int | None) -> None:
            if total:
                percent = min(100, int(received * 100 / total))
                message = f"Downloading version {update.latest_version}... {percent}%"
            else:
                message = f"Downloading version {update.latest_version}... {received // 1024} KB"
            self.after(0, lambda text=message: self._show_update_progress(text))

        def worker() -> None:
            try:
                installer = download_installer(
                    update,
                    program_data_directory() / "updates",
                    progress=progress,
                )
            except Exception as exc:
                error = str(exc)
                self.after(0, lambda message=error: self._update_download_failed(message))
            else:
                self.after(
                    0,
                    lambda: self._launch_downloaded_update(installer, update.latest_version),
                )

        threading.Thread(target=worker, daemon=True).start()

    def _show_update_progress(self, message: str) -> None:
        self.update_status.set(message)
        self.busy_status.set(f"UPDATE IN PROGRESS · {message}")

    def _update_download_failed(self, error: str) -> None:
        self._update_install_running = False
        self._set_interaction_locked(False)
        self.check_update_button.configure(state=tk.NORMAL)
        self.install_update_button.configure(state=tk.NORMAL)
        self.update_status.set("Update download failed")
        self.update_status_label.configure(style="Error.TLabel")
        messagebox.showerror("Software update", error, parent=self)

    def _launch_downloaded_update(self, installer: Path, target_version: str) -> None:
        try:
            if self._direct_process is not None and self._direct_process.poll() is None:
                self.stop_direct()
            self.update_status.set("Starting update progress window...")
            self.busy_status.set("UPDATE IN PROGRESS · Starting installer")
            self.update_idletasks()
            updater = self._package_root / "radar-scanner-updater.exe"
            if updater.is_file():
                launch_updater(updater, installer, target_version)
            else:
                launch_installer(installer)
        except Exception as exc:
            self._update_download_failed(str(exc))
            return
        self.update_status.set("Updater started. Manager will close during installation...")
        self.busy_status.set("UPDATE IN PROGRESS · Waiting for installer")

    def _run_operation(self, operation, *, title: str, success_message: str) -> None:
        if self._operation_running:
            return
        self._operation_running = True

        def worker() -> None:
            try:
                operation()
            except Exception as exc:
                error = str(exc)
                self.after(
                    0,
                    lambda message=error: messagebox.showerror(title, message, parent=self),
                )
            else:
                self.after(
                    0,
                    lambda: messagebox.showinfo(title, success_message, parent=self),
                )
            finally:
                self.after(0, self._operation_finished)

        threading.Thread(target=worker, daemon=True).start()

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
            messagebox.showerror("Service installation error", str(exc), parent=self)
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
        state = query_service()
        if state.status == "running":
            messagebox.showwarning(
                "Direct run blocked",
                "Stop the Windows Service before starting a direct Agent process.",
                parent=self,
            )
            return
        if not self.save_configuration(show_message=False):
            return
        executable = worker_executable(self._package_root)
        if not executable.exists():
            messagebox.showerror("Direct run error", f"Worker not found: {executable}", parent=self)
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
            messagebox.showerror("Direct run error", str(exc), parent=self)
            return
        threading.Thread(target=self._read_process_output, daemon=True).start()
        self._build_logs_tab()
        self.tabs.select(self.logs_tab)
        self._set_log_text("")
        self.refresh_status()

    def _read_process_output(self) -> None:
        process = self._direct_process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            self._process_output.put(line)
        process.wait()
        self._process_output.put(f"\nDirect process exited with code {process.returncode}.\n")

    def _drain_process_output(self) -> None:
        while True:
            try:
                output = self._process_output.get_nowait()
            except queue.Empty:
                break
            self._append_log_text(output)
        if self.winfo_exists():
            self.after(500, self._drain_process_output)

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
            messagebox.showerror("Diagnostics", str(exc), parent=self)
            return
        self._diagnostics_running = True
        self._diagnostic_results.clear()
        self._diagnostic_items.clear()
        self.diagnostic_button.configure(state=tk.DISABLED)
        self.install_update_button.configure(state=tk.DISABLED)
        self.diagnostic_summary.set(f"Running 0/{len(_DIAGNOSTIC_STEPS)} checks")
        self.diagnostic_summary_label.configure(style="Busy.TLabel")
        for item in self.diagnostic_table.get_children():
            self.diagnostic_table.delete(item)
        for key, label in _DIAGNOSTIC_STEPS:
            self._diagnostic_items[key] = self.diagnostic_table.insert(
                "",
                tk.END,
                values=(label, "WAITING", "Waiting to run", "—"),
                tags=("waiting",),
            )

        def worker() -> None:
            try:
                results = asyncio.run(
                    run_diagnostics(
                        settings,
                        on_started=lambda key, label: self.after(
                            0,
                            lambda: self._diagnostic_started(key, label),
                        ),
                        on_result=lambda result: self.after(
                            0,
                            lambda: self._diagnostic_completed(result),
                        ),
                    )
                )
            except Exception as exc:
                error = str(exc)
                self.after(0, lambda message=error: self._diagnostics_failed(message))
            else:
                self.after(0, lambda: self._diagnostics_finished(results))

        threading.Thread(target=worker, daemon=True).start()

    def _diagnostic_started(self, key: str, label: str) -> None:
        item = self._diagnostic_items.get(key)
        if item:
            self.diagnostic_table.item(
                item,
                values=(label, "RUNNING", "Checking connection...", "—"),
                tags=("running",),
            )
            self.diagnostic_table.see(item)

    def _diagnostic_completed(self, result: DiagnosticResult) -> None:
        self._diagnostic_results[result.key] = result
        item = self._diagnostic_items.get(result.key)
        if item:
            self.diagnostic_table.item(
                item,
                values=(
                    result.label,
                    "PASSED" if result.success else "FAILED",
                    result.detail,
                    f"{result.duration_ms} ms",
                ),
                tags=("passed" if result.success else "failed",),
            )
            self.diagnostic_table.see(item)
        passed = sum(result.success for result in self._diagnostic_results.values())
        completed = len(self._diagnostic_results)
        self.diagnostic_summary.set(
            f"Running {completed}/{len(_DIAGNOSTIC_STEPS)} · {passed} passed"
        )

    def _diagnostics_finished(self, results: list[DiagnosticResult]) -> None:
        self._diagnostics_running = False
        passed = sum(result.success for result in results)
        self.diagnostic_summary.set(f"{passed}/{len(results)} checks passed")
        self.diagnostic_summary_label.configure(
            style="Success.TLabel" if passed == len(results) else "Error.TLabel"
        )
        if not self._interaction_locked:
            self.diagnostic_button.configure(state=tk.NORMAL)
            self.install_update_button.configure(
                state=tk.NORMAL if self._available_update else tk.DISABLED
            )

    def _diagnostics_failed(self, error: str) -> None:
        self._diagnostics_running = False
        self.diagnostic_summary.set("Diagnostics failed")
        self.diagnostic_summary_label.configure(style="Error.TLabel")
        if not self._interaction_locked:
            self.diagnostic_button.configure(state=tk.NORMAL)
            self.install_update_button.configure(
                state=tk.NORMAL if self._available_update else tk.DISABLED
            )
        messagebox.showerror("Diagnostics", error, parent=self)

    def _set_log_text(self, content: str) -> None:
        self.log_output.configure(state=tk.NORMAL)
        self.log_output.delete("1.0", tk.END)
        self.log_output.insert(tk.END, content)
        self.log_output.yview_moveto(1.0)
        self.log_output.xview_moveto(0.0)
        self.log_output.configure(state=tk.DISABLED)

    def _append_log_text(self, content: str) -> None:
        self.log_output.configure(state=tk.NORMAL)
        self.log_output.insert(tk.END, content)
        self.log_output.yview_moveto(1.0)
        self.log_output.xview_moveto(0.0)
        self.log_output.configure(state=tk.DISABLED)

    def refresh_logs(self) -> None:
        if not self._logs_built:
            return
        if self._direct_process is not None and self._direct_process.poll() is None:
            return
        try:
            self._set_log_text(read_service_log())
        except OSError as exc:
            self._set_log_text(f"Unable to read logs: {exc}")

    def open_log_folder(self) -> None:
        folder = service_log_path().parent
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)

    def _start_tray(self) -> None:
        try:
            self._tray = TrayController(
                dispatch=lambda callback: self.after(0, callback),
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
        self.deiconify()
        self.state("normal")
        self.lift()
        self.focus_force()

    def _run_diagnostics_from_tray(self) -> None:
        if self._interaction_locked:
            return
        self._show_manager()
        self.tabs.select(self.diagnostics_tab)
        self.run_checks()

    def _open_logs_from_tray(self) -> None:
        if self._interaction_locked:
            return
        self._show_manager()
        self._build_logs_tab()
        self.tabs.select(self.logs_tab)
        self.refresh_logs()

    def _exit_application(self) -> None:
        if self._interaction_locked:
            messagebox.showinfo(
                "Update in progress",
                "Scanner Manager cannot exit while an update is in progress.",
                parent=self,
            )
            return
        direct_running = self._direct_process is not None and self._direct_process.poll() is None
        if direct_running:
            should_close = messagebox.askyesno(
                "Stop direct process?",
                "Exiting the Manager will stop the direct Agent process. Continue?",
                parent=self,
            )
            if not should_close:
                return
            self.stop_direct()
        if self._tray is not None:
            self._tray.stop()
        self.destroy()

    def _close_window(self) -> None:
        if self._interaction_locked:
            messagebox.showinfo(
                "Update in progress",
                "Wait for the update process to open before closing Scanner Manager.",
                parent=self,
            )
            return
        if self._tray is None:
            self._exit_application()
            return
        self.withdraw()
        if not self._tray_notice_shown:
            self._tray_notice_shown = True
            self._tray.notify_minimized()


def main() -> None:
    instance = SingleInstance()
    if not instance.acquire():
        focus_existing_manager()
        return
    try:
        application = ManagerWindow()
        application.mainloop()
    finally:
        instance.close()


if __name__ == "__main__":
    main()
