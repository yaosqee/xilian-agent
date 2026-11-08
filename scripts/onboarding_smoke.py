"""真实 Onboarding 冒烟（无 Key 启动路径）。

在临时 XILIAN_HOME 中启动 main.py，验证：
1. 没有 Key 时进入引导模式；
2. /api/config/check 返回 false；
3. 引导页可访问；
4. 空 Key 保存返回 400，不写 provider；
5. 临时数据库创建成功，且没有 provider 行。

不会读取/修改项目 .env，也不会使用真实 data/xilian.db。

用法：
    uv run python scripts/onboarding_smoke.py
    uv run python scripts/onboarding_smoke.py --keep
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
PROVIDER_KEYS = (
    "DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY_2", "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "MIMO_API_KEY",
    "QWEATHER_API_KEY", "ZHIPU_SEARCH_API_KEY", "ZHIPU_API_KEY",
)


def _wait_http(url: str, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
            time.sleep(0.5)
    raise RuntimeError(f"服务未在 {timeout}s 内启动: {last}")


def _json(url: str, payload: dict | None = None) -> tuple[int, dict]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, {"raw": body}


def _kill(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _pids_on_port(port: int) -> list[int]:
    """Windows netstat 找监听端口的 PID；用于清理 onboarding 重启后的进程。"""
    try:
        out = subprocess.check_output(
            ["netstat", "-ano"], text=True, errors="ignore", timeout=10,
        )
    except Exception:
        return []
    pids = []
    needle = f":{port}"
    for line in out.splitlines():
        if "LISTENING" not in line.upper() or needle not in line:
            continue
        parts = line.split()
        if parts and parts[-1].isdigit():
            pids.append(int(parts[-1]))
    return sorted(set(pids))


def _kill_port(port: int) -> None:
    for pid in _pids_on_port(port):
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--exe", type=Path, default=None, help="用打包 exe 做冒烟")
    parser.add_argument("--image", type=Path, default=None, help="上传该图片并跑一次识图聊天")
    parser.add_argument("--keep", action="store_true", help="保留临时目录")
    args = parser.parse_args()

    temp = Path(tempfile.mkdtemp(prefix="xilian-onboarding-smoke-"))
    log_path = temp / "smoke.log"
    proc: subprocess.Popen | None = None
    ok = False
    try:
        env = os.environ.copy()
        for key in PROVIDER_KEYS:
            env.pop(key, None)
        # Windows exe 的 PyInstaller 解压需要合法 TEMP；Git Bash 可能给 /tmp。
        # 用系统 Temp 的父目录，避免把解压目录再嵌进临时工作目录。
        win_tmp = temp.parent
        env.update({
            "XILIAN_HOME": str(temp),
            "HTTP_PORT": str(args.port),
            "FRONTEND_DEV": "0",
            "PYTHONUNBUFFERED": "1",
            "MODEL_ROUTING_V2": "1",
            "LOOP_V2": "1",
            "DEEPSEEK_DISABLE_THINKING": "1",
            "TEMP": str(win_tmp),
            "TMP": str(win_tmp),
        })
        # 开发模式用项目解释器；--exe 先复制到临时目录再运行。
        # 某些 Windows 环境下，从项目目录直接运行 onefile exe 会在解压临时目录时失败；
        # 复制到系统临时目录可模拟真实安装位置。
        if args.exe:
            exe_copy = temp / "app.exe"
            shutil.copy2(args.exe.resolve(), exe_copy)
            command = [str(exe_copy)]
        else:
            command = [sys.executable, str(ROOT / "main.py")]
        log_file = log_path.open("w", encoding="utf-8")
        proc = subprocess.Popen(
            command,
            cwd=temp,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )

        base = f"http://127.0.0.1:{args.port}"
        _wait_http(f"{base}/api/config/check")

        status, data = _json(f"{base}/api/config/check")
        assert status == 200 and data.get("has_api_key") is False, data

        with urllib.request.urlopen(f"{base}/", timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        assert resp.status == 200 and "<div id=\"root\"" in html, "引导页未返回前端 HTML"

        status, _ = _json(f"{base}/api/config/save", {
            "provider": "deepseek", "api_key": "",
        })
        assert status == 400, f"空 Key 应返回 400，实际 {status}"

        db_path = temp / "data" / "xilian.db"
        assert db_path.exists(), "临时数据库未创建"
        import sqlite3
        with sqlite3.connect(db_path) as conn:
            providers = conn.execute("select count(*) from model_providers").fetchone()[0]
        assert providers == 0, f"空 Key 不应写 provider，实际 {providers}"
        assert not (temp / ".env").exists(), "Onboarding 不应创建 .env"

        smoke_key = os.getenv("SMOKE_DEEPSEEK_KEY", "").strip()
        if smoke_key:
            # 真实 Key 路径：保存 → 主进程重启 → /api/status 可用 → DB 有 provider。
            status, saved = _json(f"{base}/api/config/save", {
                "provider": "deepseek", "api_key": smoke_key,
            })
            assert status == 200 and saved.get("status") == "ok", saved

            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                raise RuntimeError("保存 Key 后引导进程未退出")

            _wait_http(f"{base}/api/status", timeout=120)
            status, status_data = _json(f"{base}/api/status")
            assert status == 200, status_data

            with sqlite3.connect(db_path) as conn:
                providers = conn.execute(
                    "select provider, key_source from model_providers"
                ).fetchall()
            assert ("deepseek", "db") in providers, providers
            assert not (temp / ".env").exists(), "保存 Key 不应写 .env"
            print("PASS: 真实 Key 保存 + 重启 + /api/status")
            print(f"  providers={providers}")
            print(f"  status_keys={sorted(status_data)[:8]}")

            if args.image:
                image_path = args.image.resolve()
                assert image_path.exists(), f"图片不存在: {image_path}"
                with httpx.Client(base_url=base, timeout=120) as client:
                    with image_path.open("rb") as fh:
                        upload = client.post(
                            "/api/upload",
                            files={"file": (image_path.name, fh, "image/webp")},
                        )
                    upload.raise_for_status()
                    image_url = upload.json().get("url")
                    assert image_url, upload.text
                    chat = client.post("/api/chat", json={
                        "message": "看看这张图里是什么？",
                        "images": [image_url],
                        "user_id": "hezi",
                    })
                    chat.raise_for_status()
                    chat_data = chat.json()
                reply = chat_data.get("reply", "")
                assert reply and "agent not ready" not in reply, chat_data
                print("PASS: 图片上传 + 识图聊天")
                print(f"  url={image_url}")
                print(f"  reply={reply[:200]}")

        print("PASS: 无 Key 引导模式")
        print(f"  temp={temp}")
        print(f"  check={data}")
        print(f"  db={db_path}")
        print(f"  log={log_path}")
        ok = True
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        if log_path.exists():
            print("\n--- last log ---", file=sys.stderr)
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            print("\n".join(lines[-25:]), file=sys.stderr)
        return 1
    finally:
        if proc is not None:
            _kill(proc)
        _kill_port(args.port)
        if ok and not args.keep:
            shutil.rmtree(temp, ignore_errors=True)
        elif not args.keep:
            # 失败时保留现场，方便排查。
            print(f"保留失败现场: {temp}")


if __name__ == "__main__":
    raise SystemExit(main())
