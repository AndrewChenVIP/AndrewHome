"""主题——token 字典 + 单一 QSS 生成器。

v0.6 全面视觉重做（老板实测反馈"UI太丑"后）：
- 字体：Microsoft YaHei UI 全局统一，三级字号层次
- 卡片化：内容区白卡 + 1px 描边 + 12px 圆角，页面浅灰底拉开层次
- 控件统一样式：下拉/输入/复选/按钮全部定制圆角与 hover/焦点态
- 品牌色：现代紫 #6D5AE0 一以贯之；危险红降饱和不再满屏刺眼
"""
from __future__ import annotations

TOKENS: dict[str, dict[str, str]] = {
    "light": {
        "window_bg": "#f4f5f7",
        "content_bg": "#ffffff",
        "card_bg": "#ffffff",
        "card_border": "#e6e8ee",
        "sidebar_bg": "#20232e",
        "sidebar_header": "#191c26",
        "sidebar_text": "#aab0bd",
        "sidebar_text_active": "#ffffff",
        "sidebar_sel": "#6d5ae0",
        "sidebar_hover": "#2a2e3c",
        "text": "#23262e",
        "text_muted": "#828894",
        "accent": "#6d5ae0",
        "accent_hover": "#7e6ce8",
        "accent_pressed": "#5b4ad0",
        "accent_soft": "#eef0fc",
        "danger": "#dc4c5c",
        "danger_hover": "#e55c6a",
        "ok": "#12805c",
        "input_bg": "#ffffff",
        "input_border": "#d4d8e0",
        "input_focus": "#6d5ae0",
        "log_bg": "#fafafc",
        "statusbar_bg": "#ffffff",
        "table_alt": "#f8f9fb",
        "table_sel": "#eef0fc",
        "table_header_bg": "#f4f5f7",
    },
    "dark": {
        "window_bg": "#14161c",
        "content_bg": "#1a1d25",
        "card_bg": "#1e222b",
        "card_border": "#2a2f3a",
        "sidebar_bg": "#111319",
        "sidebar_header": "#0d0f14",
        "sidebar_text": "#9aa1af",
        "sidebar_text_active": "#ffffff",
        "sidebar_sel": "#7e6ce8",
        "sidebar_hover": "#232733",
        "text": "#e7e9ef",
        "text_muted": "#8b91a0",
        "accent": "#8b7cf0",
        "accent_hover": "#9c8ff4",
        "accent_pressed": "#7a6ae8",
        "accent_soft": "#2b2a3e",
        "danger": "#f0565b",
        "danger_hover": "#f6686d",
        "ok": "#3ccb9a",
        "input_bg": "#16181f",
        "input_border": "#333947",
        "input_focus": "#8b7cf0",
        "log_bg": "#111319",
        "statusbar_bg": "#1a1d25",
        "table_alt": "#20242e",
        "table_sel": "#2b2a3e",
        "table_header_bg": "#20242e",
    },
}

_THEME_KEY = "light"
_FONT_STACK = '"Microsoft YaHei UI", "Segoe UI", "PingFang SC", sans-serif'


def set_theme(name: str) -> None:
    global _THEME_KEY
    if name in TOKENS:
        _THEME_KEY = name


def current_theme() -> str:
    return _THEME_KEY


def c(token: str) -> str:
    return TOKENS[_THEME_KEY].get(token, "#888888")


