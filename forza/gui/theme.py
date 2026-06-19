from __future__ import annotations

APP_BG = "#F3F6FA"
SURFACE = "#FFFFFF"
SURFACE_ALT = "#F8FAFD"
SIDEBAR = "#FFFFFF"
BORDER = "#D0D7DE"
TEXT = "#1F2328"
MUTED = "#57606A"
ACCENT = "#0F6CBD"
ACCENT_HOVER = "#115EA3"
ACCENT_SOFT = "#EAF4FF"
SUCCESS = "#107C10"
SUCCESS_SOFT = "#DFF6DD"
WARNING = "#9A6700"
WARNING_SOFT = "#FFF4CE"
DANGER = "#C50F1F"
DANGER_SOFT = "#FDE7E9"
PURPLE = "#5C2D91"

SIDEBAR_WIDTH = 238
TOPBAR_HEIGHT = 74
STATUSBAR_HEIGHT = 28
CARD_RADIUS = 12
BUTTON_RADIUS = 6
ROW_HEIGHT = 38


def build_qss() -> str:
    return f"""
    * {{
        font-family: 'Segoe UI', 'Inter', Arial, sans-serif;
        color: {TEXT};
        font-size: 13px;
    }}

    QMainWindow, QWidget#centralRoot {{
        background: {APP_BG};
    }}

    QWidget#sidebar {{
        background: {SIDEBAR};
        border-right: 1px solid {BORDER};
    }}

    QLabel#appTitle {{
        font-size: 16px;
        font-weight: 700;
    }}

    QLabel#appSubtitle, QLabel#mutedLabel {{
        color: {MUTED};
    }}

    QWidget#commandBar {{
        background: {SURFACE};
        border-bottom: 1px solid {BORDER};
    }}

    QPushButton {{
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: {BUTTON_RADIUS}px;
        padding: 7px 10px;
    }}

    QPushButton:hover {{
        background: {SURFACE_ALT};
    }}

    QPushButton#primaryButton {{
        background: {ACCENT};
        border-color: {ACCENT};
        color: white;
        font-weight: 600;
    }}

    QPushButton#primaryButton:hover {{
        background: {ACCENT_HOVER};
    }}

    QPushButton#navButton {{
        border: 0;
        border-radius: 8px;
        padding: 9px 12px;
        text-align: left;
        background: transparent;
        color: {TEXT};
    }}

    QPushButton#navButton:hover {{
        background: {SURFACE_ALT};
    }}

    QPushButton#navButton[active="true"] {{
        background: {ACCENT_SOFT};
        color: {ACCENT};
        font-weight: 700;
    }}

    QFrame#card {{
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: {CARD_RADIUS}px;
    }}

    QLabel#sectionTitle {{
        font-size: 24px;
        font-weight: 700;
    }}

    QLabel#cardTitle {{
        font-size: 18px;
        font-weight: 700;
    }}

    QLabel#statusBadge {{
        border-radius: 999px;
        padding: 4px 9px;
        font-weight: 600;
        background: {SURFACE_ALT};
        border: 1px solid {BORDER};
    }}

    QLabel#statusBadge[kind="success"] {{
        color: {SUCCESS};
        background: {SUCCESS_SOFT};
        border-color: {SUCCESS_SOFT};
    }}

    QLabel#statusBadge[kind="warning"] {{
        color: {WARNING};
        background: {WARNING_SOFT};
        border-color: {WARNING_SOFT};
    }}

    QLabel#statusBadge[kind="danger"] {{
        color: {DANGER};
        background: {DANGER_SOFT};
        border-color: {DANGER_SOFT};
    }}

    QStatusBar {{
        background: {SURFACE};
        border-top: 1px solid {BORDER};
        min-height: {STATUSBAR_HEIGHT}px;
    }}
    """
