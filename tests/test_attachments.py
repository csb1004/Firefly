import asyncio

from firefly.attachments import read_text_attachments


class FakeAttachment:
    def __init__(self, filename, data, *, content_type=None, size=None):
        self.filename = filename
        self._data = data
        self.content_type = content_type
        self.size = len(data) if size is None else size

    async def read(self):
        return self._data


def test_read_text_attachments_formats_supported_text_file():
    context = asyncio.run(
        read_text_attachments([
            FakeAttachment("note.md", "# 제목\n본문".encode("utf-8")),
        ])
    )

    assert "[첨부 파일 내용]" in context
    assert "[파일: note.md]" in context
    assert "# 제목" in context
    assert "본문" in context


def test_read_text_attachments_reports_unsupported_files():
    context = asyncio.run(
        read_text_attachments([
            FakeAttachment("image.png", b"not text", content_type="image/png"),
        ])
    )

    assert "[읽지 못한 첨부 파일]" in context
    assert "지원하지 않는 파일 형식" in context
