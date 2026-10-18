"""B04 统一启动入口：B01(/)、B02(/B02)、B03(/B03)、B04(/B04) 同端口 8000。

不改动 B01 / B02 / B03 任何代码文件：只 import 它们的 FastAPI 应用并挂载。
sys.path 前缀显式排为 B04 → ROOT → B02 → B03（insert(0) 从头部插入，逆序调用）：
- `from app import` 命中 B04/app.py（B04 排最前）；
- `from main import` 命中根目录 main.py（B04 无 main.py，ROOT 在 B02 之前）；
- `from llm / from states import` 命中根目录模块（B04 无同名文件）；
- B02/B03 内部 import（db、simulator、evidence_store…）由各自目录兜底。

启动（项目根目录）：python B04/run.py
  - B04 知识增强：http://127.0.0.1:8000/B04
  - B03 天气证据：http://127.0.0.1:8000/B03
  - B02 数据记忆：http://127.0.0.1:8000/B02
  - B01 环境问答：http://127.0.0.1:8000/
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
B04_DIR = str(Path(__file__).resolve().parent)

sys.path.insert(0, str(ROOT / "B03"))
sys.path.insert(0, str(ROOT / "B02"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, B04_DIR)

import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402

from app import b04_app  # noqa: E402  （B04 子应用）
from B03.app import b03_app  # noqa: E402  （B03 子应用，未改动）
from B02.app import b02_app  # noqa: E402  （B02 子应用，未改动）
from main import app as b01_app  # noqa: E402  （B01 根 main.py，未改动）

combo = FastAPI(title="GreenMate B01+B02+B03+B04")
combo.mount("/B02", b02_app)
combo.mount("/B03", b03_app)
combo.mount("/B04", b04_app)
combo.mount("/", b01_app)  # 兜底：B01 原功能不变

if __name__ == "__main__":
    uvicorn.run(combo, host="127.0.0.1", port=8000)
