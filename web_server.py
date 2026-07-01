#!/usr/bin/env python3
"""
Web界面启动脚本

启动Web管理界面：
    python web_server.py

默认监听 0.0.0.0（所有网卡），同网段设备可用内网 IP 访问。
"""

import os
import socket
import sys
from pathlib import Path

# 添加src到路径（当前进程 + 子进程热重载时亦能 import llm_qauto）
_ROOT = Path(__file__).resolve().parent
_src = str(_ROOT / "src")
sys.path.insert(0, _src)
os.environ["PYTHONPATH"] = _src + os.pathsep + os.environ.get("PYTHONPATH", "")

try:
    from dotenv import load_dotenv

    load_dotenv(_ROOT / ".env")
except ImportError:
    pass

from llm_qauto.web.api import start_web_server


def _local_ipv4_addresses():
    """本机可用于局域网访问的 IPv4 地址（不含 127.0.0.1）。"""
    seen = set()
    addrs = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip.startswith("127.") or ip in seen:
                continue
            seen.add(ip)
            addrs.append(ip)
    except OSError:
        pass
    # Windows 上 getaddrinfo 有时漏网卡，再试 UDP 探测
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip not in seen and not ip.startswith("127."):
            addrs.insert(0, ip)
    except OSError:
        pass
    return addrs


def _print_access_urls(host: str, port: int):
    print("访问地址：")
    print(f"  本机      http://127.0.0.1:{port}")
    if host in ("0.0.0.0", "::"):
        for ip in _local_ipv4_addresses():
            print(f"  内网      http://{ip}:{port}")
    elif host not in ("127.0.0.1", "localhost"):
        print(f"  指定网卡  http://{host}:{port}")
    print()
    print("其他网络（外网/跨网段）访问还需：")
    print("  1) 路由器端口转发 → 本机内网 IP + 端口，或")
    print("  2) 内网穿透（frp / ngrok / Cloudflare Tunnel）")
    print("  3) Windows 防火墙放行该端口（管理员 PowerShell）：")
    print(f'     New-NetFirewallRule -DisplayName "LLM-QAuto Web" -Direction Inbound -Protocol TCP -LocalPort {port} -Action Allow')
    print()


if __name__ == "__main__":
    host = os.environ.get("WEB_HOST", "0.0.0.0").strip() or "0.0.0.0"
    try:
        port = int(os.environ.get("WEB_PORT", "8080"))
    except ValueError:
        port = 8080

    print("=" * 60)
    print("LLM-QAuto Web界面")
    print("=" * 60)
    print()
    print(f"正在启动 Web 服务器（{host}:{port}）…")
    _print_access_urls(host, port)
    if os.name == "nt" and os.environ.get("QAUTO_WEB_RELOAD") is None:
        print("热重载: Windows 默认关闭（避免 Ctrl+C 后残留进程导致页面无法加载）")
        print("        开启请设置环境变量 QAUTO_WEB_RELOAD=1")
    else:
        print("热重载: 默认开启（修改 src 下 Python/静态资源后自动重启）")
        print("        关闭请设置环境变量 QAUTO_WEB_RELOAD=0")
    print()
    print("按 Ctrl+C 停止服务器")
    if os.name == "nt":
        print("若停止后页面仍无法加载，请执行: powershell -File scripts/stop_server.ps1")
        print("然后硬刷新浏览器 (Ctrl+Shift+R)")
    print("=" * 60)
    print()

    start_web_server(host=host, port=port)
