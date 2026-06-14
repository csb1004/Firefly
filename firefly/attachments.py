from pathlib import Path

from .text_utils import clamp_text

SUPPORTED_TEXT_EXTENSIONS = {
    ".cfg",
    ".conf",
    ".csv",
    ".css",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".jsonl",
    ".jsx",
    ".log",
    ".markdown",
    ".md",
    ".py",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
SUPPORTED_CONTENT_TYPES = {
    "application/json",
    "application/x-ndjson",
}
MAX_ATTACHMENT_BYTES = 128 * 1024
MAX_ATTACHMENT_CHARS = 24000
MAX_ATTACHMENT_COUNT = 5
MAX_ATTACHMENT_CONTEXT_CHARS = 60000


def _is_supported_text_attachment(filename: str, content_type: str | None) -> bool:
    suffix = Path(filename).suffix.casefold()
    if suffix in SUPPORTED_TEXT_EXTENSIONS:
        return True

    content_type = (content_type or "").split(";")[0].strip().casefold()
    return content_type.startswith("text/") or content_type in SUPPORTED_CONTENT_TYPES


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _format_attachment_section(filename: str, text: str) -> str:
    safe_filename = filename.replace("`", "'")
    safe_text = text.replace("```", "'''").strip()
    safe_text = clamp_text(safe_text, MAX_ATTACHMENT_CHARS, "\n... [파일 내용 일부 생략]")
    return f"[파일: {safe_filename}]\n```text\n{safe_text}\n```"


async def read_text_attachments(attachments: list[object]) -> str | None:
    if not attachments:
        return None

    sections = []
    skipped = []

    for attachment in attachments[:MAX_ATTACHMENT_COUNT]:
        filename = str(getattr(attachment, "filename", "attachment"))
        content_type = getattr(attachment, "content_type", None)
        size = int(getattr(attachment, "size", 0) or 0)

        if not _is_supported_text_attachment(filename, content_type):
            skipped.append(f"- {filename}: 지원하지 않는 파일 형식")
            continue

        if size > MAX_ATTACHMENT_BYTES:
            skipped.append(f"- {filename}: {MAX_ATTACHMENT_BYTES // 1024}KB보다 커서 생략")
            continue

        try:
            data = await attachment.read()
        except Exception:
            skipped.append(f"- {filename}: 읽기 실패")
            continue

        data = bytes(data)
        if len(data) > MAX_ATTACHMENT_BYTES:
            skipped.append(f"- {filename}: {MAX_ATTACHMENT_BYTES // 1024}KB보다 커서 생략")
            continue

        text = _decode_text(data)
        if not text.strip():
            skipped.append(f"- {filename}: 비어 있는 파일")
            continue

        sections.append(_format_attachment_section(filename, text))

    if len(attachments) > MAX_ATTACHMENT_COUNT:
        skipped.append(f"- 추가 파일 {len(attachments) - MAX_ATTACHMENT_COUNT}개: 한 번에 최대 {MAX_ATTACHMENT_COUNT}개만 읽음")

    if skipped:
        sections.append("[읽지 못한 첨부 파일]\n" + "\n".join(skipped))

    if not sections:
        return None

    return clamp_text(
        "[첨부 파일 내용]\n" + "\n\n".join(sections),
        MAX_ATTACHMENT_CONTEXT_CHARS,
        "\n... [첨부 파일 내용 일부 생략]",
    )
