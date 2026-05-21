import unittest
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
from urllib.parse import quote

from fastapi.testclient import TestClient


class ServerTests(unittest.TestCase):
    def test_dashboard_returns_runtime_summary(self) -> None:
        from dify_win_agent.config import AppConfig
        from dify_win_agent.logging_utils import create_task_logger
        from dify_win_agent.runtime_paths import ensure_runtime_directories
        from dify_win_agent.server import create_app

        with TemporaryDirectory() as temp_dir:
            runtime_paths = ensure_runtime_directories(Path(temp_dir))
            logger, log_path = create_task_logger("task-dashboard", runtime_paths.log_dir)
            logger.info("dashboard-link")
            report_path = runtime_paths.report_dir / "20260521-000000-报告-dashboard.docx"
            report_path.write_bytes(b"dashboard-report")
            app = create_app(
                AppConfig(
                    host="0.0.0.0",
                    port=8765,
                    command_timeout_seconds=300,
                    log_dir=runtime_paths.log_dir,
                    report_dir=runtime_paths.report_dir,
                    settings_path=runtime_paths.root_dir / "settings.json",
                ),
                runtime_paths,
            )

            response = TestClient(app).get("/")

            self.assertEqual(200, response.status_code)
            self.assertIn("text/html", response.headers["content-type"])
            self.assertIn("dify-win-agent 控制台", response.text)
            self.assertIn("隐藏侧栏", response.text)
            self.assertIn("控制台总览", response.text)
            self.assertIn("http://127.0.0.1:8765/", response.text)
            self.assertIn("/health", response.text)
            self.assertIn("/api/v1/execute", response.text)
            self.assertIn("最近一次检查时间(UTC)", response.text)
            self.assertIn("尚未收到健康检查", response.text)
            self.assertIn("本机信息", response.text)
            self.assertIn("运行设置", response.text)
            self.assertIn("选择文件夹", response.text)
            self.assertIn("最近产物", response.text)
            self.assertIn("控制台实时日志", response.text)
            self.assertIn(str(runtime_paths.log_dir), response.text)
            self.assertIn(str(runtime_paths.report_dir), response.text)
            self.assertIn(
                f"/api/v1/runtime/artifacts/logs/{quote(log_path.name)}",
                response.text,
            )
            self.assertIn(
                f"/api/v1/runtime/artifacts/reports/{quote(report_path.name)}",
                response.text,
            )
            self.assertIn("点击下载", response.text)

    def test_dashboard_shows_last_health_check_time_after_ping(self) -> None:
        from dify_win_agent.config import AppConfig
        from dify_win_agent.runtime_paths import ensure_runtime_directories
        from dify_win_agent.server import create_app

        with TemporaryDirectory() as temp_dir:
            runtime_paths = ensure_runtime_directories(Path(temp_dir))
            app = create_app(
                AppConfig(
                    host="0.0.0.0",
                    port=8765,
                    command_timeout_seconds=300,
                    log_dir=runtime_paths.log_dir,
                    report_dir=runtime_paths.report_dir,
                    settings_path=runtime_paths.root_dir / "settings.json",
                ),
                runtime_paths,
            )

            client = TestClient(app)
            health_payload = client.get("/health").json()
            response = client.get("/")

            self.assertEqual(200, response.status_code)
            self.assertIn(health_payload["checked_at_utc"], response.text)

    def test_execute_returns_result_and_download_url(self) -> None:
        from dify_win_agent.config import AppConfig
        from dify_win_agent.runtime_paths import ensure_runtime_directories
        from dify_win_agent.server import create_app

        with TemporaryDirectory() as temp_dir:
            runtime_paths = ensure_runtime_directories(Path(temp_dir))
            app = create_app(
                AppConfig(
                    host="0.0.0.0",
                    port=8765,
                    command_timeout_seconds=300,
                    log_dir=runtime_paths.log_dir,
                    report_dir=runtime_paths.report_dir,
                    settings_path=runtime_paths.root_dir / "settings.json",
                ),
                runtime_paths,
            )

            command = f'"{sys.executable}" -c "print(\'hello-server\')"'
            response = TestClient(app).post(
                "/api/v1/execute",
                json={
                    "task_id": "task-001",
                    "target_host": "10.0.0.5",
                    "commands": [{"id": "cmd-001", "shell": command}],
                },
            )

            payload = response.json()
            self.assertEqual(200, response.status_code)
            self.assertEqual("task-001", payload["task_id"])
            self.assertEqual("succeeded", payload["status"])
            self.assertEqual("命令执行完成。", payload["message"])
            self.assertIn("hello-server", payload["command_results"][0]["stdout"])
            self.assertEqual(
                "/api/v1/reports/task-001",
                payload["report_download_url"],
            )

    def test_execute_returns_failed_status_when_command_fails(self) -> None:
        from dify_win_agent.config import AppConfig
        from dify_win_agent.runtime_paths import ensure_runtime_directories
        from dify_win_agent.server import create_app

        with TemporaryDirectory() as temp_dir:
            runtime_paths = ensure_runtime_directories(Path(temp_dir))
            app = create_app(
                AppConfig(
                    host="0.0.0.0",
                    port=8765,
                    command_timeout_seconds=300,
                    log_dir=runtime_paths.log_dir,
                    report_dir=runtime_paths.report_dir,
                    settings_path=runtime_paths.root_dir / "settings.json",
                ),
                runtime_paths,
            )

            response = TestClient(app).post(
                "/api/v1/execute",
                json={
                    "task_id": "task-failed",
                    "target_host": "10.0.0.7",
                    "commands": [{"id": "cmd-001", "shell": "cmd /c exit 3"}],
                },
            )

            payload = response.json()
            self.assertEqual(200, response.status_code)
            self.assertEqual("failed", payload["status"])
            self.assertIn("命令执行失败", payload["message"])
            self.assertEqual(3, payload["command_results"][0]["return_code"])

    def test_execute_returns_partially_failed_status_when_results_are_mixed(self) -> None:
        from dify_win_agent.config import AppConfig
        from dify_win_agent.runtime_paths import ensure_runtime_directories
        from dify_win_agent.server import create_app

        with TemporaryDirectory() as temp_dir:
            runtime_paths = ensure_runtime_directories(Path(temp_dir))
            app = create_app(
                AppConfig(
                    host="0.0.0.0",
                    port=8765,
                    command_timeout_seconds=300,
                    log_dir=runtime_paths.log_dir,
                    report_dir=runtime_paths.report_dir,
                    settings_path=runtime_paths.root_dir / "settings.json",
                ),
                runtime_paths,
            )

            response = TestClient(app).post(
                "/api/v1/execute",
                json={
                    "task_id": "task-partial",
                    "target_host": "10.0.0.8",
                    "commands": [
                        {"id": "cmd-001", "shell": "whoami"},
                        {"id": "cmd-002", "shell": "cmd /c exit 5"},
                    ],
                },
            )

            payload = response.json()
            self.assertEqual(200, response.status_code)
            self.assertEqual("partially_failed", payload["status"])
            self.assertIn("部分命令执行失败", payload["message"])
            self.assertEqual(0, payload["command_results"][0]["return_code"])
            self.assertEqual(5, payload["command_results"][1]["return_code"])

    def test_report_download_returns_docx_file(self) -> None:
        from dify_win_agent.config import AppConfig
        from dify_win_agent.runtime_paths import ensure_runtime_directories
        from dify_win_agent.server import create_app

        with TemporaryDirectory() as temp_dir:
            runtime_paths = ensure_runtime_directories(Path(temp_dir))
            app = create_app(
                AppConfig(
                    host="0.0.0.0",
                    port=8765,
                    command_timeout_seconds=300,
                    log_dir=runtime_paths.log_dir,
                    report_dir=runtime_paths.report_dir,
                    settings_path=runtime_paths.root_dir / "settings.json",
                ),
                runtime_paths,
            )

            command = f'"{sys.executable}" -c "print(\'hello-download\')"'
            client = TestClient(app)
            client.post(
                "/api/v1/execute",
                json={
                    "task_id": "task-002",
                    "target_host": "10.0.0.6",
                    "commands": [{"id": "cmd-001", "shell": command}],
                },
            )

            response = client.get("/api/v1/reports/task-002")

            self.assertEqual(200, response.status_code)
            self.assertEqual(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                response.headers["content-type"],
            )

    def test_health_endpoint_returns_ok(self) -> None:
        from dify_win_agent.config import AppConfig
        from dify_win_agent.runtime_paths import RuntimePaths
        from dify_win_agent.server import create_app

        app = create_app(
            AppConfig(
                host="0.0.0.0",
                port=8765,
                command_timeout_seconds=300,
                log_dir=Path("."),
                report_dir=Path("."),
                settings_path=Path("settings.json"),
            ),
            RuntimePaths(root_dir=None, log_dir=None, report_dir=None),
        )

        response = TestClient(app).get("/health")

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("ok", payload["status"])
        self.assertEqual("dify-win-agent", payload["service"])
        self.assertEqual(os.getpid(), payload["process_id"])
        self.assertIn("started_at_utc", payload)
        self.assertIn("checked_at_utc", payload)
        self.assertIn("uptime_seconds", payload)
        self.assertGreaterEqual(payload["uptime_seconds"], 0)
        self.assertEqual(
            "no-store, no-cache, must-revalidate, max-age=0",
            response.headers["cache-control"],
        )
        self.assertEqual("no-cache", response.headers["pragma"])
        self.assertEqual("0", response.headers["expires"])

    def test_live_log_tail_returns_latest_log_content(self) -> None:
        from dify_win_agent.config import AppConfig
        from dify_win_agent.logging_utils import create_task_logger
        from dify_win_agent.runtime_paths import ensure_runtime_directories
        from dify_win_agent.server import create_app

        with TemporaryDirectory() as temp_dir:
            runtime_paths = ensure_runtime_directories(Path(temp_dir))
            logger, _ = create_task_logger("task-live", runtime_paths.log_dir)
            logger.info("第一行")
            logger.info("第二行")

            app = create_app(
                AppConfig(
                    host="0.0.0.0",
                    port=8765,
                    command_timeout_seconds=300,
                    log_dir=runtime_paths.log_dir,
                    report_dir=runtime_paths.report_dir,
                    settings_path=runtime_paths.root_dir / "settings.json",
                ),
                runtime_paths,
            )

            response = TestClient(app).get("/api/v1/runtime/log-tail")

            self.assertEqual(200, response.status_code)
            payload = response.json()
            self.assertIn("日志", payload["file_name"])
            self.assertIn("第一行", payload["content"])
            self.assertIn("第二行", payload["content"])

    def test_runtime_artifact_download_returns_log_file(self) -> None:
        from dify_win_agent.config import AppConfig
        from dify_win_agent.logging_utils import create_task_logger
        from dify_win_agent.runtime_paths import ensure_runtime_directories
        from dify_win_agent.server import create_app

        with TemporaryDirectory() as temp_dir:
            runtime_paths = ensure_runtime_directories(Path(temp_dir))
            logger, log_path = create_task_logger("task-artifact", runtime_paths.log_dir)
            logger.info("artifact-download")

            app = create_app(
                AppConfig(
                    host="0.0.0.0",
                    port=8765,
                    command_timeout_seconds=300,
                    log_dir=runtime_paths.log_dir,
                    report_dir=runtime_paths.report_dir,
                    settings_path=runtime_paths.root_dir / "settings.json",
                ),
                runtime_paths,
            )

            response = TestClient(app).get(
                f"/api/v1/runtime/artifacts/logs/{quote(log_path.name)}"
            )

            self.assertEqual(200, response.status_code)
            self.assertEqual("text/plain; charset=utf-8", response.headers["content-type"])
            self.assertIn("filename*=utf-8''", response.headers["content-disposition"])
            self.assertIn(quote(log_path.name), response.headers["content-disposition"])
            self.assertIn("artifact-download", response.text)

    def test_directory_browser_lists_child_directories(self) -> None:
        from dify_win_agent.config import AppConfig
        from dify_win_agent.runtime_paths import ensure_runtime_directories
        from dify_win_agent.server import create_app

        with TemporaryDirectory() as temp_dir:
            runtime_paths = ensure_runtime_directories(Path(temp_dir))
            child_dir = runtime_paths.root_dir / "browse-me"
            child_dir.mkdir()

            app = create_app(
                AppConfig(
                    host="0.0.0.0",
                    port=8765,
                    command_timeout_seconds=300,
                    log_dir=runtime_paths.log_dir,
                    report_dir=runtime_paths.report_dir,
                    settings_path=runtime_paths.root_dir / "settings.json",
                ),
                runtime_paths,
            )

            response = TestClient(app).get(
                "/api/v1/runtime/directories",
                params={"path": str(runtime_paths.root_dir)},
            )

            self.assertEqual(200, response.status_code)
            payload = response.json()
            self.assertEqual(str(runtime_paths.root_dir.resolve()), payload["current_path"])
            self.assertTrue(any(item["name"] == "browse-me" for item in payload["children"]))

    def test_settings_endpoint_updates_runtime_directories_and_persists_port(self) -> None:
        from dify_win_agent.config import AppConfig
        from dify_win_agent.runtime_paths import ensure_runtime_directories
        from dify_win_agent.server import create_app

        with TemporaryDirectory() as temp_dir:
            runtime_paths = ensure_runtime_directories(Path(temp_dir))
            settings_path = runtime_paths.root_dir / "settings.json"
            app = create_app(
                AppConfig(
                    host="0.0.0.0",
                    port=8765,
                    command_timeout_seconds=300,
                    log_dir=runtime_paths.log_dir,
                    report_dir=runtime_paths.report_dir,
                    settings_path=settings_path,
                ),
                runtime_paths,
            )

            response = TestClient(app).post(
                "/api/v1/settings",
                json={
                    "port": 9001,
                    "log_dir": "custom-logs",
                    "report_dir": "custom-reports",
                },
            )

            self.assertEqual(200, response.status_code)
            payload = response.json()
            self.assertEqual(9001, payload["configured_port"])
            self.assertEqual(8765, payload["listening_port"])
            self.assertTrue((runtime_paths.root_dir / "custom-logs").is_dir())
            self.assertTrue((runtime_paths.root_dir / "custom-reports").is_dir())
            self.assertTrue(settings_path.is_file())
            self.assertIn("端口修改需重启程序后生效", payload["message"])


if __name__ == "__main__":
    unittest.main()