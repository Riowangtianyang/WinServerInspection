import html
import os
import socket
from datetime import datetime, timezone
from getpass import getuser
from pathlib import Path
from string import Template
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from dify_win_agent.config import AppConfig, save_runtime_settings
from dify_win_agent.elevation import default_is_admin
from dify_win_agent.executor import execute_task
from dify_win_agent.models import DashboardSettingsRequest, ExecuteRequest
from dify_win_agent.reports import CommandExecutionResult
from dify_win_agent.runtime_paths import (
    RuntimePaths,
    ensure_runtime_directories,
    find_latest_artifact_path,
)


LIVE_LOG_LINE_LIMIT = 60
DIRECTORY_LIST_LIMIT = 200


def _summarize_execution(
    command_results: list[CommandExecutionResult],
) -> tuple[str, str]:
    failed_count = sum(1 for item in command_results if item.return_code != 0)

    if failed_count == 0:
        return "succeeded", "命令执行完成。"

    if failed_count == len(command_results):
        return (
            "failed",
            "命令执行失败，请检查返回结果、详细日志和执行报告，并根据错误信息处理后重试。",
        )

    return (
        "partially_failed",
        "部分命令执行失败，请检查返回结果、详细日志和执行报告，并根据错误信息处理后重试。",
    )


def _format_utc_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _format_optional_utc_timestamp(value: datetime | None) -> str:
    if value is None:
        return "尚未收到健康检查"

    return _format_utc_timestamp(value)


def _dashboard_url(host: str, port: int) -> str:
    if host in {"", "0.0.0.0", "::", "localhost"}:
        return f"http://127.0.0.1:{port}/"

    return f"http://{host}:{port}/"


def _recent_runtime_files(
    directory: Path | None,
    suffix: str,
    limit: int = 5,
) -> list[Path]:
    if directory is None or not directory.is_dir():
        return []

    items = [
        item
        for item in directory.iterdir()
        if item.is_file() and item.suffix.lower() == suffix
    ]
    items.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return items[:limit]


def _runtime_artifact_directory(
    runtime_paths: RuntimePaths,
    artifact_kind: str,
) -> Path | None:
    if artifact_kind == "logs":
        return runtime_paths.log_dir
    if artifact_kind == "reports":
        return runtime_paths.report_dir

    return None


def _runtime_artifact_href(artifact_kind: str, file_name: str) -> str:
    return f"/api/v1/runtime/artifacts/{artifact_kind}/{quote(file_name)}"


def _resolve_runtime_artifact_path(
    runtime_paths: RuntimePaths,
    artifact_kind: str,
    file_name: str,
) -> Path:
    directory = _runtime_artifact_directory(runtime_paths, artifact_kind)
    if directory is None or not directory.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")

    if Path(file_name).name != file_name:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")

    artifact_path = (directory / file_name).resolve()
    if artifact_path.parent != directory.resolve() or not artifact_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")

    expected_suffix = ".log" if artifact_kind == "logs" else ".docx"
    if artifact_path.suffix.lower() != expected_suffix:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")

    return artifact_path


def _tail_text(file_path: Path, max_lines: int = LIVE_LOG_LINE_LIMIT) -> str:
    lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-max_lines:])


def _live_log_payload(runtime_paths: RuntimePaths) -> dict[str, str | None]:
    latest_logs = _recent_runtime_files(runtime_paths.log_dir, ".log", limit=1)
    if not latest_logs:
        return {
            "file_name": None,
            "updated_at_utc": None,
            "content": "暂无实时日志。",
        }

    latest_log = latest_logs[0]
    updated_at = datetime.fromtimestamp(latest_log.stat().st_mtime, tz=timezone.utc)
    return {
        "file_name": latest_log.name,
        "updated_at_utc": _format_utc_timestamp(updated_at),
        "content": _tail_text(latest_log),
    }


