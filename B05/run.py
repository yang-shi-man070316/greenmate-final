"""B05 统一启动入口：B01(/)、B02(/B02)、B03(/B03)、B04(/B04)、B05(/B05) 同端口 8000。

不改动 B01–B04 任何代码文件：只 import 它们的 FastAPI 应用并挂载。
sys.path 前缀显式排为 B05 → ROOT → B02 → B03 → B04（insert(0) 从头部插入，逆序调用）：
- `from app import` 命中 B05/app.py（B05 排最前）；
- `from main import` 命中根目录 main.py（B05 无 main.py，ROOT 在 B02 之前）；
- B02/B03/B04 内部 import（db、simulator、evidence_store、weather_client、retriever…）由各自目录兜底；
- B05 内部 from llm / from states 命中根目录模块。

启动（项目根目录）：python B05/run.py
  - B05 工具智能体：http://127.0.0.1:8000/B05
  - B04 知识增强：http://127.0.0.1:8000/B04
  - B03 天气证据：http://127.0.0.1:8000/B03
  - B02 数据记忆：http://127.0.0.1:8000/B02
  - B01 环境问答：http://127.0.0.1:8000/
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
B05_DIR = str(Path(__file__).resolve().parent)

sys.path.insert(0, str(ROOT / "B04"))
sys.path.insert(0, str(ROOT / "B03"))
sys.path.insert(0, str(ROOT / "B02"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, B05_DIR)

import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402

from app import b05_app  # noqa: E402  （B05 子应用）
from B04.app import b04_app  # noqa: E402  （未改动）
from B03.app import b03_app  # noqa: E402  （未改动）
from B02.app import b02_app  # noqa: E402  （未改动）
from main import app as b01_app  # noqa: E402  （未改动，根 main.py）

combo = FastAPI(title="GreenMate B01+B02+B03+B04+B05")
combo.mount("/B02", b02_app)
combo.mount("/B03", b03_app)
combo.mount("/B04", b04_app)
combo.mount("/B05", b05_app)
combo.mount("/", b01_app)  # 兜底：B01 原功能不变

if __name__ == "__main__":
    uvicorn.run(combo, host="127.0.0.1", port=8000)
