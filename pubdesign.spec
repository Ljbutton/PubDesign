# PyInstaller build recipe for PubDesign (run: pyinstaller --noconfirm pubdesign.spec)
import sys

datas = [
    ("template.pub", "."),
    ("shape_templates.json", "."),
    ("version.json", "."),
    ("assets", "assets"),
]
# bundled Microsoft Publisher reader (built by tools/pubconv/build_windows.sh)
import os
if os.path.isdir(os.path.join("tools", "pubconv", "build")):
    datas.append((os.path.join("tools", "pubconv", "build"), "pubconv"))

a = Analysis(
    ["app.py"],
    pathex=["."],
    datas=datas,
    hiddenimports=["PySide6.QtPdf", "PySide6.QtSvg", "PySide6.QtPrintSupport", "fontTools.varLib.instancer",
                   "fontTools.ttLib.tables"],
    excludes=["tkinter", "PIL", "numpy", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
              "PySide6.Qt3DCore", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="PubDesign",
    icon="assets/PubDesign.ico",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="PubDesign")
