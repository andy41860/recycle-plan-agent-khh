"""Windows 一鍵啟動：mcp-recycle + Chainlit。Ctrl+C 時兩個子程序都會結束。

用法：uv run scripts/dev.py
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IS_WINDOWS = sys.platform == "win32"


def load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(ROOT / ".env")


def pump(prefix: str, stream) -> None:
    for line in iter(stream.readline, ""):
        print(f"{prefix} {line.rstrip()}", flush=True)


def start(prefix: str, args: list[str], env: dict[str, str]) -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, *args],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        # 獨立的 process group，才能單獨送 CTRL_BREAK_EVENT 而不影響本程序
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0,
    )
    threading.Thread(target=pump, args=(prefix, proc.stdout), daemon=True).start()
    return proc


def wait_port(host: str, port: int, proc: subprocess.Popen, timeout: float = 60) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            socket.create_connection((host, port), 1).close()
            return True
        except OSError:
            time.sleep(0.5)
    return False


def stop(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.send_signal(signal.CTRL_BREAK_EVENT if IS_WINDOWS else signal.SIGINT)
        proc.wait(timeout=5)
    except (subprocess.TimeoutExpired, OSError):
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if IS_WINDOWS:  # 連同子孫程序一起結束
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
            else:
                proc.kill()


def main() -> int:
    if IS_WINDOWS:  # 讓 CTRL_BREAK 與 Ctrl+C 走同一條關閉流程
        signal.signal(signal.SIGBREAK, signal.default_int_handler)
    load_env()
    env = {
        **os.environ,
        "PYTHONUTF8": "1",
        "PYTHONUNBUFFERED": "1",
    }
    mcp_port = int(env.get("MCP_PORT") or 8001)
    mcp_host = env.get("MCP_HOST") or "127.0.0.1"

    procs: list[subprocess.Popen] = []
    try:
        mcp = start("[mcp]", ["-m", "recycle_schedule.server"], env)
        procs.append(mcp)
        if not wait_port("127.0.0.1" if mcp_host == "0.0.0.0" else mcp_host, mcp_port, mcp):
            print("[dev] mcp-recycle 無法啟動，請看上方 [mcp] 訊息", file=sys.stderr)
            return 1
        ui = start(
            "[ui]",
            ["-m", "chainlit", "run", "agent/recycle_agent/app.py", "--headless", "--host", "0.0.0.0", "--port", "8000"],
            env,
        )
        procs.append(ui)
        print("[dev] 啟動完成：http://localhost:8000（Ctrl+C 結束）", flush=True)
        while all(p.poll() is None for p in procs):
            time.sleep(0.5)
        print("[dev] 有子程序已結束，關閉其餘程序", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        for p in reversed(procs):
            stop(p)


if __name__ == "__main__":
    sys.exit(main())