def _resolve_user_path(value: str, root_dir: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root_dir / path

    return path.resolve()


def _list_available_drives() -> list[str]:
    if os.name != "nt":
        return [str(Path("/").resolve())]

    return [
        f"{letter}:\\"
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        if Path(f"{letter}:\\").exists()
    ]


def _favorite_directories(root_dir: Path | None) -> list[dict[str, str]]:
    home = Path.home()
    candidates: list[tuple[str, Path]] = []
    if root_dir is not None:
        candidates.append(("工作目录", root_dir))

    for label, path in (
        ("桌面", home / "Desktop"),
        ("文档", home / "Documents"),
        ("下载", home / "Downloads"),
        ("用户目录", home),
    ):
        if path.exists():
            candidates.append((label, path))

    seen_paths: set[str] = set()
    favorites: list[dict[str, str]] = []
    for label, path in candidates:
        resolved = str(path.resolve())
        if resolved in seen_paths:
            continue

        seen_paths.add(resolved)
        favorites.append({"label": label, "path": resolved})

    return favorites


def _directory_browser_payload(path: str | None, root_dir: Path | None) -> dict[str, object]:
    fallback_root = (root_dir or Path.home()).resolve()
    current_path = _resolve_user_path(path, fallback_root) if path else fallback_root
    if not current_path.exists():
        current_path = current_path.parent if current_path.parent.exists() else fallback_root

    if current_path.is_file():
        current_path = current_path.parent

    current_path = current_path.resolve()
    try:
        directories = sorted(
            (item for item in current_path.iterdir() if item.is_dir()),
            key=lambda item: item.name.lower(),
        )
    except (PermissionError, OSError):
        directories = []

    parent_path: str | None = None
    if current_path.parent != current_path:
        parent_path = str(current_path.parent.resolve())

    return {
        "current_path": str(current_path),
        "parent_path": parent_path,
        "children": [
            {"name": directory.name, "path": str(directory.resolve())}
            for directory in directories[:DIRECTORY_LIST_LIMIT]
        ],
        "drives": _list_available_drives(),
        "favorites": _favorite_directories(root_dir),
    }


def _machine_ipv4_addresses() -> list[str]:
    addresses: set[str] = set()
    for host_name in (socket.gethostname(), socket.getfqdn()):
        try:
            infos = socket.getaddrinfo(host_name, None, family=socket.AF_INET)
        except socket.gaierror:
            continue

        for info in infos:
            addresses.add(info[4][0])

    if not addresses:
        return ["127.0.0.1"]

    filtered = [address for address in sorted(addresses) if not address.startswith("169.254.")]
    if len(filtered) > 1 and "127.0.0.1" in filtered:
        filtered = [address for address in filtered if address != "127.0.0.1"]

    return filtered or ["127.0.0.1"]


def _system_info_payload() -> list[tuple[str, str]]:
    computer_name = os.environ.get("COMPUTERNAME") or socket.gethostname()
    login_user = getuser()
    current_permission = "管理员" if default_is_admin() else "普通用户"
    ipv4_addresses = " / ".join(_machine_ipv4_addresses())

    return [
        ("电脑名称", computer_name),
        ("登录用户", login_user),
        ("当前权限", current_permission),
        ("IPv4 地址", ipv4_addresses),
    ]


def _render_kv_rows(
    items: list[tuple[str, str]],
    value_id_map: dict[str, str] | None = None,
) -> str:
    rows: list[str] = []
    for label, value in items:
        value_id = ""
        if value_id_map and label in value_id_map:
            value_id = f' id="{html.escape(value_id_map[label], quote=True)}"'

        rows.append(
            "<div class=\"kv\">"
            f"<span class=\"k\">{html.escape(label)}</span>"
            f"<strong class=\"v\"{value_id}>{html.escape(value)}</strong>"
            "</div>"
        )

    return "".join(rows)


def _render_file_group(title: str, items: list[Path], artifact_kind: str) -> str:
    if not items:
        content = '<li class="artifact-empty">暂无文件</li>'
    else:
        content = "".join(
            "<li>"
            f'<a class="artifact-link" href="{_runtime_artifact_href(artifact_kind, item.name)}" download>'
            f'<span class="artifact-link-name">{html.escape(item.name)}</span>'
            f'<span class="artifact-link-meta">{html.escape(_format_utc_timestamp(datetime.fromtimestamp(item.stat().st_mtime, tz=timezone.utc)))} · 点击下载</span>'
            "</a>"
            "</li>"
            for item in items
        )

    return (
        "<section class=\"artifact-group\">"
        f"<h3>{html.escape(title)}</h3>"
        f"<ul class=\"artifact-list\">{content}</ul>"
        "</section>"
    )


def _render_recent_artifacts_panel(
    recent_logs: list[Path],
    recent_reports: list[Path],
) -> str:
    return (
        "<section class=\"panel wide-panel\">"
        "<h2>最近产物</h2>"
        "<div class=\"artifact-stack\">"
        f"{_render_file_group('最近日志文件', recent_logs, 'logs')}"
        f"{_render_file_group('最近报告文件', recent_reports, 'reports')}"
        "</div>"
        "</section>"
    )


def _render_dashboard(
    config: AppConfig,
    runtime_paths: RuntimePaths,
    started_at: datetime,
    process_id: int,
    last_health_check_at: datetime | None,
    listening_port: int,
    configured_port: int,
    settings_saved_at: datetime | None,
) -> str:
    rendered_at = datetime.now(timezone.utc)
    uptime_seconds = int((rendered_at - started_at).total_seconds())
    local_dashboard_url = _dashboard_url(config.host, listening_port)
    recent_logs = _recent_runtime_files(runtime_paths.log_dir, ".log", limit=6)
    recent_reports = _recent_runtime_files(runtime_paths.report_dir, ".docx", limit=6)
    live_log = _live_log_payload(runtime_paths)

    configured_port_display = str(configured_port)
    if configured_port != listening_port:
        configured_port_display = f"{configured_port}（重启后生效）"

    settings_status = "设置文件尚未更新"
    if settings_saved_at is not None:
        settings_status = f"最近保存时间：{_format_utc_timestamp(settings_saved_at)}"

    overview_items = _render_kv_rows(
        [
            ("服务状态", "运行中"),
            ("本地访问地址", local_dashboard_url),
            ("监听地址", f"{config.host}:{listening_port}"),
            ("配置端口", configured_port_display),
            ("进程 PID", str(process_id)),
            ("启动时间(UTC)", _format_utc_timestamp(started_at)),
            ("最近一次检查时间(UTC)", _format_optional_utc_timestamp(last_health_check_at)),
            ("运行秒数", str(uptime_seconds)),
        ],
        value_id_map={"最近一次检查时间(UTC)": "last-health-check-value"},
    )
    system_info_items = _render_kv_rows(_system_info_payload())
    recent_artifacts_panel = _render_recent_artifacts_panel(recent_logs, recent_reports)

    template = Template(
        """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>dify-win-agent 控制台</title>
    <style>
        :root {
            color-scheme: light;
            --sidebar-width: 320px;
            --bg: #ffffff;
            --paper: #ffffff;
            --ink: #111827;
            --muted: #4b5563;
            --line: #e5e7eb;
            --accent: #0f172a;
            --accent-soft: #f8fafc;
            --shadow: rgba(15, 23, 42, 0.06);
        }
        * { box-sizing: border-box; }
        body {
            margin: 0;
            font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
            background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
            color: var(--ink);
        }
        .sidebar-toggle {
            position: fixed;
            top: 14px;
            left: 14px;
            z-index: 60;
            border: 1px solid var(--line);
            background: rgba(255, 255, 255, 0.96);
            color: var(--ink);
            border-radius: 999px;
            padding: 8px 12px;
            font: inherit;
            font-size: 13px;
            cursor: pointer;
            box-shadow: 0 12px 28px var(--shadow);
            backdrop-filter: blur(8px);
        }
        .sidebar {
            position: fixed;
            inset: 0 auto 0 0;
            z-index: 50;
            width: var(--sidebar-width);
            padding: 58px 18px 24px;
            background: rgba(255, 255, 255, 0.98);
            border-right: 1px solid var(--line);
            box-shadow: 12px 0 32px var(--shadow);
            overflow-y: auto;
            transition: transform 0.24s ease, box-shadow 0.24s ease;
        }
        body.sidebar-collapsed .sidebar {
            transform: translateX(calc(-1 * var(--sidebar-width) - 12px));
            box-shadow: none;
        }
        .sidebar-inner {
            display: grid;
            gap: 16px;
        }
        .sidebar-card {
            background: var(--paper);
            border: 1px solid var(--line);
            border-radius: 22px;
            padding: 18px;
            box-shadow: 0 10px 26px rgba(15, 23, 42, 0.04);
        }
        .sidebar-card h1 {
            margin: 14px 0 0;
            font-size: 30px;
            line-height: 1.2;
        }
        .sidebar-card h2 {
            margin: 0 0 12px;
            font-size: 18px;
        }
        .sidebar-card p {
            margin: 12px 0 0;
            color: var(--muted);
            line-height: 1.7;
        }
        .sidebar-actions {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 4px;
        }
        .sidebar-note {
            margin-top: 14px;
            padding: 10px 12px;
            background: #f8fafc;
            border: 1px solid var(--line);
            border-radius: 14px;
            color: var(--muted);
            line-height: 1.6;
            word-break: break-word;
        }
        .main-shell {
            margin-left: calc(var(--sidebar-width) + 24px);
            padding: 58px 24px 32px;
            transition: margin-left 0.24s ease;
        }
        body.sidebar-collapsed .main-shell {
            margin-left: 0;
        }
        .toolbar-strip {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
            margin: 0 auto 12px;
            max-width: 1220px;
            padding: 12px 14px;
            background: var(--paper);
            border: 1px solid var(--line);
            border-radius: 16px;
            box-shadow: 0 10px 24px rgba(15, 23, 42, 0.04);
        }
        .toolbar-title {
            display: flex;
            align-items: center;
            gap: 10px;
            min-width: 0;
        }
        .toolbar-title h1 {
            margin: 0;
            font-size: 16px;
        }
        .toolbar-title p {
            margin: 0;
            color: var(--muted);
            font-size: 13px;
            line-height: 1.6;
        }
        .toolbar-chips {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }
        .toolbar-chip {
            display: inline-flex;
            align-items: center;
            padding: 5px 10px;
            border-radius: 999px;
            border: 1px solid var(--line);
            background: #ffffff;
            color: var(--muted);
            font-size: 12px;
            line-height: 1;
            white-space: nowrap;
        }
        .mini-button,
        .mini-link {
            border: 1px solid var(--line);
            background: #ffffff;
            color: var(--ink);
            text-decoration: none;
            border-radius: 999px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 6px 10px;
            font-size: 12px;
            line-height: 1;
            cursor: pointer;
        }
        .mini-button[disabled] { opacity: 0.7; cursor: default; }
        .badge {
            display: inline-flex;
            align-items: center;
            padding: 6px 10px;
            background: var(--accent-soft);
            border-radius: 999px;
            color: var(--accent);
            font-size: 13px;
        }
        .main-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 14px;
            max-width: 1220px;
            margin: 0 auto;
            align-items: start;
        }
        .panel {
            background: var(--paper);
            border: 1px solid var(--line);
            border-radius: 20px;
            padding: 16px 18px;
            box-shadow: 0 10px 26px rgba(15, 23, 42, 0.04);
        }
        .wide-panel { grid-column: 1 / -1; }
        .panel h2 { margin: 0 0 12px; font-size: 18px; }
        .panel h3 { margin: 0 0 10px; font-size: 15px; }
        .kv { padding: 12px 0; border-bottom: 1px solid var(--line); }
        .kv:last-child { border-bottom: none; }
        .k { display: block; font-size: 13px; color: var(--muted); }
        .v { display: block; margin-top: 4px; line-height: 1.5; word-break: break-word; }
        .api-list,
        .artifact-group ul { margin: 0; padding-left: 18px; color: var(--muted); line-height: 1.7; }
        .api-list strong { color: var(--ink); }
        .artifact-stack { display: grid; gap: 16px; }
        .artifact-group { padding-top: 4px; }
        .artifact-group + .artifact-group { border-top: 1px solid var(--line); padding-top: 16px; }
        .artifact-list {
            list-style: none;
            padding: 0;
            display: grid;
            gap: 10px;
        }
        .artifact-link {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 14px;
            padding: 12px 14px;
            border: 1px solid var(--line);
            border-radius: 14px;
            background: #ffffff;
            color: var(--ink);
            text-decoration: none;
            transition: transform 0.16s ease, box-shadow 0.16s ease, border-color 0.16s ease;
        }
        .artifact-link:hover {
            transform: translateY(-1px);
            border-color: #cbd5e1;
            box-shadow: 0 12px 24px rgba(15, 23, 42, 0.08);
        }
        .artifact-link-name {
            font-weight: 600;
            line-height: 1.5;
            word-break: break-word;
        }
        .artifact-link-meta {
            flex: 0 0 auto;
            font-size: 12px;
            color: var(--muted);
            white-space: nowrap;
        }
        .artifact-empty {
            padding: 12px 14px;
            border-radius: 14px;
            border: 1px dashed var(--line);
            background: #f8fafc;
        }
        .helper { color: var(--muted); font-size: 13px; line-height: 1.6; }
        .field { display: grid; gap: 6px; margin-top: 14px; }
        .field label { font-size: 13px; color: var(--muted); }
        .field input {
            width: 100%;
            padding: 11px 12px;
            border: 1px solid var(--line);
            border-radius: 12px;
            font: inherit;
            color: var(--ink);
            background: #fff;
        }
        .picker-input { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px; }
        .secondary-button,
        .ghost-button {
            border: 1px solid var(--line);
            background: #ffffff;
            color: var(--ink);
            border-radius: 12px;
            padding: 10px 12px;
            font: inherit;
            cursor: pointer;
            white-space: nowrap;
        }
        .primary-button {
            border: none;
            background: var(--accent);
            color: #ffffff;
            border-radius: 999px;
            padding: 10px 16px;
            font: inherit;
            cursor: pointer;
        }
        .button-row { display: flex; align-items: center; gap: 12px; margin-top: 16px; flex-wrap: wrap; }
        .status { color: var(--muted); font-size: 13px; line-height: 1.6; }
        .live-head { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 12px; margin-bottom: 12px; color: var(--muted); font-size: 13px; }
        #live-log-content {
            margin: 0;
            padding: 16px;
            min-height: 420px;
            max-height: min(64vh, 760px);
            overflow-y: auto;
            overflow-x: auto;
            background: #f8fafc;
            border: 1px solid var(--line);
            border-radius: 16px;
            white-space: pre-wrap;
            word-break: break-word;
            line-height: 1.55;
            color: var(--ink);
            font-family: Consolas, "Cascadia Mono", "Courier New", monospace;
        }
        .modal[hidden] { display: none; }
        .modal {
            position: fixed;
            inset: 0;
            z-index: 80;
            display: grid;
            place-items: center;
            padding: 18px;
            background: rgba(15, 23, 42, 0.38);
        }
        .modal-card {
            width: min(820px, 100%);
            max-height: min(82vh, 780px);
            overflow: auto;
            background: #ffffff;
            border-radius: 24px;
            border: 1px solid var(--line);
            box-shadow: 0 24px 60px rgba(15, 23, 42, 0.18);
            padding: 20px;
        }
        .modal-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
        .modal-head h3 { margin: 0; font-size: 18px; }
        .picker-current {
            margin-top: 14px;
            padding: 12px 14px;
            border-radius: 14px;
            background: #f8fafc;
            border: 1px solid var(--line);
            word-break: break-word;
        }
        .picker-actions,
        .chip-row { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 14px; }
        .picker-label { margin-top: 18px; font-size: 13px; color: var(--muted); }
        .chip-button,
        .picker-item {
            border: 1px solid var(--line);
            background: #ffffff;
            color: var(--ink);
            border-radius: 12px;
            padding: 10px 12px;
            font: inherit;
            cursor: pointer;
            text-align: left;
        }
        .folder-list {
            display: grid;
            gap: 10px;
            margin-top: 10px;
            max-height: 280px;
            overflow: auto;
        }
        @media (max-width: 960px) {
            .main-shell {
                margin-left: 0;
                padding: 58px 16px 24px;
            }
            .main-grid { grid-template-columns: 1fr; }
            .sidebar { width: min(88vw, var(--sidebar-width)); }
            body.sidebar-collapsed .sidebar {
                transform: translateX(calc(-100% - 12px));
            }
            .artifact-link {
                align-items: flex-start;
                flex-direction: column;
            }
            .artifact-link-meta {
                white-space: normal;
            }
        }
        @media (max-width: 860px) {
            .toolbar-strip {
                display: grid;
                justify-content: stretch;
            }
            .toolbar-title {
                display: block;
            }
            .toolbar-title p {
                margin-top: 4px;
            }
            .picker-input { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
    <button id="sidebar-toggle" class="sidebar-toggle" type="button" aria-controls="dashboard-sidebar" aria-expanded="true">隐藏侧栏</button>
    <aside id="dashboard-sidebar" class="sidebar">
        <div class="sidebar-inner">
            <section class="sidebar-card">
                <span class="badge">窗口版 exe 预览布局</span>
                <h1>dify-win-agent 控制台</h1>
                <p>这个页面面向本机 exe 启动后的运维查看，集中展示服务状态、运行目录、接口入口和最近产出的日志与报告。页面会持续刷新状态与日志，不影响现有 Dify 调用链。</p>
            </section>
            <section class="sidebar-card">
                <h2>快捷入口</h2>
                <div class="sidebar-actions">
                    <button id="health-check-button" class="mini-button" type="button">健康检查</button>
                    <a class="mini-link" href="/docs" target="_blank" rel="noreferrer">Swagger</a>
                    <a class="mini-link" href="/openapi.json" target="_blank" rel="noreferrer">OpenAPI</a>
                </div>
                <div class="sidebar-note">本地访问建议：$local_dashboard_url</div>
            </section>
            <section class="sidebar-card">
                <h2>接口说明</h2>
                <ul class="api-list">
                    <li><strong>GET /health</strong>：健康检查，返回进程与运行时信息。</li>
                    <li><strong>POST /api/v1/execute</strong>：执行命令任务，保持现有 Dify 调用协议不变。</li>
                    <li><strong>GET /api/v1/reports/{task_id}</strong>：下载 docx 执行报告。</li>
                </ul>
            </section>
            <section class="sidebar-card">
                <h2>本机信息</h2>
                $system_info_items
            </section>
        </div>
    </aside>
    <main class="main-shell">
        <header class="toolbar-strip">
            <div class="toolbar-title">
                <h1>控制台总览</h1>
                <p>主区域只保留四个核心板块，侧栏负责系统信息和接口入口。</p>
            </div>
            <div class="toolbar-chips">
                <span class="toolbar-chip">运行概况</span>
                <span class="toolbar-chip">运行设置</span>
                <span class="toolbar-chip">最近产物</span>
                <span class="toolbar-chip">控制台实时日志</span>
            </div>
        </header>
        <section class="main-grid">
                <section class="panel">
                    <h2>运行概况</h2>
                    $overview_items
                </section>
                <section class="panel">
                    <h2>运行设置</h2>
                    <p class="helper">端口可自行设定，但修改后需要重启程序才会切换监听端口。日志目录和报告目录可以通过目录选择框完成，不需要手工输入路径。</p>
                    <form id="settings-form">
                        <div class="field">
                            <label for="port">端口</label>
                            <input id="port" name="port" type="number" min="1" max="65535" value="$configured_port" />
                        </div>
                        <div class="field">
                            <label for="log_dir">日志目录</label>
                            <div class="picker-input">
                                <input id="log_dir" name="log_dir" type="text" value="$log_dir" readonly />
                                <button class="ghost-button" type="button" data-picker-target="log_dir">选择文件夹</button>
                            </div>
                        </div>
                        <div class="field">
                            <label for="report_dir">报告目录</label>
                            <div class="picker-input">
                                <input id="report_dir" name="report_dir" type="text" value="$report_dir" readonly />
                                <button class="ghost-button" type="button" data-picker-target="report_dir">选择文件夹</button>
                            </div>
                        </div>
                        <div class="button-row">
                            <button class="primary-button" type="submit">保存设置</button>
                            <span id="settings-status" class="status">$settings_status</span>
                        </div>
                    </form>
                </section>
            
            $recent_artifacts_panel
            <section class="panel wide-panel">
                <h2>控制台实时日志</h2>
                <div class="live-head">
                    <span>当前文件：<strong id="live-log-file">$live_log_file</strong></span>
                    <span>更新时间：<strong id="live-log-updated">$live_log_updated</strong></span>
                </div>
                <pre id="live-log-content">$live_log_content</pre>
            </section>
        </section>
    </main>
    <div id="picker-modal" class="modal" hidden>
        <div class="modal-card">
            <div class="modal-head">
                <h3>选择文件夹</h3>
                <button id="picker-close" class="secondary-button" type="button">关闭</button>
            </div>
            <div id="picker-current" class="picker-current"></div>
            <div class="picker-actions">
                <button id="picker-up" class="secondary-button" type="button">上一级</button>
                <button id="picker-select" class="primary-button" type="button">选择当前文件夹</button>
            </div>
            <div class="picker-label">常用位置</div>
            <div id="picker-favorites" class="chip-row"></div>
            <div class="picker-label">磁盘</div>
            <div id="picker-drives" class="chip-row"></div>
            <div class="picker-label">子文件夹</div>
            <div id="picker-folders" class="folder-list"></div>
            <div id="picker-status" class="status"></div>
        </div>
    </div>
    <script>
        const layoutRoot = document.body;
        const sidebarToggle = document.getElementById("sidebar-toggle");
        const healthCheckButton = document.getElementById("health-check-button");
        const lastHealthCheckValue = document.getElementById("last-health-check-value");
        const settingsForm = document.getElementById("settings-form");
        const settingsStatus = document.getElementById("settings-status");
        const liveLogFile = document.getElementById("live-log-file");
        const liveLogUpdated = document.getElementById("live-log-updated");
        const liveLogContent = document.getElementById("live-log-content");
        const pickerModal = document.getElementById("picker-modal");
        const pickerCurrent = document.getElementById("picker-current");
        const pickerFavorites = document.getElementById("picker-favorites");
        const pickerDrives = document.getElementById("picker-drives");
        const pickerFolders = document.getElementById("picker-folders");
        const pickerStatus = document.getElementById("picker-status");
        const pickerUp = document.getElementById("picker-up");
        const pickerSelect = document.getElementById("picker-select");
        const pickerClose = document.getElementById("picker-close");
        const pickerState = { targetId: null, currentPath: "", parentPath: null };
        function setSidebarCollapsed(collapsed) {
            layoutRoot.classList.toggle("sidebar-collapsed", collapsed);
            sidebarToggle.textContent = collapsed ? "展开侧栏" : "隐藏侧栏";
            sidebarToggle.setAttribute("aria-expanded", String(!collapsed));
            try {
                window.localStorage.setItem("dashboard-sidebar-collapsed", collapsed ? "1" : "0");
            } catch (error) {
                // ignore persistence failures
            }
        }
        function setStatus(text) {
            settingsStatus.textContent = text;
        }
        async function triggerHealthCheck() {
            const originalText = healthCheckButton.textContent;
            healthCheckButton.disabled = true;
            healthCheckButton.textContent = "检查中";
            try {
                const response = await fetch("/health", { cache: "no-store" });
                const payload = await response.json();
                if (!response.ok) {
                    throw new Error(payload.detail || "健康检查失败");
                }
                lastHealthCheckValue.textContent = payload.checked_at_utc || "未知";
                setStatus("健康检查已完成");
            } catch (error) {
                setStatus(error.message || "健康检查失败");
            } finally {
                healthCheckButton.disabled = false;
                healthCheckButton.textContent = originalText;
            }
        }
        async function refreshLiveLog() {
            const response = await fetch("/api/v1/runtime/log-tail", { cache: "no-store" });
            if (!response.ok) {
                return;
            }
            const payload = await response.json();
            const shouldStickToBottom = liveLogContent.scrollTop + liveLogContent.clientHeight >= liveLogContent.scrollHeight - 24;
            liveLogFile.textContent = payload.file_name || "暂无日志文件";
            liveLogUpdated.textContent = payload.updated_at_utc || "暂无更新";
            liveLogContent.textContent = payload.content || "暂无实时日志。";
            if (shouldStickToBottom) {
                liveLogContent.scrollTop = liveLogContent.scrollHeight;
            }
        }
        function renderChipButtons(container, items, labelKey) {
            container.innerHTML = "";
            for (const item of items) {
                const button = document.createElement("button");
                button.type = "button";
                button.className = "chip-button";
                button.textContent = item[labelKey];
                button.addEventListener("click", () => loadDirectory(item.path));
                container.appendChild(button);
            }
        }
        function renderFolderButtons(children) {
            pickerFolders.innerHTML = "";
            for (const item of children) {
                const button = document.createElement("button");
                button.type = "button";
                button.className = "picker-item";
                button.textContent = item.name;
                button.title = item.path;
                button.addEventListener("click", () => loadDirectory(item.path));
                pickerFolders.appendChild(button);
            }
        }
        async function loadDirectory(path) {
            const url = new URL("/api/v1/runtime/directories", window.location.origin);
            if (path) {
                url.searchParams.set("path", path);
            }
            pickerStatus.textContent = "正在读取文件夹...";
            const response = await fetch(url, { cache: "no-store" });
            const payload = await response.json();
            if (!response.ok) {
                pickerStatus.textContent = payload.detail || "读取目录失败";
                return;
            }
            pickerState.currentPath = payload.current_path;
            pickerState.parentPath = payload.parent_path;
            pickerCurrent.textContent = payload.current_path;
            pickerUp.disabled = !payload.parent_path;
            renderChipButtons(pickerFavorites, payload.favorites, "label");
            renderChipButtons(pickerDrives, payload.drives.map(pathValue => ({ label: pathValue, path: pathValue })), "label");
            renderFolderButtons(payload.children);
            pickerStatus.textContent = payload.children.length ? "点击子文件夹继续进入，或直接选择当前文件夹。" : "当前目录下暂无可进入的子文件夹。";
        }
        function openPicker(targetId) {
            pickerState.targetId = targetId;
            pickerModal.hidden = false;
            loadDirectory(document.getElementById(targetId).value);
        }
        function closePicker() {
            pickerModal.hidden = true;
        }
        healthCheckButton.addEventListener("click", triggerHealthCheck);
        settingsForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            setStatus("正在保存设置...");
            const payload = {
                port: Number(document.getElementById("port").value),
                log_dir: document.getElementById("log_dir").value,
                report_dir: document.getElementById("report_dir").value,
            };
            const response = await fetch("/api/v1/settings", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            const result = await response.json();
            if (!response.ok) {
                setStatus(result.detail || "保存失败");
                return;
            }
            setStatus(result.message);
            document.getElementById("log_dir").value = result.log_dir;
            document.getElementById("report_dir").value = result.report_dir;
            window.setTimeout(() => window.location.reload(), 600);
        });
        for (const button of document.querySelectorAll("[data-picker-target]")) {
            button.addEventListener("click", () => openPicker(button.dataset.pickerTarget));
        }
        pickerClose.addEventListener("click", closePicker);
        pickerUp.addEventListener("click", () => {
            if (pickerState.parentPath) {
                loadDirectory(pickerState.parentPath);
            }
        });
        pickerSelect.addEventListener("click", () => {
            if (!pickerState.targetId) {
                return;
            }
            document.getElementById(pickerState.targetId).value = pickerState.currentPath;
            closePicker();
        });
        pickerModal.addEventListener("click", (event) => {
            if (event.target === pickerModal) {
                closePicker();
            }
        });
        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && !pickerModal.hidden) {
                closePicker();
            }
        });
        sidebarToggle.addEventListener("click", () => {
            setSidebarCollapsed(!layoutRoot.classList.contains("sidebar-collapsed"));
        });
        let sidebarCollapsed = window.matchMedia("(max-width: 960px)").matches;
        try {
            const savedSidebarState = window.localStorage.getItem("dashboard-sidebar-collapsed");
            if (savedSidebarState !== null) {
                sidebarCollapsed = savedSidebarState === "1";
            }
        } catch (error) {
            // ignore persistence failures
        }
        setSidebarCollapsed(sidebarCollapsed);
        refreshLiveLog();
        window.setInterval(refreshLiveLog, 2000);
    </script>
</body>
</html>
"""
    )

    return template.substitute(
        local_dashboard_url=html.escape(local_dashboard_url),
        overview_items=overview_items,
        system_info_items=system_info_items,
        configured_port=html.escape(str(configured_port), quote=True),
        log_dir=html.escape(str(runtime_paths.log_dir), quote=True),
        report_dir=html.escape(str(runtime_paths.report_dir), quote=True),
        settings_status=html.escape(settings_status),
        recent_artifacts_panel=recent_artifacts_panel,
        live_log_file=html.escape(live_log["file_name"] or "暂无日志文件"),
        live_log_updated=html.escape(live_log["updated_at_utc"] or "暂无更新"),
        live_log_content=html.escape(live_log["content"] or "暂无实时日志。"),
    )


def create_app(config: AppConfig, runtime_paths: RuntimePaths) -> FastAPI:
    app = FastAPI(title="dify-win-agent")
    app.state.config = config
    app.state.runtime_paths = runtime_paths
    app.state.started_at = datetime.now(timezone.utc)
    app.state.process_id = os.getpid()
    app.state.last_health_check_at = None
    app.state.listening_port = config.port
    app.state.configured_port = config.port
    app.state.settings_saved_at = None

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> HTMLResponse:
        return HTMLResponse(
            content=_render_dashboard(
                config=config,
                runtime_paths=app.state.runtime_paths,
                started_at=app.state.started_at,
                process_id=app.state.process_id,
                last_health_check_at=app.state.last_health_check_at,
                listening_port=app.state.listening_port,
                configured_port=app.state.configured_port,
                settings_saved_at=app.state.settings_saved_at,
            ),
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )

    @app.get("/health")
    def health() -> JSONResponse:
        checked_at = datetime.now(timezone.utc)
        app.state.last_health_check_at = checked_at
        return JSONResponse(
            content={
                "status": "ok",
                "service": "dify-win-agent",
                "process_id": app.state.process_id,
                "started_at_utc": _format_utc_timestamp(app.state.started_at),
                "checked_at_utc": _format_utc_timestamp(checked_at),
                "uptime_seconds": int((checked_at - app.state.started_at).total_seconds()),
            },
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )

    @app.get("/api/v1/runtime/log-tail")
    def live_log_tail() -> JSONResponse:
        return JSONResponse(
            content=_live_log_payload(app.state.runtime_paths),
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )

    @app.get("/api/v1/runtime/directories")
    def browse_directories(path: str | None = None) -> JSONResponse:
        return JSONResponse(
            content=_directory_browser_payload(path, app.state.runtime_paths.root_dir),
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )

    @app.get("/api/v1/runtime/artifacts/{artifact_kind}/{file_name:path}")
    def download_runtime_artifact(artifact_kind: str, file_name: str) -> FileResponse:
        artifact_path = _resolve_runtime_artifact_path(
            app.state.runtime_paths,
            artifact_kind,
            file_name,
        )
        media_type = "text/plain; charset=utf-8"
        if artifact_kind == "reports":
            media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

        return FileResponse(
            path=artifact_path,
            filename=artifact_path.name,
            media_type=media_type,
        )

    @app.post("/api/v1/settings")
    def update_settings(request: DashboardSettingsRequest) -> dict[str, object]:
        root_dir = app.state.runtime_paths.root_dir
        log_dir = _resolve_user_path(request.log_dir, root_dir)
        report_dir = _resolve_user_path(request.report_dir, root_dir)

        save_runtime_settings(
            app.state.config.settings_path,
            port=request.port,
            log_dir=log_dir,
            report_dir=report_dir,
        )

        app.state.runtime_paths = ensure_runtime_directories(root_dir, log_dir, report_dir)
        app.state.configured_port = request.port
        app.state.settings_saved_at = datetime.now(timezone.utc)

        return {
            "message": "设置已保存。目录已立即生效；端口修改需重启程序后生效。",
            "configured_port": request.port,
            "listening_port": app.state.listening_port,
            "log_dir": str(app.state.runtime_paths.log_dir),
            "report_dir": str(app.state.runtime_paths.report_dir),
            "saved_at_utc": _format_utc_timestamp(app.state.settings_saved_at),
        }

    @app.post("/api/v1/execute")
    def execute(request: ExecuteRequest) -> dict[str, object]:
        try:
            task_result = execute_task(
                task_id=request.task_id,
                target_host=request.target_host,
                commands=request.commands,
                runtime_paths=app.state.runtime_paths,
                timeout_seconds=config.command_timeout_seconds,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    "执行失败：Windows agent 处理命令时发生内部错误。"
                    f"请检查 {app.state.runtime_paths.log_dir} 目录日志并重试。错误信息：{exc}"
                ),
            ) from exc

        execution_status, execution_message = _summarize_execution(task_result.command_results)
        return {
            "status": execution_status,
            "message": execution_message,
            "task_id": task_result.task_id,
            "target_host": task_result.target_host,
            "report_download_url": f"/api/v1/reports/{task_result.task_id}",
            "command_results": [
                {
                    "command_id": item.command_id,
                    "shell": item.shell,
                    "return_code": item.return_code,
                    "stdout": item.stdout,
                    "stderr": item.stderr,
                }
                for item in task_result.command_results
            ],
        }

    @app.get("/api/v1/reports/{task_id}")
    def download_report(task_id: str) -> FileResponse:
        report_path = find_latest_artifact_path(
            app.state.runtime_paths.report_dir,
            task_id,
            "报告",
            ".docx",
        )
        if report_path is None or not report_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="报告不存在，请先执行任务。",
            )

        return FileResponse(
            report_path,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=report_path.name,
        )

    return app
