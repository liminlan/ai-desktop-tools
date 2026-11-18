# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：onedir 模式，模型外置，输出干净能跑的绿色版。

打包命令（项目根目录执行）：
    .venv\\Scripts\\pyinstaller.exe --noconfirm --clean offline_translator\\build.spec
"""
from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs

datas = []
binaries = []
hiddenimports = []

# wordninja 的词频表是数据文件（约 3.4 MB），OCR 文本修复离不开它
import os

try:
    import wordninja as _wordninja

    _wn_data = os.path.join(
        os.path.dirname(_wordninja.__file__), "wordninja", "wordninja_words.txt.gz"
    )
    if os.path.exists(_wn_data):
        datas.append((_wn_data, "wordninja"))
except Exception:
    pass

# RapidOCR 的 onnx 模型和 config.yaml 是数据文件，必须显式收进去
for pkg in ("rapidocr_onnxruntime",):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# CTranslate2 / onnxruntime 的动态库
for pkg in ("ctranslate2", "onnxruntime", "sentencepiece"):
    try:
        binaries += collect_dynamic_libs(pkg)
    except Exception:
        pass

hiddenimports += [
    "ctranslate2",
    "sentencepiece",
    "onnxruntime",
    "onnxruntime.capi._pybind_state",
    "shapely",
    "pyclipper",
    # Windows 系统 OCR（winrt 自带 __pyinstaller hook，这里补齐用到的命名空间）
    "winrt",
    "winrt.runtime",
    "winrt.system",
    "winrt.windows",
    "winrt.windows.media.ocr",
    "winrt.windows.graphics.imaging",
    "winrt.windows.storage.streams",
    "winrt.windows.globalization",
    "winrt.windows.foundation",
    "winrt.windows.foundation.collections",
]

# 砍掉用不上的大件，exe 体积能小一半以上
excludes = [
    "tkinter", "unittest", "pydoc_data", "test",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.Qt3DCore",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtSerialPort",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp",
    "matplotlib", "scipy", "pandas", "torch", "transformers",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OfflineTranslator",
    icon="app_icon.ico",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="OfflineTranslator",
)
