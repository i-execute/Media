#!/usr/bin/env python3
import socket
import os
import json
import base64
import struct
import sys
from datetime import datetime

SOCK = os.path.expanduser("~/.codex/app-server-control/app-server-control.sock")

USE_COLOR = sys.stdout.isatty()

if USE_COLOR:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    CYAN = "\033[36m"
else:
    RESET = BOLD = DIM = GREEN = YELLOW = RED = CYAN = ""


def ws_frame(data):
    data = data.encode() if isinstance(data, str) else data
    mask = os.urandom(4)
    n = len(data)

    if n < 126:
        head = bytes([0x81, 0x80 | n])
    elif n < 65536:
        head = bytes([0x81, 0x80 | 126]) + struct.pack("!H", n)
    else:
        head = bytes([0x81, 0x80 | 127]) + struct.pack("!Q", n)

    return head + mask + bytes(
        b ^ mask[i % 4] for i, b in enumerate(data)
    )


def recv_exact(sock, n):
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise RuntimeError("socket closed")
        data += chunk
    return data


def recv_frame(sock):
    b1, b2 = recv_exact(sock, 2)
    opcode = b1 & 0x0F
    masked = b2 & 0x80
    length = b2 & 0x7F

    if length == 126:
        length = struct.unpack("!H", recv_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", recv_exact(sock, 8))[0]

    mask = recv_exact(sock, 4) if masked else None
    data = recv_exact(sock, length)

    if mask:
        data = bytes(
            x ^ mask[i % 4] for i, x in enumerate(data)
        )

    return opcode, data


def send_json(sock, obj):
    sock.sendall(ws_frame(json.dumps(obj, separators=(",", ":"))))


def recv_json(sock):
    while True:
        opcode, data = recv_frame(sock)

        if opcode == 0x1:
            return json.loads(data.decode())

        if opcode == 0x9:
            n = len(data)
            if n < 126:
                sock.sendall(bytes([0x8A, n]) + data)

        elif opcode == 0x8:
            raise RuntimeError("server closed websocket")


def format_reset(timestamp):
    if not timestamp:
        return "—"

    return datetime.fromtimestamp(timestamp).astimezone().strftime(
        "%d.%m.%Y %H:%M:%S %Z"
    )


def format_window(minutes):
    if not minutes:
        return "—"

    if minutes % 43200 == 0:
        months = minutes // 43200
        return f"{months} month" if months == 1 else f"{months} months"

    if minutes % 10080 == 0:
        weeks = minutes // 10080
        return f"{weeks} week" if weeks == 1 else f"{weeks} weeks"

    if minutes % 1440 == 0:
        days = minutes // 1440
        return f"{days} day" if days == 1 else f"{days} days"

    if minutes % 60 == 0:
        hours = minutes // 60
        return f"{hours} hour" if hours == 1 else f"{hours} hours"

    return f"{minutes} min"


def progress_bar(percent, width=30):
    percent = max(0, min(100, int(percent)))
    filled = round(width * percent / 100)
    empty = width - filled

    if percent >= 90:
        color = RED
    elif percent >= 70:
        color = YELLOW
    else:
        color = GREEN

    return f"{color}{'█' * filled}{DIM}{'░' * empty}{RESET}"


def print_window(title, window):
    if not window:
        return

    used = int(window.get("usedPercent", 0))
    remaining = max(0, 100 - used)

    print(f"{BOLD}{title}{RESET}")
    print(f"  {progress_bar(used)}  {BOLD}{used}%{RESET} used")
    print(f"  Remaining: {GREEN}{remaining}%{RESET}")
    print(f"  Window:    {format_window(window.get('windowDurationMins'))}")
    print(f"  Resets:    {format_reset(window.get('resetsAt'))}")


def main():
    if not os.path.exists(SOCK):
        raise RuntimeError(f"Codex control socket not found: {SOCK}")

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(10)
    sock.connect(SOCK)

    key = base64.b64encode(os.urandom(16)).decode()

    handshake = (
        "GET / HTTP/1.1\r\n"
        "Host: localhost\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )

    sock.sendall(handshake.encode())

    response = b""
    while b"\r\n\r\n" not in response:
        chunk = sock.recv(4096)
        if not chunk:
            raise RuntimeError("WebSocket handshake failed")
        response += chunk

    status = response.split(b"\r\n", 1)[0]

    if b" 101 " not in status and not status.endswith(b" 101"):
        raise RuntimeError(
            "WebSocket upgrade failed: " +
            status.decode(errors="replace")
        )

    send_json(sock, {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "clientInfo": {
                "name": "codex-limits",
                "version": "1.0"
            }
        }
    })

    while True:
        response = recv_json(sock)

        if response.get("id") == 1:
            if "error" in response:
                raise RuntimeError(
                    json.dumps(response["error"], ensure_ascii=False)
                )
            break

    send_json(sock, {
        "jsonrpc": "2.0",
        "method": "initialized",
        "params": {}
    })

    send_json(sock, {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "account/rateLimits/read",
        "params": None
    })

    while True:
        response = recv_json(sock)

        if response.get("id") == 2:
            if "error" in response:
                raise RuntimeError(
                    json.dumps(response["error"], ensure_ascii=False)
                )

            result = response.get("result", {})
            break

    sock.close()

    limits = result.get("rateLimits") or {}
    plan = limits.get("planType", "unknown")

    print()
    print(f"{BOLD}{CYAN}Codex Usage{RESET}")
    print(f"{DIM}{'─' * 42}{RESET}")
    print(f"  Plan: {BOLD}{plan}{RESET}")
    print()

    print_window("Primary", limits.get("primary"))

    if limits.get("secondary"):
        print()
        print_window("Secondary", limits["secondary"])

    credits = limits.get("credits")

    if credits:
        if credits.get("unlimited"):
            print()
            print(f"{BOLD}Credits{RESET}")
            print(f"  Balance: {GREEN}unlimited{RESET}")
        elif credits.get("balance") is not None:
            print()
            print(f"{BOLD}Credits{RESET}")
            print(f"  Balance: {credits['balance']}")

    buckets = result.get("rateLimitsByLimitId")

    if buckets:
        for limit_id, bucket in buckets.items():
            if limit_id == limits.get("limitId"):
                continue

            print()
            print(f"{BOLD}Bucket: {limit_id}{RESET}")

            if bucket.get("primary"):
                print_window("Primary", bucket["primary"])

            if bucket.get("secondary"):
                print()
                print_window("Secondary", bucket["secondary"])

    print()
    print(f"{DIM}{'─' * 42}{RESET}")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as e:
        print(f"{RED}codex-limits: ERROR:{RESET} {e}")
        raise SystemExit(1)