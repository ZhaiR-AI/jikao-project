"""Read text documents for the model; PDFs always use the vision pipeline."""
from pathlib import Path
import re
import zipfile
from xml.etree import ElementTree as ET


TEXT_EXTENSIONS = {".txt", ".md", ".docx"}
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _read_docx(path):
    try:
        with zipfile.ZipFile(path) as archive:
            document = ET.fromstring(archive.read("word/document.xml"))
            if document.find(f".//{W}drawing") is not None or document.find(f".//{W}pict") is not None:
                raise ValueError("这份 Word 含有图片，请先导出为 PDF，使用多模态识别，以免漏掉图片中的题目。")
            if document.find(".//{http://schemas.openxmlformats.org/officeDocument/2006/math}oMath") is not None:
                raise ValueError("这份 Word 含有公式对象，请先导出为 PDF，保留公式后进行多模态识别。")
            numbering = ET.fromstring(archive.read("word/numbering.xml")) if "word/numbering.xml" in archive.namelist() else None
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        raise ValueError("无法读取 Word 文件，请确认文件是有效的 .docx，或将其导出为 PDF。") from exc

    definitions, instances, counters, overrides = {}, {}, {}, set()
    if numbering is not None:
        for abstract in numbering.findall(f"{W}abstractNum"):
            for level in abstract.findall(f"{W}lvl"):
                definitions[(abstract.get(W + "abstractNumId"), level.get(W + "ilvl"))] = level
        for instance in numbering.findall(f"{W}num"):
            if instance.find(f"{W}lvlOverride") is not None:
                overrides.add(instance.get(W + "numId"))
            abstract = instance.find(f"{W}abstractNumId")
            if abstract is not None:
                instances[instance.get(W + "numId")] = abstract.get(W + "val")

    lines = []
    for paragraph in document.findall(f".//{W}body//{W}p"):
        text = "".join(n.text or "" if n.tag == W + "t" else "\t" if n.tag == W + "tab" else "\n"
                       for n in paragraph.iter() if n.tag in {W + "t", W + "tab", W + "br", W + "cr"}).strip()
        if not text:
            continue
        number = paragraph.find(f"{W}pPr/{W}numPr/{W}numId")
        if number is not None and number.get(W + "val") != "0":
            indent = paragraph.find(f"{W}pPr/{W}numPr/{W}ilvl")
            level_id = indent.get(W + "val") if indent is not None else "0"
            num_id = number.get(W + "val")
            level = definitions.get((instances.get(num_id), level_id))
            if level is None:
                raise ValueError("Word 中的自动编号无法完整读取，请导出为 PDF 后识别。")
            fmt = level.find(f"{W}numFmt")
            start = level.find(f"{W}start")
            template = level.find(f"{W}lvlText")
            kind = fmt.get(W + "val") if fmt is not None else "decimal"
            if kind not in {"decimal", "upperLetter", "lowerLetter", "bullet"} or level_id != "0" or num_id in overrides:
                raise ValueError("Word 使用复杂自动编号，请导出为 PDF 后识别，避免题号丢失。")
            key = (num_id, level_id)
            counters[key] = counters.get(key, int(start.get(W + "val", "1")) - 1 if start is not None else 0) + 1
            if kind in {"upperLetter", "lowerLetter"} and not 1 <= counters[key] <= 26:
                raise ValueError("Word 的字母编号超出可读取范围，请导出为 PDF 后识别。")
            value = str(counters[key]) if kind == "decimal" else chr((65 if kind == "upperLetter" else 97) + (counters[key] - 1) % 26)
            prefix = template.get(W + "val", "%1.") if template is not None else "%1."
            text = prefix.replace("%1", value) + " " + text
        lines.append(text)
    return "\n\n".join(lines)


def read_document_pages(path: Path):
    suffix = path.suffix.lower()
    if suffix == ".docx":
        text = _read_docx(path)
    elif suffix in {".txt", ".md"}:
        raw = path.read_bytes()
        text = None
        encodings = ["utf-16"] if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else ["utf-8-sig", "gb18030"]
        for encoding in encodings:
            try:
                text = raw.decode(encoding)
                break
            except UnicodeError:
                pass
        if text is None or "\x00" in text:
            raise ValueError("无法读取文本编码，请另存为 UTF-8 的 TXT 或 Markdown 文件。")
    else:
        raise ValueError("支持 PDF、Word（.docx）、TXT 和 Markdown 文件。旧版 .doc 请先另存为 .docx 或 PDF。")
    if not text.strip():
        raise ValueError("文件中没有可读取的文字；图片或扫描件请使用 PDF 多模态识别。")
    # These are content segments, not fabricated Word page numbers. Keep each
    # paragraph intact so the overlapping model windows can join continuations.
    segments, current = [], []
    for block in re.split(r"\n\s*\n", text.strip()):
        if current and sum(map(len, current)) + len(block) > 6000:
            segments.append("\n\n".join(current)); current = []
        current.append(block)
    if current:
        segments.append("\n\n".join(current))
    return [{"page": i, "text": segment, "extraction_method": "document_text"} for i, segment in enumerate(segments, 1)]
