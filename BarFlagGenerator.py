#!/usr/bin/env python3
# BarFlagGenerator.py
# 条形旗帜生成器 —— 入口脚本
#
# 用法:
#   图形界面:   python BarFlagGenerator.py
#   文本交互:   python BarFlagGenerator.py --cli
#   命令行模式: python BarFlagGenerator.py -r 900x600 -s "#FF0000 1,#FFFFFF 1.5" -f svg -o flag.svg
#   强制图形:   python BarFlagGenerator.py --gui
#
# 规则：不带任何参数 → 图形界面；带了参数 → 命令行模式（除非显式 --gui）。
#
# 依赖：
#   pillow       生成 PNG/JPG 需要
#   sv-ttk       界面主题（Sun Valley，模仿 Windows 11 外观）
#   tkinterdnd2  把 .flagpreset 拖进窗口载入
#   以上三个缺失时都会自动 pip 安装。
#   tkinter 是标准库（pip 上没有真正的同名包），只能检测、不能自动安装。
#
# 代码结构（逻辑层与前端完全解耦）：
#   barflag/report.py   日志与状态上报 —— 逻辑层唯一的对外出口
#   barflag/core.py     解析、计算、配置、生成编排（不 import tkinter/argparse）
#   barflag/render.py   SVG / 位图渲染
#   barflag/presets.py  预设扫描与读写
#   barflag/deps.py     依赖检测与自动安装（带 pip 进度）
#   barflag/cli.py      命令行前端
#   barflag/gui.py      tkinter 图形前端
#
# 打包 release：
#   python build.py
#   产物在 release/<版本号>/ 下：BarFlagGenerator/（图形版）、
#   BarFlagGenerator-cli/（命令行版），以及对应的两个 zip。
#   打包脚本会自动自检，并确认预设会存在 exe 同级目录、不会因重启丢失。
#   打包配置在 packaging/ 里。
#
# 日志约定：
#   [-]  失败  红色
#   <!>  警告  黄色
#   [+]  成功  绿色
#   [*]  普通  白色

import os
import sys

# 让 barflag 包在"双击运行"和"从别处调用"时都能被找到
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def decide_mode(argv):
    """决定跑哪个前端：显式开关优先，其次看有没有参数。"""
    if "--gui" in argv:
        return "gui"
    if "--cli" in argv:
        return "cli"
    return "cli" if argv else "gui"


def run_gui():
    try:
        import tkinter  # noqa: F401
    except ImportError:
        if getattr(sys, "frozen", False):
            sys.stderr.write(
                "这是命令行版（打包时未包含图形组件）。\n"
                "要使用图形界面，请运行 BarFlagGenerator.exe。\n")
        else:
            sys.stderr.write(
                "无法启动图形界面：当前 Python 没有 tkinter（标准库组件，pip 装不了）。\n"
                "请改用 python.org 或 Python Install Manager 安装的完整版 Python，\n"
                "或加上 --cli 使用文本模式。\n")
        return 1
    try:
        from barflag import gui
    except ImportError as e:
        sys.stderr.write(f"载入图形界面失败: {e}\n")
        return 1
    return gui.main()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    mode = decide_mode(argv)
    return run_gui() if mode == "gui" else _run_cli(argv)


def _run_cli(argv):
    try:
        from barflag import cli
    except ImportError as e:
        sys.stderr.write(f"载入命令行模块失败: {e}\n")
        return 1
    return cli.main(argv)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
