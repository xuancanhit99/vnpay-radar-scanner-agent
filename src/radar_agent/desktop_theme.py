from io import BytesIO

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QProxyStyle, QStyle, QStyleOption, QWidget

from radar_agent.desktop_shell import create_radar_icon

BACKGROUND = "#F5F7FA"
SURFACE = "#FFFFFF"
INPUT = "#FFFFFF"
BORDER = "#DCE3EA"
TEXT = "#172B3A"
MUTED = "#667788"
BLUE = "#0056A7"
BLUE_BRIGHT = "#006CC2"
BLUE_TINT = "#E8F2FA"
RED = "#D92D3A"
RED_TINT = "#FFF0F1"
AMBER = "#B76E00"
AMBER_TINT = "#FFF7E6"
GREEN = "#087A55"
GREEN_TINT = "#EAF7F2"


class RadarProxyStyle(QProxyStyle):
    def pixelMetric(
        self,
        metric: QStyle.PixelMetric,
        option: QStyleOption | None = None,
        widget: QWidget | None = None,
    ) -> int:
        if metric in {
            QStyle.PixelMetric.PM_IndicatorWidth,
            QStyle.PixelMetric.PM_IndicatorHeight,
        }:
            return 18
        return super().pixelMetric(metric, option, widget)

    def drawPrimitive(
        self,
        element: QStyle.PrimitiveElement,
        option: QStyleOption,
        painter: QPainter,
        widget: QWidget | None = None,
    ) -> None:
        if element != QStyle.PrimitiveElement.PE_IndicatorCheckBox:
            super().drawPrimitive(element, option, painter, widget)
            return

        state = option.state
        enabled = bool(state & QStyle.StateFlag.State_Enabled)
        checked = bool(state & QStyle.StateFlag.State_On)
        partial = bool(state & QStyle.StateFlag.State_NoChange)
        hovered = bool(state & QStyle.StateFlag.State_MouseOver)
        focused = bool(state & QStyle.StateFlag.State_HasFocus)

        if checked or partial:
            fill = QColor(BLUE_BRIGHT if hovered and enabled else BLUE)
            if not enabled:
                fill = QColor("#9CB7CC")
            border = fill
        else:
            fill = QColor(BLUE_TINT if hovered and enabled else SURFACE)
            border = QColor(BLUE_BRIGHT if focused or hovered else "#AEBBC6")
            if not enabled:
                fill = QColor("#F3F5F7")
                border = QColor(BORDER)

        rect = option.rect.adjusted(1, 1, -1, -1)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(border, 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, 4, 4)

        if checked:
            path = QPainterPath()
            path.moveTo(rect.left() + 3.5, rect.center().y())
            path.lineTo(rect.center().x() - 0.5, rect.bottom() - 3.5)
            path.lineTo(rect.right() - 3, rect.top() + 3.5)
            check_pen = QPen(QColor("#FFFFFF"), 2)
            check_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            check_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(check_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        elif partial:
            partial_pen = QPen(QColor("#FFFFFF"), 2)
            partial_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(partial_pen)
            painter.drawLine(
                rect.left() + 4,
                rect.center().y(),
                rect.right() - 4,
                rect.center().y(),
            )
        painter.restore()


RADAR_STYLESHEET = f"""
QWidget {{
    color: {TEXT};
    background: {BACKGROUND};
    font-family: "Segoe UI Variable Text", "Segoe UI";
    font-size: 13px;
}}
QMainWindow, QDialog {{ background: {BACKGROUND}; }}
QLabel, QCheckBox {{ background: transparent; }}
QToolTip {{
    color: {TEXT};
    background: {SURFACE};
    border: 1px solid {BORDER};
    padding: 5px;
}}
QFrame#Sidebar {{
    background: {SURFACE};
    border-right: 1px solid {BORDER};
}}
QFrame#Panel {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QFrame#InfoBanner {{
    background: {BLUE_TINT};
    border: 1px solid #B9D7ED;
    border-radius: 6px;
}}
QFrame#SuccessBanner {{
    background: {GREEN_TINT};
    border: 1px solid #A9DCC8;
    border-radius: 6px;
}}
QFrame#ErrorBanner {{
    background: {RED_TINT};
    border: 1px solid #F0BEC3;
    border-radius: 6px;
}}
QLabel#BrandTitle {{ font-size: 16px; font-weight: 600; color: {TEXT}; }}
QLabel#BrandSubtitle {{ font-size: 11px; color: {MUTED}; }}
QLabel#PageTitle {{ font-size: 24px; font-weight: 600; color: {TEXT}; }}
QLabel#PageSubtitle {{ font-size: 13px; color: {MUTED}; }}
QLabel#SectionTitle {{ font-size: 15px; font-weight: 600; color: {TEXT}; }}
QLabel#SectionSubtitle, QLabel#MutedLabel {{ color: {MUTED}; }}
QLabel#FieldLabel {{ color: {MUTED}; font-weight: 600; }}
QLabel#VersionLabel {{
    color: {BLUE};
    background: {BLUE_TINT};
    border-radius: 6px;
    padding: 5px 9px;
    font-weight: 600;
}}
QLabel#StatusDotSuccess {{ color: {GREEN}; font-size: 17px; }}
QLabel#StatusDotError {{ color: {RED}; font-size: 17px; }}
QLabel#StatusDotWarning {{ color: {AMBER}; font-size: 17px; }}
QLabel#StatusDotNeutral {{ color: #94A3B8; font-size: 17px; }}
QLabel#StatusSuccess {{ color: {GREEN}; font-weight: 600; }}
QLabel#StatusError {{ color: {RED}; font-weight: 600; }}
QLabel#StatusWarning {{ color: {AMBER}; font-weight: 600; }}
QLabel#StatusBusy {{ color: {BLUE_BRIGHT}; font-weight: 600; }}
QPushButton {{
    min-height: 34px;
    padding: 0 14px;
    color: {TEXT};
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 6px;
    font-weight: 600;
}}
QPushButton:hover {{ background: #F1F5F8; border-color: #C7D3DD; }}
QPushButton:pressed {{ background: #E8EEF3; }}
QPushButton:disabled {{ color: #9AA8B5; background: #F3F5F7; border-color: #E3E8ED; }}
QPushButton#PrimaryButton {{ color: white; background: {BLUE}; border-color: {BLUE}; }}
QPushButton#PrimaryButton:hover {{ background: {BLUE_BRIGHT}; border-color: {BLUE_BRIGHT}; }}
QPushButton#PrimaryButton:pressed {{ background: #004987; border-color: #004987; }}
QPushButton#PrimaryButton:disabled {{ color: #EDF3F7; background: #9CB7CC; border-color: #9CB7CC; }}
QPushButton#DangerButton {{ color: #B4232A; background: {RED_TINT}; border-color: #EAB5BA; }}
QPushButton#DangerButton:hover {{ background: #FFE3E6; }}
QPushButton#NavButton {{
    min-height: 42px;
    padding: 0 14px;
    text-align: left;
    color: {MUTED};
    background: transparent;
    border: 0;
    border-radius: 6px;
    font-weight: 500;
}}
QPushButton#NavButton:hover {{ color: {TEXT}; background: #F1F5F8; }}
QPushButton#NavButton:checked {{ color: {BLUE}; background: {BLUE_TINT}; font-weight: 600; }}
QLineEdit, QSpinBox {{
    min-height: 35px;
    padding: 0 10px;
    color: {TEXT};
    background: {INPUT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    selection-background-color: {BLUE};
}}
QLineEdit:focus, QSpinBox:focus {{ border: 2px solid {BLUE_BRIGHT}; padding: 0 9px; }}
QLineEdit:disabled, QSpinBox:disabled {{ color: #9AA8B5; background: #F3F5F7; }}
QFrame#NumericStepper {{
    min-height: 35px;
    max-height: 35px;
    background: {INPUT};
    border: 1px solid {BORDER};
    border-radius: 6px;
}}
QSpinBox#StepperInput {{
    min-height: 33px;
    padding: 0 10px;
    background: transparent;
    border: 0;
    border-radius: 0;
}}
QSpinBox#StepperInput:focus {{ border: 0; padding: 0 10px; }}
QToolButton#StepperButton {{
    min-width: 34px;
    max-width: 34px;
    min-height: 33px;
    max-height: 33px;
    color: {MUTED};
    background: transparent;
    border: 0;
    border-left: 1px solid {BORDER};
    font-size: 16px;
    font-weight: 600;
}}
QToolButton#StepperButton:hover {{ color: {BLUE}; background: {BLUE_TINT}; }}
QToolButton#StepperButton:pressed {{ background: #DCECF7; }}
QCheckBox {{ spacing: 9px; }}
QProgressBar {{
    min-height: 7px;
    max-height: 7px;
    background: #E5EBF0;
    border: 0;
    border-radius: 3px;
    text-align: center;
}}
QProgressBar::chunk {{ background: {BLUE_BRIGHT}; border-radius: 3px; }}
QTableWidget {{
    color: {TEXT};
    background: {SURFACE};
    alternate-background-color: #FAFBFC;
    border: 1px solid {BORDER};
    border-radius: 6px;
    gridline-color: #E8EDF1;
    selection-background-color: {BLUE_TINT};
    selection-color: {TEXT};
}}
QHeaderView::section {{
    color: {MUTED};
    background: #F6F8FA;
    border: 0;
    border-bottom: 1px solid {BORDER};
    padding: 9px;
    font-weight: 600;
}}
QPlainTextEdit {{
    color: {TEXT};
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 8px;
    selection-background-color: {BLUE};
}}
QScrollArea {{ border: 0; background: transparent; }}
QScrollBar:vertical {{ width: 12px; background: transparent; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #C8D2DB; min-height: 28px; border-radius: 4px; }}
QScrollBar::handle:vertical:hover {{ background: #AEBBC6; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ height: 12px; background: transparent; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #C8D2DB; min-width: 28px; border-radius: 4px; }}
QScrollBar::handle:horizontal:hover {{ background: #AEBBC6; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar::corner {{ background: transparent; }}
QMenu {{ background: {SURFACE}; border: 1px solid {BORDER}; padding: 5px; }}
QMenu::item {{ padding: 7px 24px 7px 10px; border-radius: 4px; }}
QMenu::item:selected {{ color: {BLUE}; background: {BLUE_TINT}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 5px 8px; }}
"""


def radar_icon(size: int = 64) -> QIcon:
    buffer = BytesIO()
    create_radar_icon(size).save(buffer, format="PNG")
    pixmap = QPixmap()
    pixmap.loadFromData(buffer.getvalue(), "PNG")
    return QIcon(pixmap)


def apply_window_icon(window: QWidget) -> None:
    window.setWindowIcon(radar_icon())


def configure_radar_theme(application: QApplication) -> None:
    application.setStyle(RadarProxyStyle("Fusion"))
    application.setFont(QFont("Segoe UI Variable Text", 10))
    application.setStyleSheet(RADAR_STYLESHEET)
    application.setWindowIcon(radar_icon())
