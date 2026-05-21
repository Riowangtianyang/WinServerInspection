from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch


class _EventHook:
    def __init__(self) -> None:
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


class DesktopWindowTests(unittest.TestCase):
    def test_run_dashboard_window_starts_server_and_webview(self) -> None:
        from dify_win_agent import desktop_window

        fake_server = MagicMock()
        fake_server.started = True
        fake_thread = MagicMock()
        fake_thread.is_alive.return_value = False
        fake_window = SimpleNamespace(events=SimpleNamespace(closed=_EventHook()))
        fake_webview = MagicMock()
        fake_webview.create_window.return_value = fake_window

        with patch.object(desktop_window, "_load_webview_module", return_value=fake_webview):
            with patch.object(desktop_window, "_port_available", return_value=True):
                with patch.object(desktop_window, "_create_server", return_value=fake_server):
                    with patch.object(desktop_window, "_start_server_thread", return_value=fake_thread):
                        with patch.object(desktop_window, "_wait_for_server_started") as wait_for_server_started:
                            with patch.object(desktop_window, "_wait_for_url") as wait_for_url:
                                with patch.object(desktop_window, "_stop_server") as stop_server:
                                    result = desktop_window.run_dashboard_window(
                                        app=object(),
                                        host="127.0.0.1",
                                        port=8876,
                                        dashboard_url="http://127.0.0.1:8876/",
                                        health_url="http://127.0.0.1:8876/health",
                                    )

        self.assertEqual(0, result)
        wait_for_server_started.assert_called_once()
        wait_for_url.assert_called_once_with("http://127.0.0.1:8876/health")
        fake_webview.create_window.assert_called_once()
        fake_webview.start.assert_called_once_with(debug=False)
        self.assertEqual(1, len(fake_window.events.closed.handlers))
        stop_server.assert_called_once()

    def test_run_dashboard_window_rejects_occupied_port(self) -> None:
        from dify_win_agent import desktop_window

        with patch.object(desktop_window, "_load_webview_module", return_value=MagicMock()):
            with patch.object(desktop_window, "_port_available", return_value=False):
                with self.assertRaisesRegex(RuntimeError, "端口 8765 已被占用"):
                    desktop_window.run_dashboard_window(
                        app=object(),
                        host="127.0.0.1",
                        port=8765,
                        dashboard_url="http://127.0.0.1:8765/",
                        health_url="http://127.0.0.1:8765/health",
                    )


if __name__ == "__main__":
    unittest.main()