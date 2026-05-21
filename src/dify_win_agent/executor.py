from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import subprocess

from dify_win_agent.logging_utils import create_task_logger
from dify_win_agent.models import CommandSpec
from dify_win_agent.reports import CommandExecutionResult, generate_docx_report
from dify_win_agent.runtime_paths import RuntimePaths


@dataclass(frozen=True)
class TaskExecutionResult:
    task_id: str
    target_host: str
    command_results: list[CommandExecutionResult]
    report_path: Path
    log_path: Path


def _decode_output(payload: bytes) -> str:
    for encoding in ("utf-8", "gbk", "cp936"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue

    return payload.decode("utf-8", errors="replace")


def execute_task(
    task_id: str,
    target_host: str,
    commands: list[CommandSpec],
    runtime_paths: RuntimePaths,
    timeout_seconds: int,
) -> TaskExecutionResult:
    created_at = datetime.now(timezone.utc)
    logger, log_path = create_task_logger(
        task_id,
        runtime_paths.log_dir,
        created_at=created_at,
    )
    command_results: list[CommandExecutionResult] = []

    logger.info("开始执行任务 task_id=%s target_host=%s", task_id, target_host)

    for command in commands:
        logger.info("开始执行命令 command_id=%s shell=%s", command.id, command.shell)
        try:
            completed = subprocess.run(
                command.shell,
                shell=True,
                capture_output=True,
                timeout=timeout_seconds,
            )
            result = CommandExecutionResult(
                command_id=command.id,
                shell=command.shell,
                return_code=completed.returncode,
                stdout=_decode_output(completed.stdout),
                stderr=_decode_output(completed.stderr),
            )
        except subprocess.TimeoutExpired:
            result = CommandExecutionResult(
                command_id=command.id,
                shell=command.shell,
                return_code=-1,
                stdout="",
                stderr=f"命令执行超时：超过 {timeout_seconds} 秒仍未完成。",
            )
        command_results.append(result)
        logger.info(
            "命令执行完成 command_id=%s return_code=%s stdout=%s stderr=%s",
            result.command_id,
            result.return_code,
            result.stdout.strip(),
            result.stderr.strip(),
        )

    report_path = generate_docx_report(
        task_id=task_id,
        target_host=target_host,
        command_results=command_results,
        report_dir=runtime_paths.report_dir,
        created_at=created_at,
    )
    logger.info("任务执行完成 report_path=%s", report_path)

    return TaskExecutionResult(
        task_id=task_id,
        target_host=target_host,
        command_results=command_results,
        report_path=report_path,
        log_path=log_path,
    )