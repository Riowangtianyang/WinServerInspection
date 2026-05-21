from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


class ConfigTests(unittest.TestCase):
    def test_load_config_uses_defaults_when_optional_values_missing(self) -> None:
        from dify_win_agent.config import load_config

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = load_config({}, application_root=root)

            self.assertEqual("0.0.0.0", config.host)
            self.assertEqual(8765, config.port)
            self.assertEqual(300, config.command_timeout_seconds)
            self.assertEqual(root / "doc", config.log_dir)
            self.assertEqual(root / "document", config.report_dir)
            self.assertEqual(root / "dify-win-agent.settings.json", config.settings_path)

    def test_load_config_reads_settings_file_and_allows_env_override(self) -> None:
        from dify_win_agent.config import load_config

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings_path = root / "dify-win-agent.settings.json"
            settings_path.write_text(
                '{"port": 9010, "log_dir": "custom-logs", "report_dir": "custom-reports"}',
                encoding="utf-8",
            )

            config = load_config(
                {
                    "DIFY_WIN_AGENT_REPORT_DIR": "env-reports",
                },
                application_root=root,
            )

            self.assertEqual(9010, config.port)
            self.assertEqual(root / "custom-logs", config.log_dir)
            self.assertEqual(root / "env-reports", config.report_dir)


if __name__ == "__main__":
    unittest.main()