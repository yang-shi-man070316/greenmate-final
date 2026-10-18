"""B02 组合启动入口：一个进程同时提供 B01（/）与 B02（/B02）。

不改动 B01 任何代码文件：只是 import B01 的 FastAPI 应用并挂载到根路径，
B01 原有功能与路由完全不变；B02 子应用挂载在 /B02。

启动（项目根目录）：python B02/main.py
访问：
  - B02 数据记忆：http://127.0.0.1:8000/B02
  - B01 原页面：  http://127.0.0.1:8000/
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402

from app import b02_app           # B02 子应用（B02/app.py）
from main import app as b01_app   # B01 应用（根目录 main.py，未做任何修改）

combo = FastAPI(title="GreenMate B01+B02")
combo.mount("/B02", b02_app)
combo.mount("/", b01_app)  # 兜底挂载：B01 原功能不变（先注册 /B02，优先匹配）

if __name__ == "__main__":
    uvicorn.run(combo, host="127.0.0.1", port=8000)
