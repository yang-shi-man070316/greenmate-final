"""B03 统一启动入口：B01(/)、B02(/B02)、B03(/B03) 同端口 8000。

不改动 B01 / B02 任何代码文件：只 import 它们的 FastAPI 应用并挂载。
注意 sys.path 顺序（B03 → B02 → 项目根），保证各模块内部 import 解析正确。

启动（项目根目录）：python B03/run.py
  - B03 天气证据：http://127.0.0.1:8000/B03
  - B02 数据记忆：http://127.0.0.1:8000/B02
  - B01 环境问答：http://127.0.0.1:8000/
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
B03_DIR = str(Path(__file__).resolve().parent)

# import 顺序关键：B02 目录里有同名 app.py/main.py，不能误命中。
# 显式把 sys.path 前缀排成 B03 → ROOT → B02（insert(0) 是从头部插入，逆序调用）：
# - `from app import` 命中 B03/app.py（B03 排最前）；
# - `from main import` 命中根目录 main.py（B01，B03 无 main.py，ROOT 在 B02 之前）；
# - B02/app.py 内部 `import db / from simulator import` 由 B02 目录兜底。
sys.path.insert(0, str(ROOT / "B02"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, B03_DIR)

import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402

from app import b03_app  # noqa: E402  （B03 子应用）
from B02.app import b02_app  # noqa: E402  （B02 子应用，未改动）
from main import app as b01_app  # noqa: E402  （B01 根 main.py，未改动）

combo = FastAPI(title="GreenMate B01+B02+B03")
combo.mount("/B02", b02_app)
combo.mount("/B03", b03_app)
combo.mount("/", b01_app)  # 兜底：B01 原功能不变

if __name__ == "__main__":
    uvicorn.run(combo, host="127.0.0.1", port=8000)
