from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import html
import zipfile

from dify_win_agent.runtime_paths import build_artifact_path


@dataclass(frozen=True)
class CommandExecutionResult:
    command_id: str
    shell: str
    return_code: int
    stdout: str
    stderr: str


def _paragraph(text: str) -> str:
    escaped = html.escape(text)
    return (
        "<w:p><w:r><w:t xml:space=\"preserve\">"
        f"{escaped}"
        "</w:t></w:r></w:p>"
    )


def generate_docx_report(
    task_id: str,
    target_host: str,
    command_results: list[CommandExecutionResult],
    report_dir: Path,
    created_at: datetime | None = None,
) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = build_artifact_path(
        report_dir,
        task_id,
        "报告",
        ".docx",
        created_at or datetime.now(timezone.utc),
    )

    body_parts = [
        _paragraph(f"任务编号: {task_id}"),
        _paragraph(f"目标主机: {target_host}"),
    ]

    for result in command_results:
        body_parts.extend(
            [
                _paragraph(f"命令编号: {result.command_id}"),
                _paragraph(f"命令: {result.shell}"),
                _paragraph(f"返回码: {result.return_code}"),
                _paragraph(f"标准输出: {result.stdout}"),
                _paragraph(f"标准错误: {result.stderr}"),
            ]
        )

    document_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<w:document xmlns:wpc=\"http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas\" "
        "xmlns:mc=\"http://schemas.openxmlformats.org/markup-compatibility/2006\" "
        "xmlns:o=\"urn:schemas-microsoft-com:office:office\" "
        "xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\" "
        "xmlns:m=\"http://schemas.openxmlformats.org/officeDocument/2006/math\" "
        "xmlns:v=\"urn:schemas-microsoft-com:vml\" "
        "xmlns:wp14=\"http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing\" "
        "xmlns:wp=\"http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing\" "
        "xmlns:w10=\"urn:schemas-microsoft-com:office:word\" "
        "xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\" "
        "xmlns:w14=\"http://schemas.microsoft.com/office/word/2010/wordml\" "
        "xmlns:wpg=\"http://schemas.microsoft.com/office/word/2010/wordprocessingGroup\" "
        "xmlns:wpi=\"http://schemas.microsoft.com/office/word/2010/wordprocessingInk\" "
        "xmlns:wne=\"http://schemas.microsoft.com/office/2006/wordml\" "
        "xmlns:wps=\"http://schemas.microsoft.com/office/word/2010/wordprocessingShape\" "
        "mc:Ignorable=\"w14 wp14\"><w:body>"
        + "".join(body_parts)
        + "<w:sectPr><w:pgSz w:w=\"11906\" w:h=\"16838\"/><w:pgMar w:top=\"1440\" w:right=\"1440\" w:bottom=\"1440\" w:left=\"1440\" w:header=\"708\" w:footer=\"708\" w:gutter=\"0\"/></w:sectPr></w:body></w:document>"
    )

    with zipfile.ZipFile(report_path, "w", compression=zipfile.ZIP_DEFLATED) as docx:
        docx.writestr(
            "[Content_Types].xml",
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
            "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">"
            "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>"
            "<Default Extension=\"xml\" ContentType=\"application/xml\"/>"
            "<Override PartName=\"/word/document.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/>"
            "</Types>",
        )
        docx.writestr(
            "_rels/.rels",
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
            "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
            "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"word/document.xml\"/>"
            "</Relationships>",
        )
        docx.writestr("word/document.xml", document_xml)

    return report_path