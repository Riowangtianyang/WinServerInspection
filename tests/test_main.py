import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


class MainTests(unittest.TestCase):
    def test_dashboard_url_uses_loopback_for_all_interfaces(self) -> None:
        import main

        self.assertEqual("http://127.0.0.1:8765/", main._dashboard_url("0.0.0.0", 8765))
        self.assertEqual("http://127.0.0.1:8765/", main._dashboard_url("localhost", 8765))
        self.assertEqual("http://10.0.0.5:9000/", main._dashboard_url("10.0.0.5", 9000))

    def test_should_open_dashboard_only_for_frozen_exe(self) -> None:
        import main

        with patch.object(main.sys, "frozen", True, create=True):
            with patch.dict(main.os.environ, {}, clear=True):
                self.assertFalse(main._should_open_dashboard())

            with patch.dict(
                main.os.environ,
                {"DIFY_WIN_AGENT_WINDOW_MODE": "0"},
                clear=True,
            ):
                self.assertTrue(main._should_open_dashboard())

            with patch.dict(
                main.os.environ,
                {
                    "DIFY_WIN_AGENT_WINDOW_MODE": "0",
                    "DIFY_WIN_AGENT_OPEN_BROWSER": "0",
                },
                clear=True,
            ):
                self.assertFalse(main._should_open_dashboard())

        with patch.object(main.sys, "frozen", False, create=True):
            with patch.dict(main.os.environ, {}, clear=True):
                self.assertFalse(main._should_open_dashboard())

    def test_should_use_desktop_window_only_for_frozen_exe(self) -> None:
        import main

        with patch.object(main.sys, "frozen", True, create=True):
            with patch.dict(main.os.environ, {}, clear=True):
                self.assertTrue(main._should_use_desktop_window())

            with patch.dict(
                main.os.environ,
                {"DIFY_WIN_AGENT_WINDOW_MODE": "0"},
                clear=True,
            ):
                self.assertFalse(main._should_use_desktop_window())

        with patch.object(main.sys, "frozen", False, create=True):
            with patch.dict(main.os.environ, {}, clear=True):
                self.assertFalse(main._should_use_desktop_window())

    def test_schedule_dashboard_open_starts_timer_when_enabled(self) -> None:
        import main

        timer_instance = MagicMock()
        timer_class = MagicMock(return_value=timer_instance)

        with patch.object(main, "_should_open_dashboard", return_value=True):
            with patch.object(main, "Timer", timer_class):
                main._schedule_dashboard_open("0.0.0.0", 8765)

        timer_class.assert_called_once()
        timer_instance.start.assert_called_once_with()

    def test_main_uses_desktop_window_when_enabled(self) -> None:
        import main

        config = SimpleNamespace(
            host="127.0.0.1",
            port=8876,
            log_dir=Path("log"),
            report_dir=Path("report"),
        )
        runtime_paths = SimpleNamespace(log_dir=Path("log"), report_dir=Path("report"))

        with patch.object(main, "ensure_elevated", return_value=False):
            with patch.object(main, "_application_root", return_value=Path("root")):
                with patch.object(main, "load_config", return_value=config):
                    with patch.object(main, "ensure_runtime_directories", return_value=runtime_paths):
                        with patch.object(main, "create_app", return_value="app"):
                            with patch.object(main, "_should_use_desktop_window", return_value=True):
                                with patch.object(main, "_launch_desktop_window", return_value=0) as launch_window:
                                    with patch.object(main.uvicorn, "run") as uvicorn_run:
                                        with patch.object(main, "_schedule_dashboard_open") as open_browser:
                                            self.assertEqual(0, main.main())

        launch_window.assert_called_once_with("app", "127.0.0.1", 8876)
        uvicorn_run.assert_not_called()
        open_browser.assert_not_called()


if __name__ == "__main__":
    unittest.main()