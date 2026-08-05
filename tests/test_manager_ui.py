import os

from PySide6.QtWidgets import QApplication

from radar_agent.desktop_theme import configure_radar_theme
from radar_agent.manager import ManagerWindow


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
