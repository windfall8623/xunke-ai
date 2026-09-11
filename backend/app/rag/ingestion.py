"""Canonical text parsing without model, network, SQL, or vector-store access.

For untrusted uploads workers use load_canonical_document_bounded: its child process
has no Chroma client and can be terminated at the parser deadline. The synchronous
function also enforces byte, page, expansion and canonical-text size limits.
"""

from __future__ import annotations

import hashlib
import io
import re
import subprocess
import sys
import unicodedata
import zipfile
from pathlib import Path

from app.rag.contracts import (
    CanonicalBlock,
    CanonicalDocument,
    Section,
    SourceInput,
    stable_hash,
    text_hash,
)
from app.rag.errors import SourceUnavailable

NORMALIZER_VERSION = "nfc-lf-v1"
MAX_CANONICAL_CHARS = 20 * 1024 * 1024


def _normalize(text: str) -> str:
    return unicodedata.normalize(
        "NFC", text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    )


def _text_blocks(text: str, markdown: bool) -> list[dict]:
    blocks, offset, paragraph, was_blank = [], 0, 0, True
    headings: list[tuple[int, str]] = []
    fence = False
    table_row = 0
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        body = line.rstrip("\n")
        if not body.strip():
            was_blank = True
            offset += len(line)
            continue
        if was_blank:
            paragraph += 1
        was_blank = False
        block = {
            "kind": "paragraph",
            "start_char": offset,
            "end_char": offset + len(body),
            "paragraph": paragraph,
            "line_start": number,
            "line_end": number,
        }
        if markdown:
            if re.match(r"^\s*(```|~~~)", body):
                fence = not fence
                block["kind"] = "code"
            elif fence:
                block["kind"] = "code"
            elif match := re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$", body):
                level, title = len(match[1]), match[2]
                headings = [h for h in headings if h[0] < level]
                headings.append((level, title))
                block.update(kind="heading", heading_level=level, heading_title=title)
            elif "|" in body:
                table_row += 1
                block.update(kind="table_row", table_row=table_row)
            else:
                table_row = 0
        block["heading_path"] = [h[1] for h in headings]
        blocks.append(block)
        offset += len(line)
    return blocks


def _pdf(data: bytes, max_pages: int) -> tuple[str, list[dict], str]:
    import pypdf

    reader = pypdf.PdfReader(io.BytesIO(data), strict=False)
    if reader.is_encrypted:
        raise SourceUnavailable("Encrypted PDF is not supported")
    if len(reader.pages) > max_pages:
        raise SourceUnavailable("PDF exceeds the page limit")
    chunks, blocks, offset = [], [], 0
    for page_number, page in enumerate(reader.pages, 1):
        text = _normalize(page.extract_text() or "").strip("\n")
        if chunks:
            chunks.append("\n\n")
            offset += 2
        start = offset
        chunks.append(text)
        offset += len(text)
        if offset > MAX_CANONICAL_CHARS:
            raise SourceUnavailable("Canonical document exceeds the text limit")
        if text.strip():
            blocks.append(
                {
                    "kind": "page",
                    "start_char": start,
                    "end_char": offset,
                    "page": page_number,
                    "heading_path": [],
                }
            )
    return "".join(chunks), blocks, f"pypdf-{pypdf.__version__}-physical-v1"


def _docx(data: bytes) -> tuple[str, list[dict], str]:
    import docx
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    with zipfile.ZipFile(io.BytesIO(data)) as bundle:
        members = bundle.infolist()
        if len(members) > 2000 or sum(m.file_size for m in members) > 100 * 1024 * 1024:
            raise SourceUnavailable("DOCX archive exceeds the extraction limit")
        if any(
            m.file_size > 100_000 and m.file_size / max(1, m.compress_size) > 200
            for m in members
        ):
            raise SourceUnavailable("DOCX archive has an unsafe compression ratio")
    document = docx.Document(io.BytesIO(data))
    chunks, blocks, headings = [], [], []
    offset, paragraph = 0, 0

    def append(text: str, block: dict):
        nonlocal offset
        text = _normalize(text)
        if not text.strip():
            return
        if chunks:
            chunks.append("\n")
            offset += 1
        block.update(
            start_char=offset,
            end_char=offset + len(text),
            heading_path=[h[1] for h in headings],
        )
        chunks.append(text)
        blocks.append(block)
        offset += len(text)
        if offset > MAX_CANONICAL_CHARS:
            raise SourceUnavailable("Canonical document exceeds the text limit")

    for item in document.element.body.iterchildren():
        if item.tag == qn("w:p"):
            paragraph += 1
            p = Paragraph(item, document)
            level = None
            match = (
                re.match(r"Heading\s+(\d+)$", p.style.name, re.IGNORECASE)
                if p.style
                else None
            )
            if match:
                level = int(match[1])
            else:
                outline = p._p.xpath("./w:pPr/w:outlineLvl")
                if outline and int(outline[0].get(qn("w:val"))) < 9:
                    level = int(outline[0].get(qn("w:val"))) + 1
            block = {"kind": "paragraph", "paragraph": paragraph}
            if level and p.text.strip():
                headings = [h for h in headings if h[0] < level]
                headings.append((level, _normalize(p.text)))
                block.update(
                    kind="heading",
                    heading_level=level,
                    heading_title=_normalize(p.text),
                )
            append(p.text, block)
        elif item.tag == qn("w:tbl"):
            table = Table(item, document)
            for row_number, row in enumerate(table.rows, 1):
                append(
                    " | ".join(cell.text for cell in row.cells),
                    {"kind": "table_row", "table_row": row_number},
                )
    return "".join(chunks), blocks, f"python-docx-{docx.__version__}-blocks-v1"


