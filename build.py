#!/usr/bin/env python3
# build.py
"""一键打包 Windows release。

    python build.py                # 打包 → 自检 → 打 zip（默认全流程）
    python build.py --no-verify    # 跳过自检
    python build.py --no-zip       # 只打包，不打 zip
    python build.py --clean        # 只清理 release/ 与 build/
    python build.py --keep         # 保留已有产物（增量重打）

产物全部放在 release/<版本号>/ 下：

    BarFlagGenerater/        图形版（窗口模式，双击即用）
    BarFlagGenerater-cli/    命令行版（保留控制台，方便写脚本调用）
    BarFlagGenerater-<版本号>-win64.zip
    BarFlagGenerater-cli-<版本号>-win64.zip

打包配置在 packaging/ 里（两份 spec、图标、版本信息），一般不用动。
版本号来自 barflag/__init__.py 的 __version__。

会自动做完这几件事，不需要手工干预：
* 缺 PyInstaller 就 pip 装
* 没图标就用三色旗现画一个（packaging/icon.ico）
* 打完包**立刻自检**：跑一遍命令行产物，确认主题数据、tkdnd 二进制、
  预设落盘位置都对——这几项漏了都不会报错，只会在用户那儿静默失效
* Zip 的缓存目录全部限定在项目内（build/），不污染用户主目录
"""

from __future__ import annotations

import argparse
import locale
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
PACKAGING = os.path.join(ROOT, "packaging")
BUILD_DIR = os.path.join(ROOT, "build")
WORK = os.path.join(BUILD_DIR, "pyinstaller")
CACHE = os.path.join(BUILD_DIR, "pyinstaller-cache")
SCRATCH = os.path.join(BUILD_DIR, "verify")

sys.path.insert(0, ROOT)
from barflag import __version__  # noqa: E402

VERSION = __version__
RELEASE = os.path.join(ROOT, "release", VERSION)

SPECS = [
    ("图形版", "BarFlagGenerater.spec", "BarFlagGenerater"),
    ("命令行版", "BarFlagGenerater-cli.spec", "BarFlagGenerater-cli"),
]


def say(msg):
    print(f"[build] {msg}")


def human(n):
    return f"{n / 1024 / 1024:.1f} MB"


def dir_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


# ============================ 准备 ============================


def ensure_pyinstaller():
    try:
        import PyInstaller  # noqa: F401
        return True
    except ImportError:
        pass
    say("缺少 PyInstaller，正在安装…")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install",
                               "--disable-pip-version-check", "pyinstaller"])
    except Exception as e:
        say(f"安装 PyInstaller 失败: {e}")
        return False
    return True


def ensure_icon():
    """生成一个三色旗图标（已存在就不动，方便你换成自己的）。"""
    path = os.path.join(PACKAGING, "icon.ico")
    if os.path.exists(path):
        return path
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        say("没有 Pillow，跳过图标生成（exe 将使用默认图标）")
        return None

    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bands = ["#1B3A6B", "#F2F2F2", "#C8102E"]
    top, bottom = 24, size - 24
    h = (bottom - top) / len(bands)
    for i, color in enumerate(bands):
        y0 = top + i * h
        d.rectangle([24, y0, size - 24, y0 + h + 1], fill=color)
    d.rounded_rectangle([24, top, size - 24, bottom], radius=18,
                        outline="#2B2B2B", width=3)
    img.save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                          (64, 64), (128, 128), (256, 256)])
    say(f"已生成图标: {path}")
    return path


def clean(release_only=False):
    targets = [RELEASE] if release_only else [RELEASE, BUILD_DIR]
    # release/ 下如果还有别的版本，不动；只删当前版本目录
    for d in targets:
        if os.path.isdir(d):
            say(f"清理 {os.path.relpath(d, ROOT)}")
            shutil.rmtree(d, ignore_errors=True)


# ============================ 打包 ============================


