from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
import json
import os


class ConfigurationError(ValueError):
    pass


DEFAULT_SETTINGS_FILENAME = "dify-win-agent.settings.json"


@dataclass(frozen=True)
class AppConfig:
    host: str
    port: int
    command_timeout_seconds: int
    log_dir: Path
    report_dir: Path
    settings_path: Path


def _resolve_path(
    value: str | os.PathLike[str] | Path | None,
    application_root: Path,
    default_path: Path,
) -> Path:
    if value in (None, ""):
        path = default_path
    else:
        path = Path(value).expanduser()

    if not path.is_absolute():
        path = application_root / path

    return path.resolve()


def _load_settings_file(settings_path: Path) -> dict[str, Any]:
    if not settings_path.is_file():
        return {}

    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigurationError(f"设置文件读取失败：{settings_path}") from exc

    if not isinstance(payload, dict):
        raise ConfigurationError(f"设置文件格式无效：{settings_path}")

    return payload


def _pick_setting(
    env: Mapping[str, str],
    settings: Mapping[str, Any],
    env_key: str,
    settings_key: str,
    default: Any,
) -> Any:
    env_value = env.get(env_key)
    if env_value not in (None, ""):
        return env_value

    settings_value = settings.get(settings_key)
    if settings_value not in (None, ""):
        return settings_value

    return default


def load_config(
    source: Mapping[str, str] | None = None,
    application_root: Path | None = None,
) -> AppConfig:
    env = dict(os.environ if source is None else source)
    root = (application_root or Path.cwd()).resolve()
    settings_path = _resolve_path(
        env.get("DIFY_WIN_AGENT_SETTINGS_PATH"),
        root,
        root / DEFAULT_SETTINGS_FILENAME,
    )
    settings = _load_settings_file(settings_path)

    host = str(_pick_setting(env, settings, "DIFY_WIN_AGENT_HOST", "host", "0.0.0.0"))
    port = int(_pick_setting(env, settings, "DIFY_WIN_AGENT_PORT", "port", "8765"))
    command_timeout_seconds = int(
        _pick_setting(
            env,
            settings,
            "DIFY_WIN_AGENT_COMMAND_TIMEOUT_SECONDS",
            "command_timeout_seconds",
            "300",
        )
    )

    if not 1 <= port <= 65535:
        raise ConfigurationError(f"端口无效：{port}")

    log_dir = _resolve_path(
        _pick_setting(env, settings, "DIFY_WIN_AGENT_LOG_DIR", "log_dir", root / "doc"),
        root,
        root / "doc",
    )
    report_dir = _resolve_path(
        _pick_setting(
            env,
            settings,
            "DIFY_WIN_AGENT_REPORT_DIR",
            "report_dir",
            root / "document",
        ),
        root,
        root / "document",
    )

    return AppConfig(
        host=host,
        port=port,
        command_timeout_seconds=command_timeout_seconds,
        log_dir=log_dir,
        report_dir=report_dir,
        settings_path=settings_path,
    )


def save_runtime_settings(
    settings_path: Path,
    *,
    port: int,
    log_dir: Path,
    report_dir: Path,
) -> None:
    payload: dict[str, Any] = {}
    if settings_path.is_file():
        try:
            payload = _load_settings_file(settings_path)
        except ConfigurationError:
            payload = {}

    payload.update(
        {
            "port": port,
            "log_dir": str(log_dir),
            "report_dir": str(report_dir),
        }
    )

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )