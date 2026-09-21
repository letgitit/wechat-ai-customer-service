"""只读资料导入：不执行产品代码，不根据问题扩大读取范围。"""

import ast
import csv
import hashlib
import io
import json
import re
import subprocess
import zipfile
from pathlib import Path
from xml.etree import ElementTree

MAX_BYTES = 2_000_000
DENIED = re.compile(
    r"(^|/)(\.[^/]+|node_modules|vendor|target|dist|build|__pycache__)(/|$)"
    r"|(?:secret|credential|password|production|application-prod|config-prod)"
    r"|\.(?:pem|key|p12|db|sqlite\d*|bak|dump)$",
    re.I,
)
ALLOWED = {
    ".md",
    ".txt",
    ".py",
    ".java",
    ".ts",
    ".js",
    ".vue",
    ".yaml",
    ".yml",
    ".json",
    ".jsonl",
    ".csv",
    ".docx",
    ".pdf",
}
SENSITIVE = re.compile(
    r"-----BEGIN .*PRIVATE KEY|\b(?:api[_-]?key|password|secret|token)\s*[:=]\s*['\"]?[^\s'\"]{6,}"
    r"|\b1[3-9]\d{9}\b|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
    re.I,
)


class SourceError(ValueError):
    pass


def safe_file(root, path):
    root, path = Path(root).absolute(), Path(path).absolute()
    if any(p.is_symlink() for p in [path, *path.parents]):
        raise SourceError("SYMLINK_REJECTED")
    try:
        relative = path.relative_to(root).as_posix()
        path.resolve().relative_to(root.resolve())
    except ValueError:
        raise SourceError("PATH_ESCAPE") from None
    if DENIED.search(relative) or path.suffix.lower() not in ALLOWED:
        raise SourceError("FILE_NOT_ALLOWED")
    if path.stat().st_size > MAX_BYTES:
        raise SourceError("FILE_TOO_LARGE")
    return relative


def read_source(root, path, source):
    relative = safe_file(root, path)
    raw = path.read_bytes()
    if source["type"] == "code" and not source.get("synthetic", False):
        revision = source["revision"]
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise SourceError("EXACT_COMMIT_REQUIRED")
        result = subprocess.run(
            ["git", "-C", str(root), "show", f"{revision}:{relative}"],
            capture_output=True,
            timeout=10,
            check=False,
        )
        if result.returncode or result.stdout != raw:
            raise SourceError("WORKTREE_COMMIT_MISMATCH")
    return relative, raw


def blocks(path, raw, kind):
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(raw))
            if reader.is_encrypted:
                raise SourceError("ENCRYPTED_PDF")
            pages = [
                page.extract_text(extraction_mode="layout") if page.get("/Contents") else ""
                for page in reader.pages
            ]
            if not pages or any(not text.strip() for text in pages):
                images = False
                for page in reader.pages:
                    resources = page.get("/Resources")
                    objects = resources.get_object().get("/XObject") if resources else None
                    if objects:
                        images |= any(
                            obj.get_object().get("/Subtype") == "/Image"
                            for obj in objects.get_object().values()
                        )
                raise SourceError(
                    "SCANNED_PDF_NEEDS_EXTRACTION" if images else "EMPTY_PDF_NEEDS_EXTRACTION"
                )
            for page, text in enumerate(pages, 1):
                yield (
                    text,
                    {"start_line": 1, "end_line": len(text.splitlines()), "page": page},
                    "pdf-layout",
                )
        except ImportError:
            raise SourceError("PDF_DEPENDENCY_MISSING") from None
        except SourceError:
            raise
        except Exception:
            raise SourceError("DAMAGED_PDF") from None
        return
    if suffix == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                if sum(i.file_size for i in archive.infolist()) > MAX_BYTES * 10:
                    raise SourceError("DOCX_TOO_LARGE")
                body = ElementTree.fromstring(archive.read("word/document.xml"))
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            paragraphs = []
            for block in body.find("w:body", ns):
                if block.tag.endswith("}tbl"):
                    for row in block.findall("w:tr", ns):
                        paragraphs.append(
                            " | ".join(
                                "".join(t.text or "" for t in cell.findall(".//w:t", ns))
                                for cell in row.findall("w:tc", ns)
                            )
                        )
                else:
                    paragraphs.append("".join(t.text or "" for t in block.findall(".//w:t", ns)))
            text = "\n".join(paragraphs)
            if not text.strip():
                raise SourceError("NEEDS_EXTRACTION")
            yield (
                text,
                {
                    "start_line": 1,
                    "end_line": len(paragraphs),
                    "section": "OOXML paragraph/table-row ordinals; cells separated by |",
                },
                "docx-paragraphs",
            )
        except SourceError:
            raise
        except Exception:
            raise SourceError("DAMAGED_DOCX") from None
        return
    text = raw.decode("utf-8-sig")
    if "\x00" in text or not text.strip():
        raise SourceError("BINARY_OR_EMPTY")
    lines = text.splitlines()
    if kind == "code":
        if suffix == ".py":
            tree = ast.parse(text)
            nodes = tree.body
            for node in nodes:
                start = min([node.lineno, *[d.lineno for d in getattr(node, "decorator_list", [])]])
                end = node.end_lineno
                # ponytail: keep whole AST statement; over-budget nodes excluded at retrieval.
                yield (
                    "\n".join(lines[start - 1 : end]),
                    {"start_line": start, "end_line": end, "symbol": getattr(node, "name", "")},
                    "python-ast",
                )
        else:
            for start in range(0, len(lines), 68):
                yield (
                    "\n".join(lines[start : start + 80]),
                    {"start_line": start + 1, "end_line": min(start + 80, len(lines))},
                    "fallback-lines",
                )
        return
    starts = sorted({0, *[i for i, line in enumerate(lines) if line.startswith("#")]})
    for start, end in zip(starts, [*starts[1:], len(lines)], strict=True):
        part = "\n".join(lines[start:end]).strip()
        if part:
            yield (
                part,
                {"start_line": start + 1, "end_line": end, "section": lines[start].lstrip("# ")},
                "headings",
            )


def history_records(path, raw):
    text = raw.decode("utf-8-sig")
    if path.suffix == ".csv":
        reader = csv.DictReader(io.StringIO(text))
        _ = reader.fieldnames  # consume header before physical row boundaries
        rows, previous = [], reader.line_num
        for row in reader:
            row["resolved"] = row.get("resolved") == "true"
            row["synthetic"] = row.get("synthetic") == "true"
            row["_source_lines"] = (previous + 1, reader.line_num)
            previous = reader.line_num
            rows.append(row)
        return rows
    rows = []
    for number, line in enumerate(text.splitlines(), 1):
        if line.strip():
            row = json.loads(line)
            row["_source_lines"] = (number, number)
            rows.append(row)
    return rows


def digest(value):
    if not isinstance(value, str):
        value = json.dumps(value, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(value.encode()).hexdigest()
