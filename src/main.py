from pathlib import Path
from threading import Timer
import os
import sys
import webbrowser

import uvicorn

from dify_win_agent.config import ConfigurationError, load_config
from dify_win_agent.desktop_window import run_dashboard_window
from dify_win_agent.elevation import ensure_elevated
from dify_win_agent.runtime_paths import ensure_runtime_directories
from dify_win_agent.server import create_app


def _application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    return Path(__file__).resolve().parents[1]


def _dashboard_url(host: str, port: int) -> str:
    if host in {"", "0.0.0.0", "::", "localhost"}:
        return f"http://127.0.0.1:{port}/"

    return f"http://{host}:{port}/"


def _flag_enabled(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _should_use_desktop_window() -> bool:
    if not getattr(sys, "frozen", False):
        return False

    return _flag_enabled("DIFY_WIN_AGENT_WINDOW_MODE", "1")


def _should_open_dashboard() -> bool:
    if not getattr(sys, "frozen", False):
        return False

    if _should_use_desktop_window():
        return False

    return _flag_enabled("DIFY_WIN_AGENT_OPEN_BROWSER", "1")


def _schedule_dashboard_open(host: str, port: int) -> None:
    if not _should_open_dashboard():
        return

    timer = Timer(1.0, lambda: webbrowser.open(_dashboard_url(host, port)))
    timer.daemon = True
    timer.start()


def _health_url(host: str, port: int) -> str:
    return f"{_dashboard_url(host, port).rstrip('/')}/health"


def _launch_desktop_window(app: object, host: str, port: int) -> int:
    return run_dashboard_window(
        app=app,
        host=host,
        port=port,
        dashboard_url=_dashboard_url(host, port),
        health_url=_health_url(host, port),
    )


def _show_startup_error(message: str) -> None:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, "dify-win-agent", 0x10)
            return
        except (AttributeError, OSError):
            pass

    print(message, file=sys.stderr)


def main() -> int:
    if ensure_elevated():
        return 0

    application_root = _application_root()

    try:
        config = load_config(application_root=application_root)
    except ConfigurationError as exc:
        _show_startup_error(f"配置错误：{exc}")
        return 1

    runtime_paths = ensure_runtime_directories(
        application_root,
        config.log_dir,
        config.report_dir,
    )
    app = create_app(config, runtime_paths)

    if _should_use_desktop_window():
        try:
            return _launch_desktop_window(app, config.host, config.port)
        except RuntimeError as exc:
            _show_startup_error(str(exc))
            return 1

    _schedule_dashboard_open(config.host, config.port)
    uvicorn.run(app, host=config.host, port=config.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
