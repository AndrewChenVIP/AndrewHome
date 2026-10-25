"""打包脚本——PyInstaller onedir（不做 onefile：Mie 的 113MB onefile 启动解压慢是前车之鉴）。

用法: python scripts/build.py
产物: dist/WandaoLaunchpad/WandaoLaunchpad.exe + dist/万道启动台.cmd（双击启动 GUI）
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CMD_WRAPPER = r"""@echo off
REM 万道启动台 - 双击启动 GUI（控制台最小化；CLI 请直接用 WandaoLaunchpad\WandaoLaunchpad.exe）
start "WandaoLaunchpad" /min "%~dp0WandaoLaunchpad\WandaoLaunchpad.exe" gui
"""


def main() -> int:
    dist = ROOT / "dist"
    build = ROOT / "build"
    for d in (dist, build):
        if d.exists():
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--name", "WandaoLaunchpad",
        "--onedir",
        "--paths", str(ROOT),
        # 体积控制：裁掉用不到的大件（Qt WebEngine/翻译/例子）
        "--exclude-module", "PyQt5.QtWebEngineCore",
        "--exclude-module", "PyQt5.QtWebEngineWidgets",
        "--exclude-module", "PyQt5.QtQml",
        "--exclude-module", "PyQt5.QtQuick",
        "--exclude-module", "PyQt5.QtSql",
        "--exclude-module", "PyQt5.QtPdf",
        "--exclude-module", "PyQt5.QtTest",
        "--exclude-module", "tkinter",
        "--exclude-module", "PyQt5.QtDesigner",
        "--exclude-module", "PyQt5.QtBluetooth",
        "--exclude-module", "PyQt5.QtNfc",
        "--exclude-module", "PyQt5.QtLocation",
        str(ROOT / "run.py"),
    ]
    print(">> ", " ".join(cmd), flush=True)
    rc = subprocess.call(cmd, cwd=str(ROOT))
    if rc != 0:
        return rc

    # 双击入口 + 运行时配置目录占位（跟 exe 同级 = dist/WandaoLaunchpad/launchpad）
    (dist / "万道启动台.cmd").write_text(CMD_WRAPPER, encoding="gbk", errors="replace")
    app_dir = dist / "WandaoLaunchpad"
    (app_dir / "launchpad").mkdir(exist_ok=True)
    _trim(app_dir)
    print("打包完成:", dist)
    return 0


def _trim(app_dir: Path) -> None:
    """体积裁剪（对标分析：Mie 的 113MB 里有同款冗余）。

    - opengl32sw.dll（20MB Mesa 软渲染）：砍——桌面 GL 可用性交给系统驱动
    - Qt5 Quick/Qml 系 DLL 与 .pyd：本应用纯 Widgets
    - translations/*.qm：单语应用用不到
    """
    import shutil

    internal = app_dir / "_internal"
    targets = [
        internal / "PyQt5" / "Qt5" / "bin" / "opengl32sw.dll",
        internal / "PyQt5" / "Qt5" / "translations",
        internal / "PyQt5" / "Qt5" / "qml",
    ]
    for pattern in ("Qt5Quick.dll", "Qt5Qml.dll", "Qt5QmlModels.dll", "Qt5QuickWidgets.dll",
                    "Qt5QuickParticles.dll", "Qt5QuickShapes.dll", "Qt5QuickTest.dll",
                    "Qt5XmlPatterns.dll", "Qt5Designer.dll", "Qt5Help.dll", "Qt5Test.dll",
                    "Qt5Bluetooth.dll", "Qt5Nfc.dll", "Qt5Location.dll", "Qt5Sensors.dll",
                    "Qt5SerialPort.dll", "Qt5WebSockets.dll", "Qt5Pdf.dll"):
        targets.append(internal / "PyQt5" / "Qt5" / "bin" / pattern)
    for pyd in ("QtQuick.pyd", "QtQml.pyd", "QtQuickWidgets.pyd", "QtDesigner.pyd",
                "QtHelp.pyd", "QtTest.pyd", "QtBluetooth.pyd", "QtNfc.pyd",
                "QtLocation.pyd", "QtSensors.pyd", "QtSerialPort.pyd",
                "QtWebSockets.pyd", "QtPdf.pyd", "QtXmlPatterns.pyd", "QtSql.pyd",
                "QtChart.pyd", "QtDataVisualization.pyd", "QtOpenGL.pyd",
                "QtOpenGLWidgets.pyd", "QtMultimedia.pyd", "QtMultimediaWidgets.pyd",
                "QtPositioning.pyd", "QtRemoteObjects.pyd", "QtTextToSpeech.pyd"):
        targets.append(internal / "PyQt5" / (pyd))
    removed = 0
    for t in targets:
        if t.exists():
            if t.is_dir():
                shutil.rmtree(t, ignore_errors=True)
            else:
                t.unlink(missing_ok=True)
            removed += 1
    print(f"裁剪 {removed} 项冗余")


if __name__ == "__main__":
    raise SystemExit(main())
