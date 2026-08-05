import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QCheckBox, QHeaderView

from radar_agent.desktop_theme import (
    branding_asset_path,
    configure_radar_theme,
    radar_icon,
    vnpay_logo_pixmap,
)
from radar_agent.manager import ManagerWindow
from radar_agent.update_service import UpdateInfo


def _application() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    application = QApplication.instance() or QApplication([])
    configure_radar_theme(application)
    return application


def test_manager_builds_modern_navigation_pages(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("RADAR_AGENT_MANAGER_CONFIG", str(tmp_path / ".env"))
    application = _application()
    window = ManagerWindow(start_background_tasks=False)

    try:
        assert window.page_stack.count() == 4
        assert [button.text() for button in window.nav_buttons] == [
            "Overview",
            "Configuration",
            "Diagnostics",
            "Logs",
        ]
        assert window.install_button.text() == "Install / Reinstall"
        assert window.windowTitle().startswith("VNPAY RADAR Scanner Manager")
        assert not window.vnpay_brand_logo.pixmap().isNull()
        application.processEvents()
    finally:
        window._exiting = True
        window.close()


def test_update_lock_disables_navigation_and_shows_progress(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("RADAR_AGENT_MANAGER_CONFIG", str(tmp_path / ".env"))
    application = _application()
    window = ManagerWindow(start_background_tasks=False)

    try:
        window._set_interaction_locked(True, "Downloading Scanner Agent")
        application.processEvents()

        assert window.busy_banner.isVisible() is False  # Parent window is not shown in unit tests.
        assert window.busy_banner.isHidden() is False
        assert window.busy_status.text() == "Downloading Scanner Agent"
        assert window.sidebar.isEnabled() is False
        assert window.page_stack.isEnabled() is False

        window._set_interaction_locked(False)
        assert window.sidebar.isEnabled() is True
        assert window.page_stack.isEnabled() is True
    finally:
        window._exiting = True
        window.close()


def test_update_button_only_appears_when_update_is_available(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("RADAR_AGENT_MANAGER_CONFIG", str(tmp_path / ".env"))
    application = _application()
    window = ManagerWindow(start_background_tasks=False)

    current = UpdateInfo("0.7.4", "0.7.4", False, "", "", "", "")
    available = UpdateInfo(
        "0.7.4",
        "0.7.5",
        True,
        "https://github.com/example/release",
        "setup.exe",
        "https://github.com/example/setup.exe",
        "a" * 64,
    )

    try:
        assert window.install_update_button.isHidden()
        window._show_update_result(available)
        assert not window.install_update_button.isHidden()
        assert window.install_update_button.isEnabled()
        window._show_update_result(current)
        assert window.install_update_button.isHidden()
        application.processEvents()
    finally:
        window._exiting = True
        window.close()


def test_official_brand_assets_render() -> None:
    _application()

    assert branding_asset_path("icon.svg").is_file()
    assert branding_asset_path("logo.svg").is_file()
    assert not radar_icon(64).pixmap(64, 64).isNull()
    assert not vnpay_logo_pixmap(121).isNull()


def test_diagnostics_button_uses_animated_running_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("RADAR_AGENT_MANAGER_CONFIG", str(tmp_path / ".env"))
    application = _application()
    window = ManagerWindow(start_background_tasks=False)

    try:
        window._set_diagnostics_running_visual(True)
        first_frame = window.diagnostic_button.icon().cacheKey()
        window._advance_diagnostic_spinner()

        assert window.diagnostic_button.text() == "Running checks"
        assert window._diagnostic_spinner_timer.isActive()
        assert window.diagnostic_button.icon().cacheKey() != first_frame

        window._set_diagnostics_running_visual(False)
        assert window.diagnostic_button.text() == "Run checks"
        assert not window._diagnostic_spinner_timer.isActive()
        application.processEvents()
    finally:
        window._exiting = True
        window.close()


def test_diagnostics_table_uses_balanced_columns(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("RADAR_AGENT_MANAGER_CONFIG", str(tmp_path / ".env"))
    application = _application()
    window = ManagerWindow(start_background_tasks=False)

    try:
        table = window.diagnostic_table
        header = table.horizontalHeader()

        assert table.columnWidth(0) == 180
        assert table.columnWidth(1) == 116
        assert table.columnWidth(3) == 116
        assert header.sectionResizeMode(2) == QHeaderView.ResizeMode.Stretch

        table.setRowCount(1)
        window._set_diagnostic_row(
            0, "Android device", "FAILED", "ReadTimeout", "20000 ms", "#dc2626"
        )
        latency_alignment = table.item(0, 3).textAlignment()
        assert latency_alignment & int(Qt.AlignmentFlag.AlignRight)
        application.processEvents()
    finally:
        window._exiting = True
        window.close()


def test_checked_checkbox_uses_high_contrast_indicator() -> None:
    application = _application()
    checkbox = QCheckBox()
    checkbox.setChecked(True)
    checkbox.resize(24, 24)
    checkbox.show()
    application.processEvents()

    image = checkbox.grab().toImage()
    blue_pixels = 0
    white_pixels = 0
    for x in range(min(20, image.width())):
        for y in range(image.height()):
            color = image.pixelColor(x, y)
            if color.blue() > 120 and color.green() > 50 and color.red() < 40:
                blue_pixels += 1
            if color.red() > 250 and color.green() > 250 and color.blue() > 250:
                white_pixels += 1

    assert blue_pixels > 80
    assert white_pixels > 3
    assert "QScrollBar:horizontal" in application.styleSheet()
    checkbox.close()


def test_numeric_stepper_and_log_autoscroll(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("RADAR_AGENT_MANAGER_CONFIG", str(tmp_path / ".env"))
    application = _application()
    window = ManagerWindow(start_background_tasks=False)

    try:
        window.heartbeat_interval.setValue(10)
        window.heartbeat_interval.increment_button.click()
        assert window.heartbeat_interval.value() == 11
        window.heartbeat_interval.decrement_button.click()
        assert window.heartbeat_interval.value() == 10

        content = "\n".join(f"line {index}: {'x' * 300}" for index in range(100))
        window.show()
        window._set_log_text(content)
        application.processEvents()

        assert window.log_output.verticalScrollBar().value() == (
            window.log_output.verticalScrollBar().maximum()
        )
        assert window.log_output.horizontalScrollBar().value() == (
            window.log_output.horizontalScrollBar().minimum()
        )
    finally:
        window._exiting = True
        window.close()