def _finalize(
    source: SourceInput, source_sha: str, text: str, raw: list[dict], parser: str
) -> CanonicalDocument:
    if not text.strip() or not raw:
        raise SourceUnavailable(
            "No reliable text was found; scanned documents require OCR"
        )
    canonical_hash = text_hash(text)
    parse_id = (
        "parse_"
        + stable_hash([source_sha, parser, NORMALIZER_VERSION, canonical_hash])[:32]
    )
    sections: list[Section] = []
    section_at: dict[int, str] = {}
    headings = [(i, b) for i, b in enumerate(raw) if b["kind"] == "heading"]
    for ordinal, (index, block) in enumerate(headings, 1):
        section_id = f"{parse_id}:section_{ordinal}"
        end = len(text)
        for _, later in headings[ordinal:]:
            if later["heading_level"] <= block["heading_level"]:
                end = later["start_char"]
                break
        sections.append(
            Section(
                section_id=section_id,
                title=block["heading_title"],
                heading_path=block["heading_path"],
                start_char=block["start_char"],
                end_char=end,
                level=block["heading_level"],
            )
        )
        section_at[index] = section_id
    root_id = f"{parse_id}:section_0"
    if not sections:
        sections.append(
            Section(
                section_id=root_id,
                title=source.title or "正文",
                start_char=0,
                end_char=len(text),
                level=0,
            )
        )
    blocks, current_section = [], root_id
    for index, block in enumerate(raw):
        current_section = section_at.get(index, current_section)
        block = {k: v for k, v in block.items() if k != "heading_title"}
        blocks.append(
            CanonicalBlock(
                block_id=f"{parse_id}:block_{index + 1}",
                section_id=current_section,
                **block,
            )
        )
    return CanonicalDocument(
        owner_id=source.owner_id,
        namespace=source.namespace,
        doc_id=source.doc_id,
        document_version_id=source.document_version_id,
        title=source.title or "未命名资料",
        file_type=source.file_type,
        source_sha256=source_sha,
        parse_artifact_id=parse_id,
        canonical_text_hash=canonical_hash,
        parser_version=parser,
        normalizer_version=NORMALIZER_VERSION,
        text=text,
        blocks=blocks,
        sections=sections,
    )


def load_canonical_document(source: SourceInput | dict) -> CanonicalDocument:
    source = SourceInput.model_validate(source)
    try:
        with Path(source.file_path).open("rb") as handle:
            data = handle.read(source.max_bytes + 1)
        if len(data) > source.max_bytes:
            raise SourceUnavailable("Source exceeds the byte limit")
        source_sha = hashlib.sha256(data).hexdigest()
        if source.source_sha256 and source.source_sha256 != source_sha:
            raise SourceUnavailable("Source file checksum changed")
        if source.file_type == "pdf":
            if not data.startswith(b"%PDF-"):
                raise SourceUnavailable("Source is not a PDF document")
            text, blocks, parser = _pdf(data, source.max_pages)
        elif source.file_type == "docx":
            if not data.startswith(b"PK"):
                raise SourceUnavailable("Source is not a DOCX document")
            text, blocks, parser = _docx(data)
        else:
            text = _normalize(data.decode("utf-8-sig"))
            blocks = _text_blocks(text, markdown=source.file_type == "md")
            parser = (
                "markdown-blocks-v1" if source.file_type == "md" else "utf8-lines-v1"
            )
        if len(text) > MAX_CANONICAL_CHARS:
            raise SourceUnavailable("Canonical document exceeds the text limit")
        return _finalize(source, source_sha, text, blocks, parser)
    except SourceUnavailable:
        raise
    except Exception as exc:
        raise SourceUnavailable(
            "Source parsing failed", details={"parser_error": type(exc).__name__}
        ) from exc


def load_canonical_document_bounded(
    source: SourceInput, timeout_seconds: float = 45
) -> CanonicalDocument:
    """Parse in a killable child. Only the source request and canonical JSON cross IPC."""
    if not 0 < timeout_seconds <= 120:
        raise ValueError("Parser timeout must be between 0 and 120 seconds")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "app.rag.ingestion", "--parse"],
            input=source.model_dump_json().encode("utf-8"),
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
            cwd=str(Path(__file__).resolve().parents[2]),
        )
    except subprocess.TimeoutExpired as exc:
        raise SourceUnavailable("Source parsing exceeded the deadline") from exc
    if result.returncode:
        raise SourceUnavailable("Source parsing failed or contains no reliable text")
    return CanonicalDocument.model_validate_json(result.stdout)


if __name__ == "__main__":
    try:
        request = SourceInput.model_validate_json(sys.stdin.buffer.read(65536))
        sys.stdout.buffer.write(
            load_canonical_document(request).model_dump_json().encode("utf-8")
        )
    except Exception:  # noqa: BLE001 - The isolated parser emits only a redacted exit status.
        # The caller receives a redacted error; no private parser traceback is emitted.
        sys.exit(2)
