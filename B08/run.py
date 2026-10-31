"""B08 基线入口：冻结 / 回放 / 真实链路 / 健康检查服务。

- --freeze                   生成场景快照 + BASELINE_INFO.md（见 freeze.py）
- --replay --scenario xxx    回归回放模式（见 replay.py，输入完全固定）
- --live --scenario s1~s5    真实链路模式（实时调用天气 API/模型/LLM，验证链路与异常退化）
- --serve                    启动健康检查服务（/health + /ask 固定提问），端口 8010

版本锁定：本轮验证全程固定 model_version=b06-rf-v1，禁止动态切换模型。
用法（项目根目录）：
  python B08/run.py --freeze
  python B08/run.py --replay --scenario b08_s3_weather
  python B08/run.py --live --scenario s3
  python B08/run.py --serve
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for d in (ROOT / "B07" / "S5", ROOT / "B07" / "S4", ROOT / "B07" / "S3",
          ROOT / "B07" / "S2", ROOT / "B07" / "S1", ROOT / "B02", ROOT):
    sys.path.insert(0, str(d))

B08_DIR = Path(__file__).resolve().parent

APP_VERSION = "B08_baseline_01"
MODEL_VERSION = "b06-rf-v1"  # 版本锁定：本轮验证固定同一模型
SERVE_PORT = 8010

LIVE_SCENES = ("s1", "s2", "s3", "s4", "s5")

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


# ---------------- 真实链路模式（复用 B07 已有链路，不新增功能） ----------------

def run_live(scene):
    """真实链路：实时调用天气 API、B06 模型、LLM。返回 B07 组件生成的记录。"""
    if scene == "s1":
        from B07.S1.run import run_pipeline
        return run_pipeline()
    if scene == "s2":
        from B07.S2.run import run_pipeline
        return run_pipeline()
    if scene == "s3":
        from B07.S3.run import run_pipeline
        return run_pipeline("with_weather")
    if scene == "s4":
        from B07.S4.run import run_pipeline
        return run_pipeline("with_evidence")
    if scene == "s5":
        from B07.S5.run import run_pipeline
        return run_pipeline("fault", fault="weather_unavailable")
    raise ValueError("未知场景：%s（可选 %s）" % (scene, LIVE_SCENES))


# ---------------- 健康检查服务（/health + /ask） ----------------

def build_app():
    import httpx
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    app = FastAPI(title="GreenMate B08 baseline")

    def check_external_weather():
        """外部天气 API 连通性探测（2 秒超时，明确提示可用/异常）。"""
        try:
            r = httpx.get(
                "https://api.open-meteo.com/v1/forecast",
                params={"latitude": 32.06, "longitude": 118.79,
                        "current": "temperature_2m"},
                timeout=2.0)
            return "ok" if r.status_code == 200 else "error(%s)" % r.status_code
        except Exception as e:
            return "unavailable(%s)" % type(e).__name__

    @app.get("/health")
    def health():
        """健康检查：系统就绪与外部 API 异常都有明确提示。"""
        knowledge_ok = (ROOT / "B04" / "knowledge" / "knowledge_base.json").exists()
        model_ok = (ROOT / "B06" / "models" / "b06_model.joblib").exists()
        db_ok = (ROOT / "B02" / "data" / "greenmate_b02.db").exists()
        scenarios_ok = (B08_DIR / "scenarios").exists() and \
            len(list((B08_DIR / "scenarios").glob("*.json"))) >= 5
        weather = check_external_weather()
        checks = {
            "knowledge_base": "ok" if knowledge_ok else "missing",
            "model": "ok" if model_ok else "missing",
            "database": "ok" if db_ok else "missing",
            "scenarios": "ok" if scenarios_ok else "missing",
            "external_weather_api": weather,
        }
        system_ready = all(v == "ok" for k, v in checks.items() if k != "external_weather_api")
        if system_ready and weather == "ok":
            status = "ok"
        elif system_ready:
            status = "degraded"  # 系统就绪但外部 API 异常（明确提示）
        else:
            status = "error"
        return {
            "status": status,
            "app_version": APP_VERSION,
            "model_version": MODEL_VERSION,
            "checks": checks,
            "note": ("status=ok 系统就绪且外部 API 可用；degraded 系统就绪但外部天气 API 异常"
                     "（影响 live 模式天气证据）；error 系统组件缺失"),
        }

    @app.post("/ask")
    def ask(payload: dict):
        """执行固定提问（真实链路），生成独立 run_id。"""
        scene = (payload or {}).get("scenario", "s3")
        if scene not in LIVE_SCENES:
            return JSONResponse(status_code=400, content={
                "detail": "未知场景 %s（可选 %s）" % (scene, LIVE_SCENES)})
        try:
            record = run_live(scene)
            judgment = (record.get("structured_judgment")
                        or record.get("step4_structured_judgment") or {})
            return {
                "run_id": record.get("run_id"),
                "scenario": scene,
                "verdict": judgment.get("verdict"),
                "model_version": MODEL_VERSION,
                "app_version": APP_VERSION,
            }
        except Exception as e:
            return JSONResponse(status_code=502, content={
                "detail": "真实链路执行失败：%s" % e})

    return app


def serve():
    import uvicorn
    app = build_app()
    print("[B08] 健康检查服务启动：http://127.0.0.1:%d" % SERVE_PORT)
    print("[B08]   GET /health   健康检查（系统就绪 / 外部 API 异常明确提示）")
    print("[B08]   POST /ask     固定提问（真实链路），生成独立 run_id")
    uvicorn.run(app, host="127.0.0.1", port=SERVE_PORT)


# ---------------- 入口 ----------------

def main():
    parser = argparse.ArgumentParser(description="GreenMate B08 基线入口")
    parser.add_argument("--freeze", action="store_true", help="生成场景快照与 BASELINE_INFO.md")
    parser.add_argument("--replay", action="store_true", help="回归回放模式")
    parser.add_argument("--live", action="store_true", help="真实链路模式")
    parser.add_argument("--scenario", help="场景（replay: b08_*；live: s1~s5）")
    parser.add_argument("--check", action="store_true", help="回放附加一致性自检")
    parser.add_argument("--serve", action="store_true", help="启动健康检查服务（端口 8010）")
    args = parser.parse_args()

    if args.serve:
        serve()
        return 0
    if args.freeze:
        from freeze import main as freeze_main
        return freeze_main()
    if args.replay:
        from replay import load_snapshot, render_replay, check_snapshot
        if not args.scenario:
            from replay import list_scenarios
            print("可用场景：%s（示例：python B08/run.py --replay --scenario b08_s3_weather）"
                  % ", ".join(list_scenarios()))
            return 1
        snapshot = load_snapshot(args.scenario)
        print(render_replay(snapshot))
        if args.check:
            problems = check_snapshot(snapshot)
            if problems:
                print("\n[自检] FAIL：%s" % problems)
                return 1
            print("\n[自检] PASS：快照字段完整，版本标记正确（%s / %s）" % (
                snapshot["app_version"], snapshot["model_version"]))
        return 0
    if args.live:
        if not args.scenario:
            print("需要 --scenario（可选 %s）" % ", ".join(LIVE_SCENES))
            return 1
        record = run_live(args.scenario)
        print("\n[B08 live] 场景 %s 执行完成，run_id=%s，model_version=%s（版本锁定）"
              % (args.scenario, record.get("run_id"), MODEL_VERSION))
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
