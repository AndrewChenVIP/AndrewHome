"""主题——token 字典 + 单一 QSS 生成器。

教训对策（Mie 双主题 QSS 重复 400 行、页面各自 setStyleSDrift）：
- 颜色只有 token 一份，深浅两套字典；QSS 从 token 生成，禁止页面硬编码色值。
"""
from __future__ import annotations

TOKENS: dict[str, dict[str, str]] = {
    "light": {
        "window_bg": "#f5f6f8",
        "content_bg": "#ffffff",
        "group_bg": "#eef0f4",
        "sidebar_bg": "#2b2f3a",
        "sidebar_text": "#d7dbe3",
        "sidebar_sel": "#7f56d9",
        "text": "#1f2329",
        "text_muted": "#6b7280",
        "accent": "#7f56d9",
        "accent_hover": "#9e77ed",
        "danger": "#d92d20",
        "ok": "#12805c",
        "input_bg": "#ffffff",
        "input_border": "#c9ced8",
        "log_bg": "#fbfbfc",
    },
    "dark": {
        "window_bg": "#1e2128",
        "content_bg": "#262a33",
        "group_bg": "#2e333e",
        "sidebar_bg": "#171a20",
        "sidebar_text": "#c3c8d4",
        "sidebar_sel": "#9e77ed",
        "text": "#e8eaf0",
        "text_muted": "#9aa1af",
        "accent": "#9e77ed",
        "accent_hover": "#b79af0",
        "danger": "#f04438",
        "ok": "#3ccb9a",
        "input_bg": "#1f232b",
        "input_border": "#3a4150",
        "log_bg": "#16181d",
    },
}

_THEME_KEY = "light"


def set_theme(name: str) -> None:
    global _THEME_KEY
    if name in TOKENS:
        _THEME_KEY = name


def current_theme() -> str:
    return _THEME_KEY


def c(token: str) -> str:
    """取当前主题的单个色 token。"""
    return TOKENS[_THEME_KEY].get(token, "#888888")


def build_qss() -> str:
    """整份应用 QSS 从 token 生成——唯一来源。"""
    return f"""
    QMainWindow {{ background: {c('window_bg')}; }}
    QWidget#content {{ background: {c('content_bg')}; border-radius: 8px; }}
    QListWidget#sidebar {{
        background: {c('sidebar_bg')}; color: {c('sidebar_text')};
        font-size: 14px; border: none; outline: none; padding: 8px 0;
    }}
    QListWidget#sidebar::item {{ padding: 12px 18px; }}
    QListWidget#sidebar::item:selected {{ background: {c('sidebar_sel')}; color: white; }}
    QLabel {{ color: {c('text')}; font-size: 13px; }}
    QLabel#title {{ font-size: 18px; font-weight: bold; }}
    QLabel#muted {{ color: {c('text_muted')}; font-size: 12px; }}
    QGroupBox {{
        background: {c('group_bg')}; border: none; border-radius: 8px;
        margin-top: 14px; padding: 10px 12px 12px 12px;
        font-weight: bold; color: {c('text')};
    }}
    QLineEdit, QComboBox, QSpinBox {{
        background: {c('input_bg')}; color: {c('text')};
        border: 1px solid {c('input_border')}; border-radius: 6px;
        padding: 5px 8px; font-size: 13px;
    }}
    QPushButton {{
        background: {c('group_bg')}; color: {c('text')};
        border: none; border-radius: 6px; padding: 8px 16px; font-size: 13px;
    }}
    QPushButton:hover {{ background: {c('accent_hover')}; color: white; }}
    QPushButton#primary {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
            stop:0 {c('accent')}, stop:1 {c('accent_hover')});
        color: white; font-size: 16px; font-weight: bold; padding: 14px;
    }}
    QPushButton#primary:hover {{ background: {c('accent_hover')}; }}
    QPushButton#stop {{
        background: {c('danger')}; color: white; font-size: 16px;
        font-weight: bold; padding: 14px;
    }}
    QPlainTextEdit#logview {{
        background: {c('log_bg')}; color: {c('text')};
        font-family: Consolas, "Courier New", monospace; font-size: 12px;
        border: 1px solid {c('input_border')}; border-radius: 6px; padding: 6px;
    }}
    QStatusBar {{ background: {c('group_bg')}; color: {c('text_muted')}; }}
    QCheckBox {{ color: {c('text')}; font-size: 13px; }}
    """