def run_spec(label, spec_name):
    spec = os.path.join(PACKAGING, spec_name)
    if not os.path.exists(spec):
        say(f"找不到 spec: {spec}")
        return False

    say(f"开始打包 {label} …")
    env = dict(os.environ)
    # 把 PyInstaller 的缓存也关在项目里，别写进用户主目录
    env.setdefault("PYINSTALLER_CONFIG_DIR", CACHE)
    cmd = [sys.executable, "-m", "PyInstaller",
           "--noconfirm", "--log-level", "WARN",
           "--distpath", RELEASE, "--workpath", WORK, spec]
    code = subprocess.call(cmd, cwd=ROOT, env=env)
    if code != 0:
        say(f"{label} 打包失败（退出码 {code}）")
        return False
    say(f"{label} 打包完成")
    return True


# ============================ 自检 ============================


def run_exe(exe, args, timeout=90):
    """跑一下产物。返回 (退出码, 输出文字)。

    输出重定向到文件而不是管道——有些受限环境不允许开管道，
    这样写更稳（顺便也留了一份日志）。
    """
    os.makedirs(SCRATCH, exist_ok=True)
    log = os.path.join(SCRATCH, "run.log")
    with open(log, "wb") as fh:
        proc = subprocess.run([exe, *args], cwd=os.path.dirname(exe),
                              stdout=fh, stderr=subprocess.STDOUT, timeout=timeout)
    try:
        with open(log, "rb") as fh:
            raw = fh.read()
    except OSError:
        raw = b""
    encoding = locale.getpreferredencoding(False) or "utf-8"
    return proc.returncode, raw.decode(encoding, "replace")


def verify():
    """打完包立刻自检。

    这几项漏了都不会报错，只会在用户那儿静默失效，所以必须自动跑一遍：
      1. 两个 exe 都在
      2. sv-ttk 的 .tcl 主题文件进了包（漏了会退化成原生外观）
      3. tkdnd 的二进制进了包（漏了拖拽直接不可用）
      4. 命令行产物真的能生成 SVG / PNG
      5. 预设落在 exe 同级目录，而不是 _MEIxxxx 临时目录
    """
    say("开始自检 …")
    problems = []
    cleanup = []

    def ok(cond, label):
        print(f"    {'OK  ' if cond else 'FAIL'}  {label}")
        if not cond:
            problems.append(label)

    gui_dir = os.path.join(RELEASE, "BarFlagGenerater")
    cli_dir = os.path.join(RELEASE, "BarFlagGenerater-cli")
    gui_exe = os.path.join(gui_dir, "BarFlagGenerater.exe")
    cli_exe = os.path.join(cli_dir, "BarFlagGenerater-cli.exe")

    ok(os.path.exists(gui_exe), "图形版 exe 存在")
    ok(os.path.exists(cli_exe), "命令行版 exe 存在")

    ok(os.path.exists(os.path.join(gui_dir, "_internal", "sv_ttk",
                                   "theme", "dark.tcl")),
       "sv-ttk 主题文件已打进包")
    ok(os.path.isdir(os.path.join(gui_dir, "_internal", "tkinterdnd2",
                                  "tkdnd", "win-x64-tcl9")),
       "tkdnd 二进制已打进包")
    ok(not os.path.exists(os.path.join(cli_dir, "_internal", "_tkinter.pyd")),
       "命令行版没有混入 tkinter")

    if not os.path.exists(cli_exe):
        return problems, cleanup

    os.makedirs(SCRATCH, exist_ok=True)
    out_svg = os.path.join(SCRATCH, "check.svg")
    out_png = os.path.join(SCRATCH, "check.png")
    for f in (out_svg, out_png):
        if os.path.exists(f):
            os.remove(f)

    try:
        code, _ = run_exe(cli_exe, ["--list-presets"])
        ok(code == 0, "命令行版 --list-presets 正常退出")
    except Exception as e:
        ok(False, f"命令行版 --list-presets 跑不起来: {e}")

    try:
        code, _ = run_exe(cli_exe, ["-r", "300x200", "-s", "#FF0000 1,FFFFFF 1",
                                    "-f", "svg", "-o", out_svg, "-y"])
        ok(code == 0 and os.path.getsize(out_svg) > 100, "能生成 SVG")
    except Exception as e:
        ok(False, f"生成 SVG 失败: {e}")

    try:
        code, _ = run_exe(cli_exe, ["-r", "120x80", "-s", "red 1,white 3",
                                    "-f", "png", "-o", out_png, "-y"])
        ok(code == 0 and os.path.getsize(out_png) > 100, "能生成 PNG（Pillow 已打进包）")
    except Exception as e:
        ok(False, f"生成 PNG 失败: {e}")

    # 预设必须落在 exe 同级目录
    try:
        code, _ = run_exe(cli_exe, ["-r", "64x48", "-s", "#112233 1",
                                    "-f", "png", "-o",
                                    os.path.join(SCRATCH, "check2.png"),
                                    "--save-preset", "_build_check", "-y"])
        preset = os.path.join(cli_dir, "presets", "_build_check.flagpreset")
        ok(code == 0 and os.path.exists(preset),
           "预设落在 exe 同级目录（不是临时目录）")
        cleanup.append(os.path.join(cli_dir, "presets"))
    except Exception as e:
        ok(False, f"保存预设失败: {e}")

    return problems, cleanup


