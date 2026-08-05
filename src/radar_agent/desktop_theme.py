import tkinter as tk
from tkinter import ttk

from PIL import ImageTk

from radar_agent.desktop_shell import create_radar_icon

BACKGROUND = "#F3F6F9"
SURFACE = "#FFFFFF"
INPUT = "#F8FAFC"
BORDER = "#D7E0E8"
TEXT = "#172B3A"
MUTED = "#64748B"
BLUE = "#0056A7"
BLUE_BRIGHT = "#006CC2"
RED = "#E81D24"
AMBER = "#F59E0B"
GREEN = "#087A55"


def apply_window_icon(window: tk.Tk) -> None:
    icon = ImageTk.PhotoImage(create_radar_icon(64))
    window.iconphoto(True, icon)
    window._radar_window_icon = icon  # type: ignore[attr-defined]


def configure_radar_theme(window: tk.Tk) -> ttk.Style:
    """Apply the light RADAR color system to native ttk controls."""
    window.configure(background=BACKGROUND)
    style = ttk.Style(window)
    if "clam" in style.theme_names():
        style.theme_use("clam")

    style.configure(".", background=BACKGROUND, foreground=TEXT, font=("Segoe UI", 9))
    style.configure("TFrame", background=BACKGROUND)
    style.configure("Root.TFrame", background=BACKGROUND)
    style.configure("Card.TFrame", background=SURFACE)
    style.configure("TLabel", background=BACKGROUND, foreground=TEXT)
    style.configure("Card.TLabel", background=SURFACE, foreground=TEXT)
    style.configure(
        "Title.TLabel",
        background=BACKGROUND,
        foreground=TEXT,
        font=("Segoe UI Semibold", 20),
    )
    style.configure(
        "Subtitle.TLabel",
        background=BACKGROUND,
        foreground=MUTED,
        font=("Segoe UI", 10),
    )
    style.configure(
        "CardSubtitle.TLabel",
        background=SURFACE,
        foreground=MUTED,
        font=("Segoe UI", 9),
    )
    style.configure(
        "Field.TLabel",
        background=SURFACE,
        foreground=MUTED,
        font=("Segoe UI Semibold", 9),
    )
    style.configure("Status.TLabel", background=SURFACE, foreground=TEXT)
    for name, color in (
        ("Success", GREEN),
        ("Error", RED),
        ("Update", AMBER),
        ("Busy", BLUE_BRIGHT),
    ):
        style.configure(
            f"{name}.TLabel",
            background=SURFACE,
            foreground=color,
            font=("Segoe UI Semibold", 9),
        )

    style.configure(
        "Section.TLabelframe",
        background=SURFACE,
        foreground=TEXT,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        padding=16,
        relief=tk.FLAT,
    )
    style.configure(
        "Section.TLabelframe.Label",
        background=SURFACE,
        foreground=TEXT,
        font=("Segoe UI Semibold", 10),
    )

    style.configure("TNotebook", background=BACKGROUND, borderwidth=0, tabmargins=(0, 0, 0, 12))
    style.configure(
        "TNotebook.Tab",
        background=SURFACE,
        foreground=MUTED,
        borderwidth=0,
        padding=(20, 11),
        font=("Segoe UI Semibold", 9),
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", "#E7F1FA"), ("active", "#EEF4F8"), ("disabled", BACKGROUND)],
        foreground=[("selected", BLUE), ("active", TEXT), ("disabled", "#94A3B8")],
    )

    style.configure(
        "TButton",
        background=INPUT,
        foreground=TEXT,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        padding=(14, 8),
        font=("Segoe UI Semibold", 9),
    )
    style.map(
        "TButton",
        background=[("active", "#E7EEF4"), ("pressed", "#DCE7F0"), ("disabled", "#EEF2F6")],
        foreground=[("disabled", "#94A3B8")],
    )
    style.configure("Primary.TButton", background=BLUE, foreground="#FFFFFF", bordercolor=BLUE)
    style.map(
        "Primary.TButton",
        background=[("active", BLUE_BRIGHT), ("pressed", "#004987"), ("disabled", "#B7C8D8")],
        foreground=[("disabled", "#F8FAFC")],
    )
    style.configure(
        "Danger.TButton",
        background="#FFF1F2",
        foreground="#B4232A",
        bordercolor="#F2B8BC",
    )
    style.map(
        "Danger.TButton",
        background=[("active", "#FFE4E6"), ("pressed", "#FECDD3"), ("disabled", "#F8E8EA")],
        foreground=[("disabled", "#B98A8E")],
    )

    style.configure(
        "TEntry",
        fieldbackground=INPUT,
        foreground=TEXT,
        insertcolor=TEXT,
        bordercolor=BORDER,
        padding=7,
    )
    style.configure(
        "TSpinbox",
        fieldbackground=INPUT,
        foreground=TEXT,
        arrowcolor=MUTED,
        bordercolor=BORDER,
        padding=7,
    )
    style.configure("TCheckbutton", background=BACKGROUND, foreground=TEXT)
    style.map(
        "TCheckbutton",
        background=[("active", BACKGROUND)],
        foreground=[("disabled", "#94A3B8")],
    )
    style.configure("Card.TCheckbutton", background=SURFACE, foreground=TEXT)
    style.map(
        "Card.TCheckbutton",
        background=[("active", SURFACE)],
        foreground=[("disabled", "#94A3B8")],
    )

    style.configure(
        "Treeview",
        background=SURFACE,
        fieldbackground=SURFACE,
        foreground=TEXT,
        bordercolor=BORDER,
        rowheight=32,
        font=("Segoe UI", 9),
    )
    style.map("Treeview", background=[("selected", BLUE)], foreground=[("selected", "#FFFFFF")])
    style.configure(
        "Treeview.Heading",
        background=INPUT,
        foreground=MUTED,
        bordercolor=BORDER,
        padding=(8, 8),
        font=("Segoe UI Semibold", 9),
    )
    style.map("Treeview.Heading", background=[("active", "#E7EEF4")])
    for orientation in ("Vertical", "Horizontal"):
        style.configure(
            f"{orientation}.TScrollbar",
            background=INPUT,
            troughcolor=BACKGROUND,
            bordercolor=BACKGROUND,
            arrowcolor=MUTED,
        )
    return style
