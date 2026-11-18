"""配色与样式：浅色简约，米黄 + 浅绿 + 深绿。"""
from __future__ import annotations

MILK = "#FBF7EA"          # 米黄：卡片底色
MILK_DEEP = "#F2EBD6"     # 米黄加深：分区底色
GREEN_PALE = "#E4EEDC"    # 浅绿：原文块
GREEN_LIGHT = "#A9C9A2"   # 浅绿描边
GREEN_MID = "#6E9A78"
GREEN_DEEP = "#2F5D50"    # 深绿：主色、标题
GREEN_DARK = "#1D3E35"    # 深绿加深：正文大字
TEXT = "#24382F"
TEXT_MUTED = "#71857A"
BORDER = "#D5E1C7"
WHITE = "#FFFFFF"

FONT_FAMILY = "Microsoft YaHei UI, Microsoft YaHei, Segoe UI"

SETTINGS_QSS = f"""
QDialog {{
    background: {MILK};
}}
QLabel {{
    color: {TEXT};
    font-family: {FONT_FAMILY};
    font-size: 13px;
}}
QLabel#Hint {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}
QLabel#Section {{
    color: {GREEN_DEEP};
    font-size: 13px;
    font-weight: 600;
}}
QLineEdit, QSpinBox, QKeySequenceEdit, QComboBox {{
    background: {WHITE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 5px 9px;
    color: {TEXT};
    font-family: {FONT_FAMILY};
    font-size: 13px;
    min-height: 22px;
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QKeySequenceEdit:focus {{
    border: 1px solid {GREEN_MID};
}}
QCheckBox {{
    color: {TEXT};
    font-family: {FONT_FAMILY};
    font-size: 13px;
    spacing: 7px;
}}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {BORDER};
    border-radius: 4px;
    background: {WHITE};
}}
QCheckBox::indicator:checked {{
    background: {GREEN_DEEP};
    border: 1px solid {GREEN_DEEP};
}}
QPushButton {{
    background: {WHITE};
    border: 1px solid {BORDER};
    border-radius: 9px;
    padding: 7px 16px;
    color: {TEXT};
    font-family: {FONT_FAMILY};
    font-size: 13px;
}}
QPushButton:hover {{
    background: {GREEN_PALE};
}}
QPushButton#Primary {{
    background: {GREEN_DEEP};
    border: 1px solid {GREEN_DEEP};
    color: {MILK};
    font-weight: 600;
}}
QPushButton#Primary:hover {{
    background: {GREEN_DARK};
}}
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 10px;
    margin-top: 14px;
    padding-top: 10px;
    background: {MILK_DEEP};
    font-family: {FONT_FAMILY};
    font-size: 12px;
    font-weight: 600;
    color: {GREEN_DEEP};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 5px;
}}
"""

MENU_QSS = f"""
QMenu {{
    background: {MILK};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 6px;
    font-family: {FONT_FAMILY};
    font-size: 13px;
    color: {TEXT};
}}
QMenu::item {{
    padding: 7px 22px 7px 14px;
    border-radius: 6px;
}}
QMenu::item:selected {{
    background: {GREEN_PALE};
    color: {GREEN_DEEP};
}}
QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 5px 8px;
}}
"""
