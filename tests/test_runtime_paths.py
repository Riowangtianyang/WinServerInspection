from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


class RuntimePathsTests(unittest.TestCase):
    def test_ensure_runtime_directories_creates_doc_and_document(self) -> None:
        from dify_win_agent.runtime_paths import ensure_runtime_directories

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            paths = ensure_runtime_directories(root)

            self.assertTrue(paths.log_dir.is_dir())
            self.assertTrue(paths.report_dir.is_dir())
            self.assertEqual(root / "doc", paths.log_dir)
            self.assertEqual(root / "document", paths.report_dir)

    def test_ensure_runtime_directories_respects_custom_directories(self) -> None:
        from dify_win_agent.runtime_paths import ensure_runtime_directories

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            custom_log_dir = root / "logs" / "agent"
            custom_report_dir = root / "reports" / "agent"

            paths = ensure_runtime_directories(root, custom_log_dir, custom_report_dir)

            self.assertEqual(custom_log_dir.resolve(), paths.log_dir)
            self.assertEqual(custom_report_dir.resolve(), paths.report_dir)
            self.assertTrue(paths.log_dir.is_dir())
            self.assertTrue(paths.report_dir.is_dir())


if __name__ == "__main__":
    unittest.main()