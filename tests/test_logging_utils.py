from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


class LoggingUtilsTests(unittest.TestCase):
    def test_create_task_logger_writes_utf8_log_file(self) -> None:
        from dify_win_agent.logging_utils import create_task_logger

        with TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir)
            logger, log_path = create_task_logger("task-001", log_dir)

            logger.info("中文日志消息")

            self.assertTrue(log_path.is_file())
            self.assertIn("日志", log_path.name)
            content = log_path.read_text(encoding="utf-8")
            self.assertIn("task-001", content)
            self.assertIn("中文日志消息", content)


if __name__ == "__main__":
    unittest.main()