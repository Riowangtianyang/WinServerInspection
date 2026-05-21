from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class RuntimePaths:
    root_dir: Path
    log_dir: Path
    report_dir: Path


def ensure_runtime_directories(
    root_dir: Path,
    log_dir: Path | None = None,
    report_dir: Path | None = None,
) -> RuntimePaths:
    resolved_root = root_dir.resolve()
    resolved_log_dir = (log_dir or resolved_root / "doc").resolve()
    resolved_report_dir = (report_dir or resolved_root / "document").resolve()

    resolved_log_dir.mkdir(parents=True, exist_ok=True)
    resolved_report_dir.mkdir(parents=True, exist_ok=True)

    return RuntimePaths(
        root_dir=resolved_root,
        log_dir=resolved_log_dir,
        report_dir=resolved_report_dir,
    )


def _safe_task_id(task_id: str) -> str:
    safe = "".join(
        character if character.isalnum() or character in {"-", "_", "."} else "_"
        for character in task_id
    )
    return safe or "task"


def build_artifact_path(
    directory: Path,
    task_id: str,
    label: str,
    suffix: str,
    created_at: datetime,
) -> Path:
    file_name = f"{created_at:%Y%m%d-%H%M%S}-{label}-{_safe_task_id(task_id)}{suffix}"
    return directory / file_name


def find_latest_artifact_path(
    directory: Path,
    task_id: str,
    label: str,
    suffix: str,
) -> Path | None:
    if not directory.is_dir():
        return None

    safe_task_id = _safe_task_id(task_id)
    candidates = [
        item
        for item in directory.glob(f"*-{label}-{safe_task_id}{suffix}")
        if item.is_file()
    ]

    for legacy_name in (f"{task_id}{suffix}", f"{safe_task_id}{suffix}"):
        legacy_path = directory / legacy_name
        if legacy_path.is_file():
            candidates.append(legacy_path)

    if not candidates:
        return None

    candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return candidates[0]