from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import socket
from threading import Thread
from time import monotonic, sleep
from urllib.request import urlopen

import uvicorn


@dataclass(slots=True)
class DesktopServerHandle:
    server: uvicorn.Server
    thread: Thread


def _load_webview_module() -> object:
    try:
        import webview
    except ImportError as exc:
        raise RuntimeError(
            "窗口模式依赖 pywebview，当前环境未安装该依赖。"
        ) from exc

    return webview


def _create_server(app: object, host: str, port: int) -> uvicorn.Server:
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port))
    server.install_signal_handlers = lambda: None
    return server


def _start_server_thread(server: uvicorn.Server) -> Thread:
    thread = Thread(target=server.run, name="dify-win-agent-server", daemon=True)
    thread.start()
    return thread


def _port_available(host: str, port: int) -> bool:
    bind_host = host
    if host in {"", "localhost"}:
        bind_host = "127.0.0.1"

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((bind_host, port))
        except OSError:
            return False

    return True


def _wait_for_server_started(
    handle: DesktopServerHandle,
    timeout_seconds: float = 10.0,
) -> None:
    deadline = monotonic() + timeout_seconds

    while monotonic() < deadline:
        if getattr(handle.server, "started", False):
            return
        if not handle.thread.is_alive():
            raise RuntimeError("窗口模式启动失败，内置服务线程提前退出。")
        sleep(0.1)

    raise RuntimeError("窗口模式启动失败，内置服务未在预期时间内完成启动。")


def _wait_for_url(
    url: str,
    timeout_seconds: float = 10.0,
    opener: Callable[..., object] = urlopen,
) -> None:
    deadline = monotonic() + timeout_seconds
    last_error: Exception | None = None

    while monotonic() < deadline:
        try:
            with opener(url, timeout=1.0) as response:
                status_code = getattr(response, "status", 200)
                if 200 <= status_code < 500:
                    return
        except Exception as exc:  # pragma: no cover - exercised through retry behavior
            last_error = exc
            sleep(0.1)

    message = f"窗口模式启动失败，无法连接 {url}"
    if last_error is not None:
        raise RuntimeError(f"{message}：{last_error}") from last_error

    raise RuntimeError(message)


def _stop_server(handle: DesktopServerHandle, join_timeout: float = 5.0) -> None:
    handle.server.should_exit = True
    if handle.thread.is_alive():
        handle.thread.join(join_timeout)


def _bind_window_close(window: object, on_close: Callable[[], None]) -> None:
    events = getattr(window, "events", None)
    closed_event = getattr(events, "closed", None)
    if closed_event is None:
        return

    closed_event += on_close


def run_dashboard_window(
    app: object,
    host: str,
    port: int,
    dashboard_url: str,
    health_url: str,
    title: str = "dify-win-agent 控制台",
) -> int:
    webview = _load_webview_module()
    if not _port_available(host, port):
        raise RuntimeError(f"启动失败：端口 {port} 已被占用，请先关闭旧实例后重试。")

    server = _create_server(app, host, port)
    handle = DesktopServerHandle(server=server, thread=_start_server_thread(server))

    try:
        _wait_for_server_started(handle)
        _wait_for_url(health_url)
        window = webview.create_window(
            title,
            dashboard_url,
            width=1380,
            height=920,
            min_size=(1140, 720),
            resizable=True,
        )
        _bind_window_close(window, lambda: _stop_server(handle))
        webview.start(debug=False)
    finally:
        _stop_server(handle)

    return 0