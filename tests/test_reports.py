from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile


class ReportsTests(unittest.TestCase):
    def test_generate_docx_report_creates_file_with_summary_content(self) -> None:
        from dify_win_agent.reports import CommandExecutionResult, generate_docx_report

        with TemporaryDirectory() as temp_dir:
            report_dir = Path(temp_dir)
            report_path = generate_docx_report(
                task_id="task-001",
                target_host="10.0.0.5",
                command_results=[
                    CommandExecutionResult(
                        command_id="cmd-001",
                        shell="whoami",
                        return_code=0,
                        stdout="administrator",
                        stderr="",
                    )
                ],
                report_dir=report_dir,
            )

            self.assertTrue(report_path.is_file())
            self.assertIn("报告", report_path.name)
            self.assertEqual(".docx", report_path.suffix)

            with zipfile.ZipFile(report_path) as docx_file:
                document_xml = docx_file.read("word/document.xml").decode("utf-8")

            self.assertIn("task-001", document_xml)
            self.assertIn("10.0.0.5", document_xml)
            self.assertIn("administrator", document_xml)


if __name__ == "__main__":
    unittest.main()