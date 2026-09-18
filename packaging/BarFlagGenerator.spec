# -*- mode: python ; coding: utf-8 -*-
"""图形版打包配置（窗口模式，双击即用）。

用 packaging/build.py 调用，不要直接 pyinstaller 这个文件——
build.py 会先生成图标、清目录、把两份产物一起打出来。

关键点：
* sv_ttk 带 .tcl 主题文件、tkinterdnd2 带 tkdnd 二进制，
  都不是 .py，必须 collect_all 收进来。漏了 sv_ttk 的话程序照样能跑，
  但主题会静默失效退化成原生外观——最难发现的那种问题。
* upx=False：UPX 压缩后杀软误报率明显上升，省那几 MB 不值。
"""

import os

from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))

datas, binaries, hiddenimports = [], [], []
for _pkg in ("sv_ttk", "tkinterdnd2"):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

# 显式列一遍，防止分析器漏掉动态导入的模块
# （Pillow 有内置 hook，会自己带上 PNG/JPEG 插件）
hiddenimports += [
    "barflag", "barflag.core", "barflag.render", "barflag.presets",
    "barflag.deps", "barflag.report", "barflag.cli", "barflag.gui",
    "PIL", "PIL.Image", "PIL.ImageDraw",
]

_icon = os.path.join(SPECPATH, "icon.ico")

a = Analysis(
    [os.path.join(ROOT, "BarFlagGenerator.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["numpy", "matplotlib", "pytest", "setuptools", "pip", "PyInstaller"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BarFlagGenerator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                       # 窗口模式：不弹黑框
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon if os.path.exists(_icon) else None,
    version=os.path.join(SPECPATH, "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="BarFlagGenerator",
)