# ============================ 打包 zip ============================


def make_zip(folder, zip_path):
    """把整个目录塞进 zip（解压后得到一个文件夹，不会散落一地）。"""
    say(f"压缩 {os.path.basename(zip_path)} …")
    base = os.path.dirname(folder)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for root, _dirs, files in os.walk(folder):
            for f in files:
                full = os.path.join(root, f)
                z.write(full, os.path.relpath(full, base))
    return os.path.getsize(zip_path)


# ============================ 主流程 ============================


def main():
    ap = argparse.ArgumentParser(description="打包 BarFlagGenerater release")
    ap.add_argument("--no-verify", action="store_true", help="跳过打包后的自检")
    ap.add_argument("--no-zip", action="store_true", help="只打包，不打 zip")
    ap.add_argument("--clean", action="store_true", help="只清理，不打包")
    ap.add_argument("--keep", action="store_true", help="保留已有产物（增量重打）")
    args = ap.parse_args()

    if args.clean:
        clean()
        return 0

    if not args.keep:
        clean()

    if not ensure_pyinstaller():
        return 1
    ensure_icon()

    say(f"版本 {VERSION}  →  {os.path.relpath(RELEASE, ROOT)}")
    for label, spec, _name in SPECS:
        if not run_spec(label, spec):
            return 1

    problems, cleanup = ([], [])
    if not args.no_verify:
        problems, cleanup = verify()

    # 自检留下的痕迹清掉，别混进发布包
    shutil.rmtree(SCRATCH, ignore_errors=True)
    for d in cleanup:
        shutil.rmtree(d, ignore_errors=True)

    zips = []
    if not args.no_zip:
        arch = "win64" if sys.maxsize > 2 ** 32 else "win32"
        for _label, _spec, name in SPECS:
            folder = os.path.join(RELEASE, name)
            if not os.path.isdir(folder):
                say(f"没找到产物目录: {folder}")
                return 1
            zip_path = os.path.join(RELEASE, f"{name}-{VERSION}-{arch}.zip")
            zips.append((os.path.basename(zip_path), make_zip(folder, zip_path)))

    print()
    say(f"release/{VERSION}/ 内容：")
    for _label, _spec, name in SPECS:
        folder = os.path.join(RELEASE, name)
        if os.path.isdir(folder):
            print(f"    {name + '/':<32} {human(dir_size(folder)):>9}")
    for zname, zsize in zips:
        print(f"    {zname:<32} {human(zsize):>9}")

    print()
    if args.no_verify:
        say("完成（未自检）。")
        return 0
    if problems:
        say(f"完成，但自检有 {len(problems)} 项没通过：")
        for p in problems:
            print(f"    - {p}")
        return 1
    say("完成，自检全部通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
