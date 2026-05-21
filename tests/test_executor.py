from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest


class ExecutorTests(unittest.TestCase):
    def test_execute_task_runs_commands_and_creates_report(self) -> None:
        from dify_win_agent.executor import execute_task
        from dify_win_agent.models import CommandSpec
        from dify_win_agent.runtime_paths import ensure_runtime_directories

        with TemporaryDirectory() as temp_dir:
            runtime_paths = ensure_runtime_directories(Path(temp_dir))
            command = f'"{sys.executable}" -c "print(\'hello-agent\')"'

            result = execute_task(
                task_id="task-001",
                target_host="10.0.0.5",
                commands=[CommandSpec(id="cmd-001", shell=command)],
                runtime_paths=runtime_paths,
                timeout_seconds=30,
            )

            self.assertEqual("task-001", result.task_id)
            self.assertTrue(result.report_path.is_file())
            self.assertTrue(result.log_path.is_file())
            self.assertEqual(1, len(result.command_results))
            self.assertEqual(0, result.command_results[0].return_code)
            self.assertIn("hello-agent", result.command_results[0].stdout)

    def test_execute_task_returns_chinese_error_when_command_times_out(self) -> None:
        from dify_win_agent.executor import execute_task
        from dify_win_agent.models import CommandSpec
        from dify_win_agent.runtime_paths import ensure_runtime_directories

        with TemporaryDirectory() as temp_dir:
            runtime_paths = ensure_runtime_directories(Path(temp_dir))
            command = f'"{sys.executable}" -c "import time; time.sleep(2)"'

            result = execute_task(
                task_id="task-timeout",
                target_host="10.0.0.8",
                commands=[CommandSpec(id="cmd-timeout", shell=command)],
                runtime_paths=runtime_paths,
                timeout_seconds=1,
            )

            self.assertEqual(1, len(result.command_results))
            self.assertEqual(-1, result.command_results[0].return_code)
            self.assertIn("命令执行超时", result.command_results[0].stderr)
            self.assertTrue(result.report_path.is_file())


if __name__ == "__main__":
    unittest.main()