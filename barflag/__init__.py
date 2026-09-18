# barflag/__init__.py
"""横条旗帜生成器。

分层结构：
    report.py   日志与状态上报（逻辑层唯一的对外出口）
    core.py     解析、计算、配置、生成编排
    render.py   SVG / 位图渲染
    presets.py  预设文件扫描与读写
    deps.py     依赖检测与自动安装（带进度）
    cli.py      命令行前端
    gui.py      tkinter 图形前端

逻辑层（core/render/presets/deps）不依赖任何前端；前端只调用逻辑层。
"""

__version__ = "2.0"
