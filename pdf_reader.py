"""Read a PDF into page-preserving text or JSON.

Requires PyMuPDF:
    python -m pip install pymupdf

Examples:
    python pdf_reader.py input.pdf
    python pdf_reader.py input.pdf --format json --out extracted.json
    python pdf_reader.py input.pdf --format markdown --out extracted.md
    python pdf_reader.py input.pdf --render-dir rendered-pages
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def read_pdf(
    pdf_path: Path,
    *,
    page_start: int = 1,
    page_end: int | None = None,
    min_text_chars: int = 20,
) -> dict[str, Any]:
    """Extract page-level text while preserving 1-based PDF page numbers."""

    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError(
            "缺少 PyMuPDF，请运行: python -m pip install pymupdf"
        ) from exc

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF 文件不存在: {pdf_path}")
    if not pdf_path.is_file():
        raise ValueError(f"输入路径不是文件: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"只支持 PDF 文件: {pdf_path}")
    if page_start < 1:
        raise ValueError("--page-start 必须大于或等于 1")
    if page_end is not None and page_end < page_start:
        raise ValueError("--page-end 不能小于 --page-start")

    with fitz.open(pdf_path) as document:
        total_pages = document.page_count
        selected_end = min(page_end or total_pages, total_pages)
        if page_start > total_pages:
            raise ValueError(
                f"--page-start 超出页数范围: PDF 共 {total_pages} 页"
            )

        pages: list[dict[str, Any]] = []
        for page_number in range(page_start, selected_end + 1):
            page = document.load_page(page_number - 1)
            text = page.get_text("text").replace("\x00", "").strip()
            pages.append(
                {
                    "page": page_number,
                    "text": text,
                    "char_count": len(text),
                    "image_count": len(page.get_images(full=True)),
                    "needs_ocr": len(text) < min_text_chars,
                }
            )

        metadata = {
            str(key): value
            for key, value in (document.metadata or {}).items()
            if value is not None
        }
        return {
            "source": str(pdf_path.resolve()),
            "file_name": pdf_path.name,
            "page_count": total_pages,
            "selected_pages": [page_start, selected_end],
            "metadata": metadata,
            "text_char_count": sum(page["char_count"] for page in pages),
            "ocr_candidate_pages": [
                page["page"] for page in pages if page["needs_ocr"]
            ],
            "pages": pages,
        }


def render_pages(
    pdf_path: Path,
    output_dir: Path,
    *,
    page_start: int = 1,
    page_end: int | None = None,
    dpi: int = 160,
) -> list[str]:
    """Render selected pages for optional OCR or visual inspection."""

    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError(
            "缺少 PyMuPDF，请运行: python -m pip install pymupdf"
        ) from exc

    if dpi <= 0:
        raise ValueError("--dpi 必须大于 0")

    output_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[str] = []
    with fitz.open(pdf_path) as document:
        selected_end = min(page_end or document.page_count, document.page_count)
        matrix = fitz.Matrix(dpi / 72, dpi / 72)
        for page_number in range(page_start, selected_end + 1):
            page = document.load_page(page_number - 1)
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            output_path = output_dir / f"page-{page_number:03d}.png"
            pixmap.save(output_path)
            rendered.append(str(output_path.resolve()))
    return rendered


def _as_markdown(document: dict[str, Any]) -> str:
    metadata = document.get("metadata", {})
    lines = [
        f"# {document['file_name']}",
        "",
        f"- 页数：{document['page_count']}",
        f"- 提取页码：{document['selected_pages'][0]}-{document['selected_pages'][1]}",
        f"- 提取字符数：{document['text_char_count']}",
        f"- 需要 OCR 的页码：{document['ocr_candidate_pages'] or '无'}",
    ]
    if metadata:
        lines.extend(["", "## PDF 元数据", ""])
        for key, value in metadata.items():
            lines.append(f"- {key}：{value}")
    for page in document["pages"]:
        lines.extend(
            [
                "",
                f"## 第 {page['page']} 页",
                "",
                f"> 字符数：{page['char_count']}；图片数：{page['image_count']}；"
                f" OCR 提示：{'是' if page['needs_ocr'] else '否'}",
                "",
                page["text"] or "（本页没有可提取文字）",
            ]
        )
    return "\n".join(lines) + "\n"


def _as_text(document: dict[str, Any]) -> str:
    parts: list[str] = []
    for page in document["pages"]:
        parts.append(f"===== 第 {page['page']} 页 =====")
        parts.append(page["text"])
        parts.append("")
    return "\n".join(parts)


def _write_output(content: str, output_path: Path | None) -> None:
    if output_path is None:
        print(content, end="")
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    print(f"已写入: {output_path.resolve()}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="提取 PDF 的页级文字，并标记可能需要 OCR 的页面。"
    )
    parser.add_argument("pdf", type=Path, help="输入 PDF 路径")
    parser.add_argument(
        "--format",
        choices=("text", "json", "markdown"),
        default="text",
        help="输出格式，默认 text",
    )
    parser.add_argument("--out", type=Path, help="输出文件路径；不指定则输出到终端")
    parser.add_argument("--page-start", type=int, default=1, help="起始页，默认 1")
    parser.add_argument("--page-end", type=int, help="结束页，默认 PDF 最后一页")
    parser.add_argument(
        "--min-text-chars",
        type=int,
        default=20,
        help="少于此字符数的页面标记为 OCR 候选，默认 20",
    )
    parser.add_argument(
        "--render-dir",
        type=Path,
        help="可选：把所选页面渲染为 PNG，供 OCR 或视觉检查",
    )
    parser.add_argument("--dpi", type=int, default=160, help="渲染分辨率，默认 160")
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_stdout()
    args = build_parser().parse_args(argv)
    try:
        document = read_pdf(
            args.pdf,
            page_start=args.page_start,
            page_end=args.page_end,
            min_text_chars=args.min_text_chars,
        )
        if args.render_dir:
            document["rendered_pages"] = render_pages(
                args.pdf,
                args.render_dir,
                page_start=args.page_start,
                page_end=args.page_end,
                dpi=args.dpi,
            )

        if args.format == "json":
            content = json.dumps(document, ensure_ascii=False, indent=2)
        elif args.format == "markdown":
            content = _as_markdown(document)
        else:
            content = _as_text(document)
        _write_output(content, args.out)
        return 0
    except (FileNotFoundError, RuntimeError, ValueError, OSError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
