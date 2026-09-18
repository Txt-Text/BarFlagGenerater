# -*- mode: python ; coding: utf-8 -*-
"""命令行版打包配置（带控制台）。

用 packaging/build.py 调用。

和图形版的区别：
* console=True —— 必须有控制台，否则文本模式的输出全进黑洞。
* 排除掉 tkinter / sv_ttk / tkinterdnd2 / barflag.gui ——
  命令行版不需要图形组件，排掉能省一大截体积。
  代价是它的 --gui 用不了，会给出"请运行 BarFlagGenerater.exe"的提示。
"""

import os

ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))

# 命令行版只需要 Pillow（生成 PNG/JPG）。
# Pillow 有 PyInstaller 内置 hook，会自己带上 PNG/JPEG 插件，
# 这里只要保证模块被显式引用即可。
datas, binaries, hiddenimports = [], [], []

hiddenimports += [
    "barflag", "barflag.core", "barflag.render", "barflag.presets",
    "barflag.deps", "barflag.report", "barflag.cli",
    "PIL", "PIL.Image", "PIL.ImageDraw",
]

_icon = os.path.join(SPECPATH, "icon.ico")

a = Analysis(
    [os.path.join(ROOT, "BarFlagGenerater.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "_tkinter", "sv_ttk", "tkinterdnd2", "barflag.gui",
              "numpy", "matplotlib", "pytest", "setuptools", "pip", "PyInstaller"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BarFlagGenerater-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,                        # 命令行版：保留控制台
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
    name="BarFlagGenerater-cli",
)