def build_qss() -> str:
    return f"""
    * {{ font-family: {_FONT_STACK}; }}

    QMainWindow {{ background: {c('window_bg')}; }}
    QWidget#content {{ background: {c('window_bg')}; }}

    /* ---------- 侧边栏 ---------- */
    QWidget#sidebarwrap {{ background: {c('sidebar_bg')}; }}
    QWidget#sidebarwrap > QLabel {{ background: transparent; }}
    QListWidget#sidebar {{
        background: transparent; color: {c('sidebar_text')};
        font-size: 14px; border: none; outline: none; padding: 6px 10px;
    }}
    QListWidget#sidebar::item {{
        padding: 11px 14px; margin: 2px 4px; border-radius: 8px;
    }}
    QListWidget#sidebar::item:hover {{ background: {c('sidebar_hover')}; }}
    QListWidget#sidebar::item:selected {{
        background: {c('sidebar_sel')}; color: {c('sidebar_text_active')};
        font-weight: bold;
    }}
    QLabel#sidebar_title {{
        color: #ffffff; font-size: 17px; font-weight: bold;
        padding: 2px 6px;
    }}
    QLabel#sidebar_version {{ color: {c('sidebar_text')}; font-size: 11px; padding: 0 6px 8px 6px; }}

    /* ---------- 排版 ---------- */
    QLabel {{ color: {c('text')}; font-size: 13px; background: transparent; }}
    QLabel#title {{ font-size: 20px; font-weight: bold; letter-spacing: 1px; }}
    QLabel#cardtitle {{
        color: {c('text')}; font-size: 14px; font-weight: bold;
        padding: 4px 2px 2px 2px;
    }}
    QLabel#muted {{ color: {c('text_muted')}; font-size: 12px; }}

    /* ---------- 卡片 ---------- */
    QGroupBox {{
        background: {c('card_bg')}; border: 1px solid {c('card_border')};
        border-radius: 12px; margin-top: 6px; padding: 32px 16px 14px 16px;
        font-size: 14px; font-weight: bold; color: {c('text')};
    }}
    QGroupBox::title {{
        subcontrol-origin: padding; subcontrol-position: top left;
        left: 16px; top: 10px; padding: 0;
        background: transparent; color: {c('text')};
    }}

    /* ---------- 输入 ---------- */
    QLineEdit, QSpinBox, QComboBox {{
        background: {c('input_bg')}; color: {c('text')};
        border: 1px solid {c('input_border')}; border-radius: 8px;
        padding: 6px 10px; font-size: 13px; min-height: 20px;
    }}
    QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {c('input_focus')}; }}
    QLineEdit:hover, QSpinBox:hover, QComboBox:hover {{ border-color: {c('accent_hover')}; }}
    QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{ color: {c('text_muted')}; }}
    QComboBox::drop-down {{ border: none; width: 26px; }}
    QComboBox::down-arrow {{
        border-left: 4px solid transparent; border-right: 4px solid transparent;
        border-top: 5px solid {c('text_muted')}; width: 0; height: 0;
    }}
    QComboBox QAbstractItemView {{
        background: {c('card_bg')}; color: {c('text')};
        border: 1px solid {c('card_border')}; border-radius: 8px;
        selection-background-color: {c('accent_soft')};
        selection-color: {c('text')}; outline: none; padding: 4px;
    }}
    QSpinBox::up-button, QSpinBox::down-button {{
        background: transparent; border: none; width: 18px;
    }}
    QSpinBox::up-arrow {{ border-left: 4px solid transparent; border-right: 4px solid transparent;
        border-bottom: 5px solid {c('text_muted')}; width: 0; height: 0; }}
    QSpinBox::down-arrow {{ border-left: 4px solid transparent; border-right: 4px solid transparent;
        border-top: 5px solid {c('text_muted')}; width: 0; height: 0; }}

    /* ---------- 按钮 ---------- */
    QPushButton {{
        background: {c('card_bg')}; color: {c('text')};
        border: 1px solid {c('card_border')}; border-radius: 8px;
        padding: 7px 14px; font-size: 13px;
    }}
    QPushButton:hover {{ border-color: {c('accent')}; color: {c('accent')}; }}
    QPushButton:pressed {{ background: {c('accent_soft')}; }}
    QPushButton:disabled {{ color: {c('text_muted')}; border-color: {c('card_border')}; }}
    QPushButton#primary {{
        background: {c('accent')};
        color: #ffffff; font-size: 15px; font-weight: bold;
        padding: 13px; border: none; border-radius: 10px;
    }}
    QPushButton#primary:hover {{ background: {c('accent_hover')}; }}
    QPushButton#primary:pressed {{ background: {c('accent_pressed')}; }}
    QPushButton#stop {{
        background: {c('danger')}; color: #ffffff; font-size: 15px;
        font-weight: bold; padding: 13px; border: none; border-radius: 10px;
    }}
    QPushButton#stop:hover {{ background: {c('danger_hover')}; }}

    /* ---------- 复选框 ---------- */
    QCheckBox {{ color: {c('text')}; font-size: 13px; spacing: 8px; background: transparent; }}
    QCheckBox::indicator {{
        width: 18px; height: 18px; border: 1.5px solid {c('input_border')};
        border-radius: 5px; background: {c('input_bg')};
    }}
    QCheckBox::indicator:hover {{ border-color: {c('accent')}; }}
    QCheckBox::indicator:checked {{ background: {c('accent')}; border-color: {c('accent')}; }}

    /* ---------- 表格 ---------- */
    QTableWidget, QTableView {{
        background: {c('card_bg')}; alternate-background-color: {c('table_alt')};
        border: 1px solid {c('card_border')}; border-radius: 10px;
        gridline-color: transparent; font-size: 12.5px;
        selection-background-color: {c('table_sel')}; selection-color: {c('text')};
        outline: none;
    }}
    QTableWidget::item, QTableView::item {{ padding: 6px 8px; border: none; }}
    QHeaderView::section {{
        background: {c('table_header_bg')}; color: {c('text_muted')};
        border: none; border-bottom: 1px solid {c('card_border')};
        padding: 8px 8px; font-size: 12px; font-weight: bold;
    }}
    QTableCornerButton::section {{ background: {c('table_header_bg')}; border: none; }}

    QListWidget {{ background: {c('card_bg')}; border: 1px solid {c('card_border')};
        border-radius: 10px; outline: none; font-size: 13px; }}
    QListWidget::item {{ padding: 9px 10px; border-radius: 6px; }}
    QListWidget::item:selected {{ background: {c('accent_soft')}; color: {c('text')} }}
    QListWidget::item:hover {{ background: {c('table_alt')}; }}

    /* ---------- 日志 / 状态栏 / 菜单 ---------- */
    QScrollArea {{
        background: transparent; border: none;
    }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QPlainTextEdit#logview {{
        background: {c('log_bg')}; color: {c('text')};
        font-family: "Cascadia Mono", Consolas, "Courier New", monospace;
        font-size: 12px; border: 1px solid {c('card_border')};
        border-radius: 10px; padding: 8px;
    }}
    QStatusBar {{
        background: {c('statusbar_bg')}; color: {c('text_muted')};
        border-top: 1px solid {c('card_border')}; font-size: 12px;
    }}
    QMenu {{
        background: {c('card_bg')}; color: {c('text')};
        border: 1px solid {c('card_border')}; border-radius: 10px; padding: 6px;
    }}
    QMenu::item {{ padding: 8px 24px; border-radius: 6px; }}
    QMenu::item:selected {{ background: {c('accent_soft')}; }}
    QMenu::separator {{ height: 1px; background: {c('card_border')}; margin: 4px 8px; }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{
        background: {c('input_border')}; border-radius: 5px; min-height: 32px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {c('accent')}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{
        background: {c('input_border')}; border-radius: 5px; min-width: 32px;
    }}
    """
