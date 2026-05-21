from datetime import datetime, timezone
from pathlib import Path
import logging

from dify_win_agent.runtime_paths import build_artifact_path


class _EphemeralFileHandler(logging.Handler):
    terminator = "\n"

    def __init__(self, log_path: Path, encoding: str = "utf-8") -> None:
        super().__init__()
        self.log_path = log_path
        self.encoding = encoding

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            with self.log_path.open("a", encoding=self.encoding) as stream:
                stream.write(message + self.terminator)
        except Exception:
            self.handleError(record)


def create_task_logger(
    task_id: str,
    log_dir: Path,
    created_at: datetime | None = None,
) -> tuple[logging.Logger, Path]:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = build_artifact_path(
        log_dir,
        task_id,
        "日志",
        ".log",
        created_at or datetime.now(timezone.utc),
    )
    logger_name = f"dify_win_agent.task.{task_id}"
    logger = logging.getLogger(logger_name)

    logger.setLevel(logging.INFO)
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    file_handler = _EphemeralFileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(name)s | %(levelname)s | %(message)s")
    )
    logger.addHandler(file_handler)

    return logger, log_path