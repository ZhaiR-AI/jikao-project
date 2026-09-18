from __future__ import annotations

import asyncio
import copy
import json
import logging
import random
import re
import shutil
import uuid
from difflib import SequenceMatcher
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar

from agentclaw.model.manager import LLMManager
from agentclaw.model.vision import ImageInput


PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
PAGE_DIR = DATA_DIR / "pages"
PAPER_DIR = DATA_DIR / "papers"
OCR_DIR = DATA_DIR / "ocr"

DEFAULT_OCR_CONCURRENCY = 3
MAX_OCR_CONCURRENCY = 4
AI_GRADING_CONCURRENCY = 3
GENERATION_RETRY_ATTEMPTS = 3
GENERATION_RETRY_BASE_DELAY_SECONDS = 1.5

logger = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass
class GenerationOptions:
    max_pages: int | None = None
    dpi: int = 160
    ocr_concurrency: int = DEFAULT_OCR_CONCURRENCY


class PaperGenerationError(RuntimeError):
    pass


async def _retry_generation_call(
    operation: Callable[[], Awaitable[T]],
    *,
    operation_name: str,
    attempts: int = GENERATION_RETRY_ATTEMPTS,
) -> T:
    attempts = max(1, int(attempts))
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await operation()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            last_error = exc
            if attempt >= attempts:
                break
            delay = GENERATION_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
            delay += random.uniform(0, 0.5)
            logger.warning(
                "%s failed on attempt %s/%s; retrying in %.1fs: %s",
                operation_name,
                attempt,
                attempts,
                delay,
                exc,
            )
            await asyncio.sleep(delay)
    raise PaperGenerationError(
        f"{operation_name}连续 {attempts} 次失败: {last_error}"
    ) from last_error


def ensure_data_dirs() -> None:
    for path in (UPLOAD_DIR, PAGE_DIR, PAPER_DIR, OCR_DIR):
        path.mkdir(parents=True, exist_ok=True)


def read_paper(paper_id: str) -> dict[str, Any]:
    from paper_trash import deleted_ids
    hidden = deleted_ids()
    if paper_id in hidden:
        raise FileNotFoundError(paper_id)
    path = _paper_json_path(paper_id)
    if not path.exists():
        raise FileNotFoundError(paper_id)
    paper = json.loads(path.read_text(encoding="utf-8"))
    if paper.get("type") == "paper_collection":
        paper["papers"] = [p for p in paper.get("papers", []) if p.get("id") not in hidden]
    from collection_categories import display_name
    paper["title"] = display_name(paper_id, paper.get("title", paper_id))
    for entry in paper.get("papers", []):
        entry["title"] = display_name(entry["id"], entry.get("title", entry["id"]))
    return paper


async def generate_paper_from_pdf(
    source_pdf: Path,
    *,
    original_name: str,
    options: GenerationOptions | None = None,
) -> dict[str, Any]:
    """Compatibility wrapper that executes the AgentClaw workflow."""
    from agents.paper_generation import workflow

    result = await workflow.run(
        {
            "pdf_path": str(source_pdf),
            "original_name": original_name,
            "max_pages": options.max_pages if options else None,
            "dpi": options.dpi if options else 160,
            "ocr_concurrency": options.ocr_concurrency if options else DEFAULT_OCR_CONCURRENCY,
        }
    )
    return result["state"]["generation_result"]


async def generate_paper_pipeline(
    source_pdf: Path,
    *,
    original_name: str,
    llm: LLMManager,
    options: GenerationOptions | None = None,
) -> dict[str, Any]:
    ensure_data_dirs()
    options = options or GenerationOptions()
    collection_id = uuid.uuid4().hex
    stored_pdf = UPLOAD_DIR / f"{collection_id}.pdf"
    shutil.copyfile(source_pdf, stored_pdf)

    page_images = await asyncio.to_thread(
        _render_pdf_pages,
        stored_pdf,
        PAGE_DIR / collection_id,
        options.dpi,
        options.max_pages,
    )
    if not page_images:
        raise PaperGenerationError("PDF 没有可处理的页面")

    ocr_pages = await ocr_page_images(
        llm=llm,
        page_images=page_images,
        ocr_concurrency=options.ocr_concurrency,
        source_pdf=stored_pdf,
    )

    ocr_doc = {
        "id": collection_id,
        "source": {
            "file_name": original_name,
            "page_count": len(page_images),
            "ocr_model": llm.get_model(llm.get_vision_model_id() or "vision").model,
        },
        "pages": ocr_pages,
    }
    _ocr_json_path(collection_id).write_text(
        json.dumps(ocr_doc, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    exams = await _split_exams(llm, original_name, ocr_pages)
    papers: list[dict[str, Any]] = []
    for index, exam in enumerate(exams, start=1):
        paper_id = f"{collection_id}-{index}"
        start_page = int(exam.get("start_page") or 1)
        end_page = int(exam.get("end_page") or len(ocr_pages))
        scoped_pages = [
            page for page in ocr_pages if start_page <= int(page.get("page", 0)) <= end_page
        ] or ocr_pages
        paper = await _build_exam_json(
            llm,
            paper_id,
            original_name,
            scoped_pages,
            exam_hint=exam,
        )
        paper.setdefault("id", paper_id)
        paper.setdefault("title", exam.get("title") or Path(original_name).stem)
        paper.setdefault("source", {})
        paper["source"].update(
            {
                "file_name": original_name,
                "collection_id": collection_id,
                "page_count": len(page_images),
                "start_page": start_page,
                "end_page": end_page,
                "ocr_model": llm.get_model(llm.get_vision_model_id() or "vision").model,
            }
        )
        paper["ocr_pages"] = scoped_pages

        output_path = _paper_json_path(paper_id)
        output_path.write_text(
            json.dumps(paper, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        papers.append(paper)

    collection = {
        "id": collection_id,
        "type": "paper_collection",
        "title": Path(original_name).stem,
        "source": ocr_doc["source"],
        "ocr_url": f"/api/paper/ocr/{collection_id}",
        "papers": [
            {
                "id": paper["id"],
                "title": paper.get("title", paper["id"]),
                "description": paper.get("description", ""),
                "question_count": _paper_question_count(paper),
                "total_score": paper.get("total_score", 0),
                "paper_url": f"/exam/{paper['id']}",
                "json_url": f"/api/paper/{paper['id']}",
                "start_page": paper.get("source", {}).get("start_page"),
                "end_page": paper.get("source", {}).get("end_page"),
            }
            for paper in papers
        ],
    }
    _paper_json_path(collection_id).write_text(
        json.dumps(collection, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "id": collection_id,
        "type": "paper_collection",
        "collection": collection,
        "papers": papers,
        "paper": papers[0] if papers else None,
    }


async def create_ocr_document(
    source_pdf: Path,
    *,
    original_name: str,
    llm: LLMManager,
    options: GenerationOptions | None = None,
) -> dict[str, Any]:
    ensure_data_dirs()
    options = options or GenerationOptions()
    render_result = render_pdf_for_ocr(
        source_pdf,
        dpi=options.dpi,
        max_pages=options.max_pages,
    )
    ocr_pages = await ocr_page_images(
        llm=llm,
        page_images=render_result["page_images"],
        ocr_concurrency=options.ocr_concurrency,
        source_pdf=Path(render_result["stored_pdf"]),
    )
    return persist_ocr_document(
        collection_id=render_result["collection_id"],
        original_name=original_name,
        page_count=render_result["page_count"],
        ocr_model=get_vision_model_name(llm),
        ocr_pages=ocr_pages,
    )


def render_pdf_for_ocr(
    source_pdf: Path,
    *,
    dpi: int,
    max_pages: int | None,
) -> dict[str, Any]:
    ensure_data_dirs()
    collection_id = uuid.uuid4().hex
    stored_pdf = UPLOAD_DIR / f"{collection_id}.pdf"
    shutil.copyfile(source_pdf, stored_pdf)

    page_images = _render_pdf_pages(
        stored_pdf,
        PAGE_DIR / collection_id,
        dpi,
        max_pages,
    )
    if not page_images:
        raise PaperGenerationError("PDF 没有可处理的页面")

    import fitz
    with fitz.open(stored_pdf) as document:
        source_page_count = len(document)
    return {
        "collection_id": collection_id,
        "stored_pdf": str(stored_pdf),
        "page_images": [str(path) for path in page_images],
        "page_count": len(page_images),
        "source_page_count": source_page_count,
    }


async def ocr_page_images(
    *,
    llm: LLMManager,
    page_images: list[str | Path],
    ocr_concurrency: int,
    cached_pages: list[dict[str, Any]] | None = None,
    on_page: Callable | None = None,
    source_pdf: Path | None = None,
) -> list[dict[str, Any]]:
    image_paths = [Path(path) for path in page_images]
    semaphore = asyncio.Semaphore(
        max(1, min(int(ocr_concurrency or DEFAULT_OCR_CONCURRENCY), MAX_OCR_CONCURRENCY))
    )

    async def run_ocr(index: int, image_path: Path) -> dict[str, Any]:
        cached = next((page for page in (cached_pages or []) if page.get("page") == index), None)
        if cached and cached.get("extraction_method") == "vision_ocr":
            return cached
        async with semaphore:
            # PDF text layers can contain plausible-looking OCR garbage and
            # scrambled columns. Every PDF page must go through the vision model.
            text = await _ocr_page(llm, image_path, index, len(image_paths))
            result = {
                "page": index,
                "image": str(image_path.relative_to(PROJECT_DIR)).replace("\\", "/"),
                "text": text.strip(),
                "extraction_method": "vision_ocr",
            }
            if on_page:
                on_page(result)
            return result

    results = await asyncio.gather(
        *[run_ocr(index, image_path) for index, image_path in enumerate(image_paths, start=1)],
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, BaseException):
            raise result
    return results


def get_vision_model_name(llm: LLMManager) -> str:
    return llm.get_model(llm.get_vision_model_id() or "vision").model


def persist_ocr_document(
    *,
    collection_id: str,
    original_name: str,
    page_count: int,
    ocr_model: str,
    ocr_pages: list[dict[str, Any]],
) -> dict[str, Any]:
    ocr_doc = {
        "id": collection_id,
        "source": {
            "file_name": original_name,
            "page_count": page_count,
            "ocr_model": ocr_model,
        },
        "pages": ocr_pages,
    }
    _ocr_json_path(collection_id).write_text(
        json.dumps(ocr_doc, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return ocr_doc


async def split_exam_ranges(
    *,
    llm: LLMManager,
    original_name: str,
    ocr_doc: dict[str, Any],
) -> list[dict[str, Any]]:
    return await _split_exams(llm, original_name, ocr_doc["pages"])


async def build_exam_papers(
    *,
    llm: LLMManager,
    original_name: str,
    ocr_doc: dict[str, Any],
    exams: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    collection_id = ocr_doc["id"]
    ocr_pages = ocr_doc["pages"]
    papers: list[dict[str, Any]] = []
    for index, exam in enumerate(exams, start=1):
        paper_id = f"{collection_id}-{index}"
        start_page = int(exam.get("start_page") or 1)
        end_page = int(exam.get("end_page") or len(ocr_pages))
        scoped_pages = [
            page for page in ocr_pages if start_page <= int(page.get("page", 0)) <= end_page
        ] or ocr_pages
        standard_paper = None if ocr_doc["source"].get("input_type") == "document" else _build_standard_exam_from_ocr(
            paper_id=paper_id,
            original_name=original_name,
            exam_hint=exam,
            scoped_pages=scoped_pages,
        )
        if standard_paper:
            paper = standard_paper
        else:
            paper = await _build_exam_json_chunked(
                llm,
                paper_id,
                original_name,
                scoped_pages,
                exam_hint=exam,
            )
            paper = _repair_cloze_sections_from_ocr(paper, scoped_pages)
            paper = _repair_reading_sections_from_ocr(paper, scoped_pages)
            paper = _repair_part_structure_from_ocr(paper, scoped_pages)
            standard_paper = _build_standard_exam_from_ocr(
                paper_id=paper_id,
                original_name=original_name,
                exam_hint=exam,
                scoped_pages=scoped_pages,
            )
            if standard_paper and _is_better_standard_paper(standard_paper, paper):
                paper = standard_paper
        paper.setdefault("id", paper_id)
        paper.setdefault("title", exam.get("title") or Path(original_name).stem)
        paper.setdefault("source", {})
        paper["source"].update(
            {
                "file_name": original_name,
                "collection_id": collection_id,
                "page_count": ocr_doc["source"]["page_count"],
                "start_page": start_page,
                "end_page": end_page,
                "ocr_model": ocr_doc["source"]["ocr_model"],
            }
        )
        paper["ocr_pages"] = scoped_pages

        _paper_json_path(paper_id).write_text(
            json.dumps(paper, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        papers.append(paper)
    return papers


def create_exam_build_jobs(
    *,
    original_name: str,
    ocr_doc: dict[str, Any],
    exams: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    collection_id = ocr_doc["id"]
    ocr_pages = ocr_doc["pages"]
    jobs = []
    for index, exam in enumerate(exams, start=1):
        start_page = int(exam.get("start_page") or 1)
        end_page = int(exam.get("end_page") or len(ocr_pages))
        scoped_pages = [
            page for page in ocr_pages if start_page <= int(page.get("page", 0)) <= end_page
        ] or ocr_pages
        standard_paper = None if ocr_doc["source"].get("input_type") == "document" else _build_standard_exam_from_ocr(
            paper_id=f"{collection_id}-{index}",
            original_name=original_name,
            exam_hint=exam,
            scoped_pages=scoped_pages,
        )
        jobs.append(
            {
                "paper_id": f"{collection_id}-{index}",
                "original_name": original_name,
                "exam": exam,
                "start_page": start_page,
                "end_page": end_page,
                "scoped_pages": scoped_pages,
                "standard_paper": standard_paper,
            }
        )
    return jobs


async def extract_exam_questions_for_jobs(
    *,
    llm: LLMManager,
    exam_jobs: list[dict[str, Any]],
    cached_chunks: dict | None = None,
    on_chunk: Callable | None = None,
) -> list[dict[str, Any]]:
    extracted_jobs = []
    for job in exam_jobs:
        if job.get("standard_paper"):
            extracted_jobs.append({**job, "extracted_chunks": []})
            continue
        chunks = _make_page_windows(job["scoped_pages"], window_size=2, step=1)
        extracted_chunks = []
        for chunk_index, chunk_pages in enumerate(chunks, start=1):
            cache_key = f"{job['paper_id']}:{chunk_index}"
            chunk = (cached_chunks or {}).get(cache_key)
            if chunk is None:
                chunk = await _extract_questions_from_chunk(
                    llm,
                    original_name=job["original_name"],
                    exam_hint=job["exam"],
                    chunk_pages=chunk_pages,
                    chunk_index=chunk_index,
                    chunk_count=len(chunks),
                )
                if on_chunk:
                    on_chunk(cache_key, chunk)
            extracted_chunks.append(chunk)
        extracted_jobs.append({**job, "extracted_chunks": extracted_chunks})
    return extracted_jobs


def assemble_exam_papers(
    *,
    ocr_doc: dict[str, Any],
    extracted_jobs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    papers: list[dict[str, Any]] = []
    for job in extracted_jobs:
        standard_paper = job.get("standard_paper")
        if standard_paper:
            paper = standard_paper
        else:
            paper = _assemble_paper_from_chunks(
                paper_id=job["paper_id"],
                original_name=job["original_name"],
                exam_hint=job["exam"],
                extracted_chunks=job["extracted_chunks"],
            )
            if _is_degree_structure(_extract_standard_part_blocks(job["scoped_pages"])):
                paper = _repair_cloze_sections_from_ocr(paper, job["scoped_pages"])
                paper = _repair_reading_sections_from_ocr(paper, job["scoped_pages"])
                paper = _repair_part_structure_from_ocr(paper, job["scoped_pages"])
            standard_paper = _build_standard_exam_from_ocr(
                paper_id=job["paper_id"],
                original_name=job["original_name"],
                exam_hint=job["exam"],
                scoped_pages=job["scoped_pages"],
            )
            if standard_paper and _is_better_standard_paper(standard_paper, paper):
                paper = standard_paper
        paper.setdefault("id", job["paper_id"])
        paper.setdefault("title", job["exam"].get("title") or Path(job["original_name"]).stem)
        paper.setdefault("source", {})
        paper["source"].update(
            {
                "file_name": job["original_name"],
                "collection_id": ocr_doc["id"],
                "page_count": ocr_doc["source"]["page_count"],
                "start_page": job["start_page"],
                "end_page": job["end_page"],
                "ocr_model": ocr_doc["source"]["ocr_model"],
            }
        )
        paper["ocr_pages"] = job["scoped_pages"]
        paper["source"]["unit"] = ocr_doc["source"].get("unit", "页")
        paper["source"]["input_type"] = ocr_doc["source"].get("input_type", "pdf")
        papers.append(paper)
    return papers


def persist_exam_papers(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from paper_quality import validate_paper
    for paper in papers:
        paper["quality"] = validate_paper(paper)
        _paper_json_path(paper["id"]).write_text(
            json.dumps(paper, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return papers


def persist_paper_collection(
    *,
    original_name: str,
    ocr_doc: dict[str, Any],
    papers: list[dict[str, Any]],
) -> dict[str, Any]:
    collection_id = ocr_doc["id"]
    collection = {
        "id": collection_id,
        "type": "paper_collection",
        "title": Path(original_name).stem,
        "source": ocr_doc["source"],
        "ocr_url": f"/api/paper/ocr/{collection_id}",
        "papers": [
            {
                "id": paper["id"],
                "title": paper.get("title", paper["id"]),
                "description": paper.get("description", ""),
                "quality": paper.get("quality"),
                "repaired_from": paper.get("repaired_from"),
                "question_count": _paper_question_count(paper),
                "total_score": paper.get("total_score", 0),
                "paper_url": f"/exam/{paper['id']}",
                "json_url": f"/api/paper/{paper['id']}",
                "start_page": paper.get("source", {}).get("start_page"),
                "end_page": paper.get("source", {}).get("end_page"),
            }
            for paper in papers
        ],
    }
    _paper_json_path(collection_id).write_text(
        json.dumps(collection, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "id": collection_id,
        "type": "paper_collection",
        "collection": collection,
        "papers": papers,
        "paper": papers[0] if papers else None,
    }


def _ocr_json_path(doc_id: str) -> Path:
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", doc_id)
    return OCR_DIR / f"{safe_id}.json"


def read_ocr(doc_id: str) -> dict[str, Any]:
    path = _ocr_json_path(doc_id)
    if not path.exists():
        raise FileNotFoundError(doc_id)
    return json.loads(path.read_text(encoding="utf-8"))


def _split_standard_exam_ranges_from_ocr(
    original_name: str,
    ocr_pages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    starts: list[tuple[int, str]] = []
    for page in ocr_pages:
        page_text = str(page.get("text") or "")
        heading = re.search(
            r"Part\s*(?:I|Ⅰ|1)\s+Vocabulary\s+and\s+Structure",
            page_text,
            flags=re.IGNORECASE,
        )
        if not heading:
            continue
        # Repeated running headings do not start another exam. A fresh paper
        # restarts its question numbering; a continuation carries on at 9, etc.
        tail = page_text[heading.end():]
        first_question = re.search(r"(?m)^\s*(\d+)\s*[.、]\s+", tail)
        if starts and (re.search(r"^[^\n]*(?:continued|续)", tail, re.I)
                       or (first_question and int(first_question[1]) != 1)):
            continue
        page_number = int(page.get("page") or 0)
        if page_number <= 0:
            continue
        title = _extract_standard_exam_title(page_text) or Path(original_name).stem
        starts.append((page_number, title))

    if not starts:
        return []

    starts.sort(key=lambda item: item[0])
    max_page = max(int(page.get("page") or 0) for page in ocr_pages)
    exams = []
    for index, (start_page, title) in enumerate(starts):
        end_page = starts[index + 1][0] - 1 if index + 1 < len(starts) else max_page
        exams.append(
            {
                "title": title,
                "description": "",
                "start_page": start_page,
                "end_page": end_page,
            }
        )
    return exams


def _extract_standard_exam_title(text: str) -> str:
    cleaned_lines = []
    for line in _strip_page_artifacts(text).splitlines():
        stripped = line.strip()
        if stripped:
            cleaned_lines.append(stripped)

    for index, line in enumerate(cleaned_lines):
        if re.search(r"20\d{2}年.*学士学位英语考试", line):
            parts = [line]
            if index + 1 < len(cleaned_lines) and "真题汇编" in cleaned_lines[index + 1]:
                parts.append(cleaned_lines[index + 1])
            return " ".join(parts)
    return ""


def _is_degree_structure(blocks):
    from paper_quality import kind
    expected = {"1": "choice", "2": "cloze", "3": "reading", "4": "translation", "5": "writing"}
    actual = {block["part_number"]: kind(block["title"]) for block in blocks}
    return all(actual.get(number) == category for number, category in expected.items())


def _build_standard_exam_from_ocr(
    *,
    paper_id: str,
    original_name: str,
    exam_hint: dict[str, Any],
    scoped_pages: list[dict[str, Any]],
) -> dict[str, Any] | None:
    from cet4_parser import build_cet4_paper
    cet_paper = build_cet4_paper(paper_id, original_name, exam_hint, scoped_pages)
    if cet_paper:
        return cet_paper
    part_blocks = _extract_standard_part_blocks(scoped_pages)
    part_numbers = {block["part_number"] for block in part_blocks}
    if not {"1", "2", "3", "4", "5"}.issubset(part_numbers) or not _is_degree_structure(part_blocks):
        return None

    sections: list[dict[str, Any]] = []
    for block in part_blocks:
        part_number = block["part_number"]
        if part_number == "1":
            section = _parse_standard_vocabulary_section(block)
            if section:
                sections.append(section)
        elif part_number == "2":
            section = _parse_standard_cloze_section(block)
            if section:
                sections.append(section)
        elif part_number == "3":
            section = _parse_standard_reading_section(block)
            if section:
                sections.append(section)
        elif part_number == "4":
            section = _parse_standard_translation_section(block)
            if section:
                sections.append(section)
        elif part_number == "5":
            previous_numbers = [int(q["number"]) for existing in sections
                                for q in _section_questions(existing)
                                if str(q.get("number", "")).isdigit()]
            section = _parse_standard_writing_section(
                block, default_number=str(max(previous_numbers, default=53) + 1)
            )
            if section:
                sections.append(section)

    if sum(len(_section_questions(section)) for section in sections) < 50:
        return None

    joined_text = "\n".join(str(page.get("text") or "") for page in scoped_pages)
    title = (
        str(exam_hint.get("title") or "").strip()
        or _extract_standard_exam_title(joined_text)
        or Path(original_name).stem
    )
    duration = sum(
        int(block.get("duration_minutes") or 0)
        for block in part_blocks
        if block.get("duration_minutes")
    )
    paper = {
        "id": paper_id,
        "title": title,
        "exam_format": "degree",
        "description": str(exam_hint.get("description") or ""),
        "duration_minutes": duration or 120,
        "total_score": sum(_as_float(section.get("total_score"), 0) for section in sections),
        "sections": sections,
    }
    return _normalize_paper(paper, paper_id, original_name)


def _is_better_standard_paper(
    standard_paper: dict[str, Any],
    current_paper: dict[str, Any],
) -> bool:
    # The CET parser only succeeds after checking all 55 numbered items,
    # option sets and reading groups. Keep its source-backed structure and
    # weights instead of model-invented Part labels or uniform listening scores.
    if standard_paper.get("exam_format") == "cet4":
        return True
    standard_count = _paper_question_count(standard_paper)
    if standard_count < 50:
        return False
    if not {"1", "2", "3", "4", "5"}.issubset(_paper_part_numbers(standard_paper)):
        return False

    current_count = _paper_question_count(current_paper)
    current_parts = _paper_part_numbers(current_paper)
    if current_count != standard_count:
        return True
    if not {"1", "2", "3", "4", "5"}.issubset(current_parts):
        return True
    return _has_zero_score_or_empty_section(current_paper)


def _paper_question_count(paper: dict[str, Any]) -> int:
    return sum(
        len(_section_questions(section))
        for section in paper.get("sections", [])
        if isinstance(section, dict)
    )


def _section_questions(section: dict[str, Any]) -> list[dict[str, Any]]:
    groups = section.get("groups")
    if isinstance(groups, list) and groups:
        questions = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            group_questions = group.get("questions")
            if isinstance(group_questions, list):
                questions.extend(question for question in group_questions if isinstance(question, dict))
        return questions

    section_questions = section.get("questions")
    if isinstance(section_questions, list):
        return [question for question in section_questions if isinstance(question, dict)]
    return []


def _paper_part_numbers(paper: dict[str, Any]) -> set[str]:
    return {
        part_number
        for section in paper.get("sections", [])
        if isinstance(section, dict)
        for part_number in [_part_number_from_title(str(section.get("title") or ""))]
        if part_number
    }


def _has_zero_score_or_empty_section(paper: dict[str, Any]) -> bool:
    for section in paper.get("sections", []):
        if not isinstance(section, dict):
            continue
        if not _section_questions(section):
            return True
        if _as_float(section.get("score"), 0) <= 0 or _as_float(section.get("total_score"), 0) <= 0:
            return True
    return False


def _extract_standard_part_blocks(scoped_pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    text, page_spans = _join_pages_for_parsing(scoped_pages)
    part_pattern = re.compile(
        r"(?m)^[^\nA-Za-z0-9]{0,8}[ \t]*Part[ \t]+([IVXⅠⅡⅢⅣⅤⅥ]+|\d+)[ \t]+([^\n]+)",
        flags=re.IGNORECASE,
    )
    matches = list(part_pattern.finditer(text))
    blocks = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        part_label = str(match.group(1)).translate(
            str.maketrans(
                {
                    "Ⅰ": "I",
                    "Ⅱ": "II",
                    "Ⅲ": "III",
                    "Ⅳ": "IV",
                    "Ⅴ": "V",
                    "Ⅵ": "VI",
                }
            )
        )
        points_match = re.search(r"(\d+(?:\.\d+)?)\s*points?", match[2], re.I)
        duration_match = re.search(r"(\d+)\s*minutes?", match[2], re.I)
        points = float(points_match[1]) if points_match else 0
        duration = int(duration_match[1]) if duration_match else 0
        title = _clean_section_title(f"Part {part_label} {match.group(2)}")
        number = _roman_to_int_label(part_label)
        from paper_quality import kind
        if (blocks and blocks[-1]["part_number"] == number
                and kind(blocks[-1]["title"]) == kind(title)):
            # Keep the original offsets so question source-page links survive.
            previous = blocks[-1]
            previous["end"] = end
            previous["text"] = text[previous["start"]:end]
            continue
        blocks.append(
            {
                "part_number": _roman_to_int_label(part_label),
                "part_label": part_label,
                "title": title,
                "duration_minutes": duration,
                "points": points,
                "text": text[start:end],
                "start": start,
                "end": end,
                "page_spans": page_spans,
            }
        )
    return blocks


def _join_pages_for_parsing(scoped_pages: list[dict[str, Any]]) -> tuple[str, list[dict[str, int]]]:
    chunks: list[str] = []
    page_spans: list[dict[str, int]] = []
    offset = 0
    for page in scoped_pages:
        page_text = str(page.get("text") or "").replace("\xa0", " ")
        start = offset
        chunks.append(page_text)
        offset += len(page_text)
        page_spans.append(
            {
                "page": int(page.get("page") or 0),
                "start": start,
                "end": offset,
            }
        )
        chunks.append("\n\n")
        offset += 2
    return "".join(chunks), page_spans


def _parse_standard_vocabulary_section(block: dict[str, Any]) -> dict[str, Any] | None:
    directions, _ = _split_standard_directions(block["text"])
    questions = _parse_standard_choice_questions(
        block["text"],
        block_start=int(block["start"]),
        page_spans=block["page_spans"],
        min_number=1,
        max_number=20,
        option_ids=("A", "B", "C", "D"),
    )
    if not questions:
        return None
    return {
        "id": "section-vocabulary",
        "title": block["title"],
        "description": directions,
        "total_score": _as_float(block.get("points"), 30) or 30,
        "score": 1.5,
        "questions": questions,
    }


def _parse_standard_cloze_section(block: dict[str, Any]) -> dict[str, Any] | None:
    directions, body = _split_standard_directions(block["text"])
    first_option = re.search(r"(?m)^\s*21\s*[\.\、]\s*(?=[A-C]\s*[\.\、])", body)
    passage = body[: first_option.start()] if first_option else ""
    option_text = body[first_option.start() :] if first_option else body
    cloze_stems = _build_cloze_stem_map(passage)
    questions = _parse_standard_choice_questions(
        option_text,
        block_start=int(block["start"]) + block["text"].find(option_text),
        page_spans=block["page_spans"],
        min_number=21,
        max_number=40,
        option_ids=("A", "B", "C"),
        blank_stems=True,
        cloze_stems=cloze_stems,
    )
    if not questions:
        return None
    return {
        "id": "section-cloze",
        "title": block["title"],
        "description": _join_description_parts(directions, _clean_description_text(passage)),
        "total_score": _as_float(block.get("points"), 20) or 20,
        "score": 1,
        "questions": questions,
    }


def _parse_standard_reading_section(block: dict[str, Any]) -> dict[str, Any] | None:
    directions, body = _split_standard_directions(block["text"])
    passage_pattern = re.compile(r"(?mi)^[^\nA-Za-z0-9]{0,8}(?:[A-D]\s+)?Passage\s+(\d+|One|Two|Three|Four)\b[^\n]*$")
    matches = list(passage_pattern.finditer(body))
    # A repeated 'Passage One — Questions ...' is a continuation, not a new text.
    unique_matches = []
    previous_label = None
    labels = {"one": "1", "two": "2", "three": "3", "four": "4"}
    for candidate in matches:
        label = labels.get(candidate[1].lower(), candidate[1])
        if label != previous_label:
            unique_matches.append(candidate)
        previous_label = label
    matches = unique_matches
    if not matches:
        return None

    groups: list[dict[str, Any]] = []
    all_questions: list[dict[str, Any]] = []
    for match_index, match in enumerate(matches):
        start = match.end()
        end = matches[match_index + 1].start() if match_index + 1 < len(matches) else len(body)
        passage_block = body[start:end]
        question_matches = _standard_number_matches(passage_block, 1, 999)
        if not question_matches:
            continue
        first_question_start = question_matches[0].start()
        passage_text = passage_block[:first_question_start]
        questions_text = passage_block[first_question_start:]
        questions = _parse_standard_choice_questions(
            questions_text,
            block_start=int(block["start"]) + block["text"].find(questions_text),
            page_spans=block["page_spans"],
            min_number=1,
            max_number=999,
            option_ids=("A", "B", "C", "D"),
        )
        if not questions:
            continue
        passage_number = labels.get(match[1].lower(), match[1])
        group_description = _clean_description_text(passage_text)
        groups.append(
            {
                "id": f"reading-passage-{passage_number}",
                "title": f"Passage {passage_number}",
                "description": group_description,
                "questions": questions,
            }
        )
        all_questions.extend(questions)

    if not all_questions:
        return None
    total_score = _as_float(block.get("points"), 20) or 20
    return {
        "id": "section-reading",
        "title": block["title"],
        "description": directions,
        "total_score": total_score,
        "score": round(total_score / len(all_questions), 2),
        "questions": all_questions,
        "groups": groups,
    }


def _parse_standard_translation_section(block: dict[str, Any]) -> dict[str, Any] | None:
    directions, body = _split_standard_directions(block["text"])
    questions = _parse_standard_short_answer_questions(
        body,
        block_start=int(block["start"]) + block["text"].find(body),
        page_spans=block["page_spans"],
        min_number=1,
        max_number=999,
        question_type="short_answer",
    )
    if not questions:
        return None
    return {
        "id": "section-translation",
        "title": block["title"],
        "description": directions,
        "total_score": _as_float(block.get("points"), 15) or 15,
        "score": 3,
        "questions": questions,
    }


def _parse_standard_writing_section(
    block: dict[str, Any], *, default_number: str = "54"
) -> dict[str, Any] | None:
    numbered = re.search(r"(?m)^\s*(\d+)\s*[.、]\s+", block["text"])
    # Outline bullets belong to one composition; they are not question numbers.
    if (numbered and numbered[1] == "1"
            and re.search(r"\boutline\b|提纲|要点", block["text"][:numbered.start()], re.I)):
        numbered = None
    body = block["text"]
    if numbered:
        body = block["text"][:numbered.start()] + block["text"][numbered.end():]
    stem = _clean_line_text(body)
    question = {
        "id": "",
        "number": numbered[1] if numbered else default_number,
        "type": "essay",
        "stem": stem,
        "options": [],
        "answer": None,
        "analysis": "",
        "source_pages": _pages_for_span(
            int(block["start"]),
            int(block["end"]),
            block["page_spans"],
        ),
    }
    return {
        "id": "section-writing",
        "title": block["title"],
        "description": "",
        "total_score": _as_float(block.get("points"), 15) or 15,
        "score": 15,
        "questions": [question],
    }


def _split_standard_directions(block_text: str) -> tuple[str, str]:
    match = re.search(r"Directions\s*:", block_text, flags=re.IGNORECASE)
    if not match:
        return "", block_text

    tail = block_text[match.start() :]
    centre_match = re.search(r"centre\.", tail, flags=re.IGNORECASE)
    if centre_match:
        end = match.start() + centre_match.end()
    else:
        boundary = re.search(
            r"(?m)^\s*(?:[A-D]\s+)?(?:Passage\s+(?:\d+|One|Two|Three|Four)\b|\d+\s*[\.\、])\s*",
            tail,
            flags=re.IGNORECASE,
        )
        paragraph_end = re.search(r"\n\s*\n", tail)
        offsets = [m.start() for m in (boundary, paragraph_end) if m]
        end = match.start() + min(offsets) if offsets else len(block_text)

    directions = _clean_description_text(block_text[match.start() : end])
    body = block_text[end:]
    return directions, body


def _parse_standard_choice_questions(
    text: str,
    *,
    block_start: int,
    page_spans: list[dict[str, int]],
    min_number: int,
    max_number: int,
    option_ids: tuple[str, ...],
    blank_stems: bool = False,
    cloze_stems: dict[int, str] | None = None,
) -> list[dict[str, Any]]:
    matches = _standard_number_matches(text, min_number, max_number)
    questions = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        raw_block = text[match.start() : end]
        parsed = _parse_standard_choice_block(raw_block, option_ids)
        if not parsed:
            continue
        number = int(parsed["number"])
        if blank_stems:
            parsed["stem"] = (cloze_stems or {}).get(number, f"Blank {number}")
        parsed["source_pages"] = _pages_for_span(
            block_start + match.start(),
            block_start + end,
            page_spans,
        )
        questions.append(parsed)
    return questions


def _build_cloze_stem_map(
    passage: str,
    *,
    min_number: int = 21,
    max_number: int = 40,
) -> dict[int, str]:
    text = _clean_inline_text(passage)
    if not text:
        return {}

    stems: dict[int, str] = {}
    for number in range(min_number, max_number + 1):
        match = _find_cloze_blank(text, number)
        if not match:
            continue
        context = _extract_cloze_context_sentence(text, match.start(), match.end())
        context = _normalize_cloze_blank_markers(context, min_number, max_number)
        if context:
            stems[number] = context
    return stems


def _find_cloze_blank(text: str, number: int) -> re.Match[str] | None:
    patterns = [
        rf"_+\s*{number}\s*_+",
        rf"(?<![A-Za-z0-9_$]){number}(?![A-Za-z0-9_])",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match
    return None


def _extract_cloze_context_sentence(text: str, start: int, end: int) -> str:
    left_matches = list(
        re.finditer(r"[.!?。！？][\"”’')\]]?\s+", text[:start])
    )
    context_start = left_matches[-1].end() if left_matches else 0

    right_match = re.search(r"[.!?。！？][\"”’')\]]?(?=\s|$)", text[end:])
    context_end = end + right_match.end() if right_match else len(text)

    context = text[context_start:context_end].strip()
    if len(context) <= 360:
        return context

    window_start = max(0, start - 140)
    window_end = min(len(text), end + 180)
    prefix = "..." if window_start > 0 else ""
    suffix = "..." if window_end < len(text) else ""
    return f"{prefix}{text[window_start:window_end].strip()}{suffix}"


def _normalize_cloze_blank_markers(
    text: str,
    min_number: int,
    max_number: int,
) -> str:
    normalized = str(text or "")
    for number in range(min_number, max_number + 1):
        normalized = re.sub(rf"_+\s*{number}\s*_+", f"__{number}__", normalized)
        normalized = re.sub(
            rf"(?<![A-Za-z0-9_$]){number}(?![A-Za-z0-9_])",
            f"__{number}__",
            normalized,
        )
    return re.sub(r"\s+", " ", normalized).strip()


def _parse_standard_short_answer_questions(
    text: str,
    *,
    block_start: int,
    page_spans: list[dict[str, int]],
    min_number: int,
    max_number: int,
    question_type: str,
) -> list[dict[str, Any]]:
    matches = _standard_number_matches(text, min_number, max_number)
    questions = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        raw_block = text[match.start() : end]
        question_match = re.match(r"^\s*(\d{1,3})\s*[\.\、]\s*([\s\S]*)$", raw_block)
        if not question_match:
            continue
        stem = _clean_inline_text(question_match.group(2))
        if not stem:
            continue
        questions.append(
            {
                "id": "",
                "number": question_match.group(1),
                "type": question_type,
                "stem": stem,
                "options": [],
                "answer": None,
                "analysis": "",
                "source_pages": _pages_for_span(
                    block_start + match.start(),
                    block_start + end,
                    page_spans,
                ),
            }
        )
    return questions


def _standard_number_matches(text: str, min_number: int, max_number: int) -> list[re.Match[str]]:
    matches = []
    for match in re.finditer(r"(?m)^\s*(\d{1,3})\s*[\.\、]\s+", text):
        number = int(match.group(1))
        if min_number <= number <= max_number:
            matches.append(match)
    return matches


def _parse_standard_choice_block(
    raw_block: str,
    option_ids: tuple[str, ...],
) -> dict[str, Any] | None:
    question_match = re.match(r"^\s*(\d{1,3})\s*[\.\、]\s*([\s\S]*)$", raw_block)
    if not question_match:
        return None

    number = question_match.group(1)
    remainder = question_match.group(2)
    option_matches = _standard_option_matches(remainder, option_ids)
    if option_matches:
        stem = _clean_inline_text(remainder[: option_matches[0].start()])
        options = []
        for index, option_match in enumerate(option_matches):
            option_start = option_match.end()
            option_end = (
                option_matches[index + 1].start()
                if index + 1 < len(option_matches)
                else len(remainder)
            )
            options.append(
                {
                    "id": option_match.group(1),
                    "text": _clean_inline_text(remainder[option_start:option_end]),
                }
            )
    else:
        stem = _clean_inline_text(remainder)
        options = []

    return {
        "id": "",
        "number": number,
        "type": "single_choice" if options else "unknown",
        "stem": stem,
        "options": options,
        "answer": None,
        "analysis": "",
        "source_pages": [],
    }


def _standard_option_matches(
    text: str,
    option_ids: tuple[str, ...],
) -> list[re.Match[str]]:
    option_chars = "".join(re.escape(option_id) for option_id in option_ids)
    return list(
        re.finditer(
            rf"(?<![A-Za-z0-9])([{option_chars}])\s*[\.\、]\s+",
            text,
        )
    )


def _pages_for_span(
    start: int,
    end: int,
    page_spans: list[dict[str, int]],
) -> list[int]:
    pages = [
        span["page"]
        for span in page_spans
        if span["page"] and start < span["end"] and end > span["start"]
    ]
    return pages or [span["page"] for span in page_spans if span["page"]][:1]


def _clean_inline_text(text: str) -> str:
    cleaned = _strip_page_artifacts(text)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _clean_description_text(text: str) -> str:
    cleaned = _strip_page_artifacts(text)
    paragraphs = []
    for paragraph in re.split(r"\n\s*\n", cleaned):
        collapsed = re.sub(r"\s+", " ", paragraph).strip()
        if collapsed:
            paragraphs.append(collapsed)
    return "\n\n".join(paragraphs)


def _clean_line_text(text: str) -> str:
    cleaned = _strip_page_artifacts(text)
    lines = []
    for line in cleaned.splitlines():
        stripped = re.sub(r"[ \t]+", " ", line).strip()
        if stripped:
            lines.append(stripped)
    return "\n".join(lines)


async def _split_exams(
    llm: LLMManager,
    original_name: str,
    ocr_pages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    standard_exams = _split_standard_exam_ranges_from_ocr(original_name, ocr_pages)
    if standard_exams:
        return standard_exams

    ocr_text = _format_ocr_pages(ocr_pages)
    prompt = f"""请根据 OCR 页级文字判断这份文档包含几套独立试卷，并给出每套试卷的页码范围。

只输出 JSON，不要 Markdown，不要解释。

JSON Schema：
{{
  "exams": [
    {{
      "title": "试卷标题",
      "description": "",
      "start_page": 1,
      "end_page": 5
    }}
  ]
}}

判断规则：
1. 如果目录显示多套题，即使只处理了部分页面，也要按当前 OCR 中实际出现的页面切分。
2. 遇到“真题汇编（一）”“真题汇编（二）”“2025年…”“2024年…”等新标题，通常是新套卷开始。
3. 封面、目录页不要单独成卷，可以归入第一套卷之前的上下文，但 start_page 应尽量指向真正试卷开始页。
4. end_page 必须覆盖该套卷最后一个已出现页面，允许题目跨页。
5. 如果只发现一套卷，返回一个 exams 元素。

文件名：{original_name}

OCR：
{ocr_text}
"""
    async def request_split() -> dict[str, Any]:
        response = await llm.invoke(
            [{"role": "user", "content": prompt}],
            model_id="default",
            temperature=0,
            max_tokens=4096,
        )
        return _parse_json_object(_response_text(response))

    data = await _retry_generation_call(
        request_split,
        operation_name="试卷范围切分",
    )
    exams = data.get("exams")
    if not isinstance(exams, list) or not exams:
        return [
            {
                "title": Path(original_name).stem,
                "description": "",
                "start_page": 1,
                "end_page": len(ocr_pages),
            }
        ]
    normalized = []
    max_page = len(ocr_pages)
    for exam in exams:
        if not isinstance(exam, dict):
            continue
        start_page = max(1, min(max_page, int(_as_float(exam.get("start_page"), 1))))
        end_page = max(start_page, min(max_page, int(_as_float(exam.get("end_page"), max_page))))
        normalized.append(
            {
                "title": str(exam.get("title") or Path(original_name).stem),
                "description": str(exam.get("description") or ""),
                "start_page": start_page,
                "end_page": end_page,
            }
        )
    return normalized or [
        {
            "title": Path(original_name).stem,
            "description": "",
            "start_page": 1,
            "end_page": max_page,
        }
    ]


def _format_ocr_pages(ocr_pages: list[dict[str, Any]]) -> str:
    return "\n\n".join(
        f"===== 第 {page['page']} 页 =====\n{page['text']}" for page in ocr_pages
    )


def _paper_json_path(paper_id: str) -> Path:
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", paper_id)
    return PAPER_DIR / f"{safe_id}.json"


def _render_pdf_pages(
    pdf_path: Path,
    output_dir: Path,
    dpi: int,
    max_pages: int | None,
) -> list[Path]:
    try:
        import fitz
    except ImportError as exc:
        raise PaperGenerationError("缺少 PyMuPDF，请运行: uv pip install pymupdf") from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    try:
        page_count = len(doc) if max_pages is None else min(len(doc), max_pages)
        zoom = dpi / 72
        matrix = fitz.Matrix(zoom, zoom)
        images: list[Path] = []
        for page_index in range(page_count):
            page = doc.load_page(page_index)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            image_path = output_dir / f"page-{page_index + 1:03d}.jpg"
            pix.save(image_path)
            images.append(image_path)
        return images
    finally:
        doc.close()


async def _ocr_page(
    llm: LLMManager,
    image_path: Path,
    page_number: int,
    total_pages: int,
) -> str:
    prompt = f"""你是严谨的试卷 OCR 助手。请识别这张 PDF 页面中的全部可见文字。

要求：
1. 保留题号、选项编号、表格、代码块、公式和分段。
2. 不要总结，不要补充答案，不要改写题意。
3. 无法识别的局部用 [无法识别] 标注。
4. 输出纯文本，不要 Markdown 围栏。
5. 按阅读顺序还原多栏内容，保留每道题的完整题干及对应选项，不能只输出选项。
6. 同一行的 Part/Section/Passage 标题合为一行；保留原来的罗马数字、题号和选项字母。
7. 选词填空的每个编号空位写为 __题号__，词库逐项保留；阅读匹配的段落字母和全文必须保留。
8. 只识别本页可见内容，跨页的未完句也原样保留，不能猜写下一页。听力原卷若只有选项，不编造音频中的问题。

当前页：{page_number}/{total_pages}
"""
    async def request_ocr() -> str:
        response = await llm.invoke(
            [
                {
                    "role": "user",
                    "content": [
                        ImageInput.from_file(image_path, detail="high").to_openai_format(),
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            model_id="vision",
            temperature=0,
            max_tokens=8192,
        )
        text = _response_text(response).strip()
        if not text:
            raise PaperGenerationError("视觉模型返回了空 OCR 文本")
        return text

    return await _retry_generation_call(
        request_ocr,
        operation_name=f"OCR 第 {page_number}/{total_pages} 页",
    )


async def _build_exam_json(
    llm: LLMManager,
    paper_id: str,
    original_name: str,
    ocr_pages: list[dict[str, Any]],
    exam_hint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ocr_text = _format_ocr_pages(ocr_pages)
    exam_hint = exam_hint or {}
    prompt = f"""请把下面“已经完成 OCR 的连续页级文字稿”整理成一个可用于前端渲染考试页面的 JSON。

只输出 JSON，不要 Markdown，不要解释。

JSON Schema：
{{
  "id": "{paper_id}",
  "title": "试卷标题",
  "description": "可为空字符串",
  "duration_minutes": 120,
  "total_score": 100,
  "sections": [
    {{
      "id": "section-1",
      "title": "一、单项选择题",
      "description": "",
      "total_score": 30,
      "score": 1.5,
      "questions": [
        {{
          "id": "q1",
          "number": "1",
          "type": "single_choice|multiple_choice|true_false|short_answer|essay|programming|fill_blank|unknown",
          "stem": "题干",
          "options": [
            {{"id": "A", "text": "选项内容"}}
          ],
          "answer": null,
          "analysis": "",
          "source_pages": [1]
        }}
      ],
      "groups": [
        {{
          "id": "passage-1",
          "title": "Passage 1",
          "description": "阅读文章或材料",
          "questions": []
        }}
      ]
    }}
  ]
}}

整理规则：
1. 尽量按原试卷大题分 section；section 是 Part/大题，不要把同一 Part 拆成多个 section。
2. 选择题必须拆出 options；非选择题 options 为空数组。
3. 如果 OCR 中有答案或解析，填入 answer/analysis；没有就用 null 和空字符串。
4. 每个 section 用 total_score 表示该部分总分，用 score 表示该部分每题分数；questions 中不要写 score。
5. 保留代码、表格、公式的原意。
6. 不要编造题目，无法判断的题型用 unknown。
7. 题目可能跨页，必须把连续页中的同一道题合并完整。例如上一页末尾只有 A/B，下一页开头出现 C/D 时，要放进同一道题的 options。
8. 不要把封面、目录、页脚、页码、内部资料水印当作题目。
9. 如果一个 section 内有多个材料/题干组，例如 Reading 的 Passage 1、Passage 2，必须使用 section.groups；每个 group.description 放该材料正文，每个 group.questions 放该材料对应题目。
10. section.description 只放 Directions/总说明；阅读文章不要混在 section.description。
11. 为兼容统计，使用 groups 的 section 也可以在 section.questions 放全部题目的扁平列表，但分组关系必须以 groups 为准。
12. 仅整理当前套卷范围内的题目，不要混入其它套卷。

文件名：{original_name}
当前套卷提示：{json.dumps(exam_hint, ensure_ascii=False)}

OCR 文本：
{ocr_text}
"""
    async def request_exam_json() -> dict[str, Any]:
        response = await llm.invoke(
            [{"role": "user", "content": prompt}],
            model_id="default",
            temperature=0.1,
            max_tokens=12000,
        )
        return _parse_json_object(_response_text(response))

    data = await _retry_generation_call(
        request_exam_json,
        operation_name=f"试卷 JSON 生成（{exam_hint.get('title') or paper_id}）",
    )
    return _normalize_paper(data, paper_id, original_name)


async def _build_exam_json_chunked(
    llm: LLMManager,
    paper_id: str,
    original_name: str,
    ocr_pages: list[dict[str, Any]],
    exam_hint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    exam_hint = exam_hint or {}
    chunks = _make_page_windows(ocr_pages, window_size=2, step=1)
    extracted_chunks = []
    for chunk_index, chunk_pages in enumerate(chunks, start=1):
        extracted_chunks.append(
            await _extract_questions_from_chunk(
                llm,
                original_name=original_name,
                exam_hint=exam_hint,
                chunk_pages=chunk_pages,
                chunk_index=chunk_index,
                chunk_count=len(chunks),
            )
        )

    return _assemble_paper_from_chunks(
        paper_id=paper_id,
        original_name=original_name,
        exam_hint=exam_hint,
        extracted_chunks=extracted_chunks,
    )


def _make_page_windows(
    pages: list[dict[str, Any]],
    *,
    window_size: int,
    step: int,
) -> list[list[dict[str, Any]]]:
    if not pages:
        return []
    windows = []
    index = 0
    while index < len(pages):
        window = pages[index : index + window_size]
        if window:
            windows.append(window)
        if index + window_size >= len(pages):
            break
        index += step
    return windows


async def _extract_questions_from_chunk(
    llm: LLMManager,
    *,
    original_name: str,
    exam_hint: dict[str, Any],
    chunk_pages: list[dict[str, Any]],
    chunk_index: int,
    chunk_count: int,
) -> dict[str, Any]:
    page_numbers = [int(page["page"]) for page in chunk_pages]
    ocr_text = _format_ocr_pages(chunk_pages)
    prompt = f"""请从下面连续 OCR 页中提取试题，输出 JSON。

只输出 JSON，不要 Markdown，不要解释。

JSON Schema：
{{
  "sections": [
    {{
      "title": "Part I Vocabulary and Structure",
      "description": "",
      "total_score": 30,
      "score": 1.5,
      "questions": [
        {{
          "number": "1",
          "type": "single_choice|multiple_choice|true_false|short_answer|essay|programming|fill_blank|unknown",
          "stem": "题干",
          "options": [{{"id": "A", "text": "选项"}}],
          "answer": null,
          "analysis": "",
          "source_pages": [3]
        }}
      ],
      "groups": [
        {{
          "title": "Passage 1",
          "description": "阅读文章或材料",
          "questions": []
        }}
      ]
    }}
  ]
}}

提取规则：
1. 只提取题目，不要提取封面、目录、水印、页码、说明文本本身。
2. 题目可能跨页；如果本窗口含有同一道题的后续选项或后续段落，必须合并完整。
3. 因为窗口有重叠，允许重复提取同一道题；后续程序会按题号合并。不要为了避免重复而漏题。
4. 选择题必须尽量提取 A/B/C/D 全部选项；如果窗口内确实没有完整选项，保留已见内容。
5. 每个 Part 的标题必须保留时间和总分，例如 "Part I Vocabulary and Structure (20 minutes, 30 points)"。
6. 每个 Part 的 Directions 不是题目，必须放进对应 section.description 的开头。
7. 同一个 Part 内通常每题分值一致；section.total_score 写该 Part 总分，section.score 写每题分数；questions 中不要写 score。
8. 阅读理解中 Passage/文章正文不是题目；按原卷实际 Part 编号和标题分组，不要假定阅读一定是 Part III。用 section.groups 表达各篇文章及其对应题目，保留完整文章和每个问题的题干。
9. 每个 group.description 放对应 Passage 文章正文，每个 group.questions 放该 Passage 后面的题目；section.description 只放 Directions/总说明。
10. 阅读题 question.stem 只能是具体问题或未完成陈述，不要把整篇文章重复塞进 stem。
11. 完形填空必须把 Directions 和完整篇章放进 section.description，questions 只列每个空的选项题；不要把 21-40 或 21-31 当成一道题。
12. 如果本窗口只有跨页题目的续文，也要提取该题，并保留题号。
13. 输出尽量紧凑，不要重复说明，不要生成额外字段。

文件名：{original_name}
当前套卷：{json.dumps(exam_hint, ensure_ascii=False)}
窗口：{chunk_index}/{chunk_count}
页码：{page_numbers}

OCR：
{ocr_text}
"""
    async def request_chunk() -> dict[str, Any]:
        response = await llm.invoke(
            [{"role": "user", "content": prompt}],
            model_id="default",
            temperature=0,
            max_tokens=8192,
        )
        parsed = _parse_json_object(_response_text(response))
        if not isinstance(parsed.get("sections"), list):
            raise PaperGenerationError("题目整理结果缺少完整的大题列表，请重试。")
        return parsed

    data = await _retry_generation_call(
        request_chunk,
        operation_name=f"题目提取窗口 {chunk_index}/{chunk_count}（页 {page_numbers}）",
    )
    return {
        "pages": page_numbers,
        "data": data,
    }


def _assemble_paper_from_chunks(
    *,
    paper_id: str,
    original_name: str,
    exam_hint: dict[str, Any],
    extracted_chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    sections_by_title: dict[str, dict[str, Any]] = {}
    question_order: list[tuple[str, str]] = []
    warnings = []

    for chunk in extracted_chunks:
        data = chunk.get("data") or {}
        if isinstance(data, dict) and data.get("_error"):
            warnings.append(
                {
                    "pages": data.get("_failed_pages") or chunk.get("pages"),
                    "error": data.get("_error"),
                }
            )
        sections = data.get("sections") if isinstance(data, dict) else []
        if not isinstance(sections, list):
            continue
        for section in sections:
            if not isinstance(section, dict):
                continue
            raw_title = str(section.get("title") or "题目")
            title = _clean_section_title(raw_title)
            section_key = _canonical_section_key(title)
            # Adjacent extraction windows can invent a different Part numeral
            # for the same continuation. Merge only with matching question
            # evidence on overlapping source pages, not by title similarity.
            from paper_quality import kind
            if section_key not in sections_by_title:
                incoming = _section_questions(section)
                for known_key, known in sections_by_title.items():
                    if kind(known["title"]) != kind(title) or kind(title) == "other":
                        continue
                    if any(_same_source_choice(old, new, chunk.get("pages", []))
                           for old in known["questions_by_number"].values() for new in incoming):
                        section_key = known_key
                        break
            target = sections_by_title.setdefault(
                section_key,
                {
                    "id": f"section-{len(sections_by_title) + 1}",
                    "title": title,
                    "description": str(section.get("description") or ""),
                    "total_score": _as_float(section.get("total_score"), 0),
                    "score": _as_float(section.get("score"), 0),
                    "questions_by_number": {},
                    "groups_by_title": {},
                },
            )
            incoming_description = str(section.get("description") or "")
            if len(incoming_description) > len(str(target.get("description") or "")):
                target["description"] = incoming_description
            if _as_float(section.get("total_score"), 0) > _as_float(target.get("total_score"), 0):
                target["total_score"] = _as_float(section.get("total_score"), 0)
            if _as_float(section.get("score"), 0) > _as_float(target.get("score"), 0):
                target["score"] = _as_float(section.get("score"), 0)
            questions = _section_questions(section)
            question_groups = {}
            for group in section.get("groups") or []:
                group_title = str(group.get("title") or "阅读文章")
                group_key = _canonical_section_key(group_title)
                saved_group = target["groups_by_title"].setdefault(group_key, {"title": group_title, "description": "", "keys": []})
                saved_group["description"] = _merge_passage_text(saved_group["description"], str(group.get("description") or ""))
                for question in group.get("questions", []):
                    question_groups[id(question)] = group_key
            for question in questions:
                if not isinstance(question, dict):
                    continue
                number = str(question.get("number") or "").strip()
                stem = str(question.get("stem") or "").strip()
                if not number and not stem:
                    continue
                if _is_cloze_title(title) and _is_range_number(number):
                    continue
                group_key = question_groups.get(id(question))
                key = (f"{group_key}:" if group_key else "") + (number or f"unnumbered-{len(question_order) + 1}")
                existing = target["questions_by_number"].get(key)
                if existing and stem and existing.get("stem") and not _is_blank_label(stem) and not _is_blank_label(existing["stem"]):
                    similarity = SequenceMatcher(None, re.sub(r"\s+", "", stem).casefold(), re.sub(r"\s+", "", existing["stem"]).casefold()).ratio()
                    if similarity < 0.65 and not _same_source_choice(existing, question, chunk.get("pages", [])):
                        key = f"{key}:variant-{len(question_order) + 1}"
                        existing = None
                normalized = {
                    "id": "",
                    "number": number or key,
                    "type": str(question.get("type") or "unknown"),
                    "stem": stem,
                    "options": _normalize_options(question.get("options")),
                    "answer": question.get("answer"),
                    "analysis": str(question.get("analysis") or ""),
                    "source_pages": _normalize_pages(question.get("source_pages") or chunk.get("pages")),
                }
                if existing is None:
                    target["questions_by_number"][key] = normalized
                    question_order.append((section_key, key))
                else:
                    target["questions_by_number"][key] = _merge_question(existing, normalized)
                if group_key and key not in target["groups_by_title"][group_key]["keys"]:
                    target["groups_by_title"][group_key]["keys"].append(key)

    sections = []
    q_index = 1
    for section_key, section in sections_by_title.items():
        questions = []
        for ordered_title, key in question_order:
            if ordered_title != section_key:
                continue
            question = section["questions_by_number"].get(key)
            if not question:
                continue
            question["id"] = f"q{q_index}"
            q_index += 1
            questions.append(question)
        sections.append(
            {
                "id": section["id"],
                "title": section["title"],
                "description": section.get("description", ""),
                "total_score": _as_float(section.get("total_score"), 0),
                "score": _as_float(section.get("score"), 0),
                "questions": questions,
            }
        )
        if section["groups_by_title"]:
            groups = [{"title": group["title"], "description": group["description"],
                       "questions": [section["questions_by_number"][key] for key in group["keys"]]}
                      for group in section["groups_by_title"].values()]
            grouped_ids = {q["id"] for group in groups for q in group["questions"]}
            ungrouped = [q for q in questions if q["id"] not in grouped_ids]
            if ungrouped:
                groups.append({"title": "其他题目", "description": section.get("description", ""), "questions": ungrouped})
            sections[-1]["groups"] = groups

    paper = {
        "id": paper_id,
        "title": str(exam_hint.get("title") or Path(original_name).stem),
        "description": str(exam_hint.get("description") or ""),
        "duration_minutes": 120,
        "total_score": sum(_as_float(section.get("total_score"), 0) for section in sections),
        "sections": sections,
        "warnings": warnings,
    }
    return _normalize_paper(paper, paper_id, original_name)


def _same_source_choice(existing: dict, incoming: dict, incoming_pages: list) -> bool:
    if str(existing.get("number")) != str(incoming.get("number")):
        return False
    left = set(_normalize_pages(existing.get("source_pages")))
    right = set(_normalize_pages(incoming.get("source_pages") or incoming_pages))
    if not left.intersection(right):
        return False
    def options(q):
        return {o["id"]: re.sub(r"\s+", " ", o["text"]).strip().casefold()
                for o in _normalize_options(q.get("options"))}
    a, b = options(existing), options(incoming)
    return len(a) >= 2 and a == b


def _merge_passage_text(existing: str, incoming: str) -> str:
    left, right = existing.split(), incoming.split()
    if not left or " ".join(left) in " ".join(right):
        return incoming
    if not right or " ".join(right) in " ".join(left):
        return existing
    for size in range(min(len(left), len(right)), 7, -1):
        if left[-size:] == right[:size]:
            return " ".join(left + right[size:])
    return existing + "\n\n" + incoming


def _merge_question(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    current_stem = str(merged.get("stem") or "")
    incoming_stem = str(incoming.get("stem") or "")
    if _is_blank_label(current_stem) and not _is_blank_label(incoming_stem):
        merged["stem"] = incoming.get("stem") or merged.get("stem", "")
    elif not _is_blank_label(current_stem) and _is_blank_label(incoming_stem):
        pass
    elif len(incoming_stem) > len(current_stem):
        merged["stem"] = incoming.get("stem") or merged.get("stem", "")
    if merged.get("type") in ("", "unknown") and incoming.get("type"):
        merged["type"] = incoming["type"]
    merged["options"] = _merge_options(merged.get("options", []), incoming.get("options", []))
    if not merged.get("answer") and incoming.get("answer"):
        merged["answer"] = incoming["answer"]
    if len(str(incoming.get("analysis") or "")) > len(str(merged.get("analysis") or "")):
        merged["analysis"] = incoming.get("analysis") or ""
    merged["source_pages"] = sorted(set(_normalize_pages(merged.get("source_pages")) + _normalize_pages(incoming.get("source_pages"))))
    return merged


def _clean_section_title(title: str) -> str:
    roman_map = str.maketrans(
        {
            "Ⅰ": "I",
            "Ⅱ": "II",
            "Ⅲ": "III",
            "Ⅳ": "IV",
            "Ⅴ": "V",
            "Ⅵ": "VI",
        }
    )
    cleaned = str(title or "题目").translate(roman_map)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or "题目"


def _canonical_section_key(title: str) -> str:
    cleaned = _clean_section_title(title)
    cleaned = re.sub(r"^part\s+", "part ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[（(][^()（）]*(?:minutes?|points?|分钟|分)[^()（）]*[）)]", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned.casefold()


def _part_number_from_title(title: str) -> str:
    cleaned = _clean_section_title(title)
    match = re.search(r"\bPart\s+([IVX]+|\d+)\b", cleaned, flags=re.IGNORECASE)
    if not match:
        return ""
    return _roman_to_int_label(match.group(1))


def _roman_to_int_label(value: str) -> str:
    text = str(value or "").strip().upper()
    if text.isdigit():
        return text
    roman_values = {"I": 1, "V": 5, "X": 10}
    total = 0
    previous = 0
    for char in reversed(text):
        current = roman_values.get(char, 0)
        if current < previous:
            total -= current
        else:
            total += current
        previous = current
    return str(total) if total else text


def _is_cloze_title(title: str) -> bool:
    cleaned = _clean_section_title(title).casefold()
    return "cloze" in cleaned or "完形" in cleaned or "完型" in cleaned


def _is_range_number(number: str) -> bool:
    return bool(re.fullmatch(r"\d+\s*[-~—–]\s*\d+", str(number or "").strip()))


def _is_blank_label(stem: str) -> bool:
    return bool(re.fullmatch(r"(?:blank|空)\s*\d+", str(stem or "").strip(), flags=re.IGNORECASE))


def _repair_part_structure_from_ocr(
    paper: dict[str, Any],
    scoped_pages: list[dict[str, Any]],
) -> dict[str, Any]:
    sections = paper.get("sections")
    if not isinstance(sections, list):
        return paper

    part_meta = _extract_part_metadata_from_pages(scoped_pages)
    if not part_meta:
        return paper

    sections[:] = _dedupe_sections_by_part(sections)
    for section in sections:
        part_number = _part_number_from_title(str(section.get("title") or ""))
        meta = part_meta.get(part_number)
        if not meta:
            continue
        original_title = str(section.get("title") or "")
        if meta.get("title") and not _is_reading_title(original_title):
            section["title"] = meta["title"]
        if meta.get("directions"):
            existing_description = str(section.get("description") or "").strip()
            if _is_reading_title(str(section.get("title") or "")):
                passage_description = _remove_leading_directions(existing_description)
                section["description"] = _join_description_parts(meta["directions"], passage_description)
            elif _is_cloze_title(str(section.get("title") or "")):
                passage_description = _remove_leading_directions(existing_description)
                section["description"] = _join_description_parts(meta["directions"], passage_description)
            elif not existing_description or len(meta["directions"]) > len(existing_description):
                section["description"] = meta["directions"]

    _apply_part_scores(sections, part_meta)
    return _normalize_paper(paper, str(paper.get("id") or ""), str(paper.get("title") or ""))


def _extract_part_metadata_from_pages(scoped_pages: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    text = _strip_page_artifacts("\n\n".join(str(page.get("text") or "") for page in scoped_pages))
    part_pattern = re.compile(
        r"(?m)^\s*Part\s+([IVXⅠⅡⅢⅣⅤⅥ]+|\d+)\s+([^\n（(]*?)(?:[（(]\s*(\d+)\s*minutes?\s*[,，]\s*(\d+(?:\.\d+)?)\s*points?\s*[）)])?\s*$",
        flags=re.IGNORECASE,
    )
    matches = list(part_pattern.finditer(text))
    meta: dict[str, dict[str, Any]] = {}
    for index, match in enumerate(matches):
        part_number = _roman_to_int_label(str(match.group(1)).translate(str.maketrans({
            "Ⅰ": "I",
            "Ⅱ": "II",
            "Ⅲ": "III",
            "Ⅳ": "IV",
            "Ⅴ": "V",
            "Ⅵ": "VI",
        })))
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[start:end]
        directions = _extract_directions_from_block(block)
        duration = int(match.group(3)) if match.group(3) else None
        points = _as_float(match.group(4), 0) if match.group(4) else None
        title_suffix = ""
        if duration is not None and points is not None:
            title_suffix = f" ({duration} minutes, {_format_score_number(points)} points)"
        title = _clean_section_title(f"Part {match.group(1)} {match.group(2)}{title_suffix}")
        meta[part_number] = {
            "part_number": part_number,
            "title": title,
            "duration_minutes": duration,
            "points": points,
            "directions": directions,
        }
    return meta


def _extract_directions_from_block(block: str) -> str:
    match = re.search(r"Directions\s*:", block, flags=re.IGNORECASE)
    if not match:
        return ""
    tail = block[match.start() :]
    centre_match = re.search(r"centre\.", tail, flags=re.IGNORECASE)
    if centre_match:
        directions = tail[: centre_match.end()]
        return re.sub(r"\s+\n", "\n", _strip_page_artifacts(directions)).strip()

    boundary = re.search(
        r"(?m)^\s*(?:Passage\s+\d+|\d+\s*[\.\、])\s+",
        tail,
        flags=re.IGNORECASE,
    )
    directions = tail[: boundary.start()] if boundary else tail
    return re.sub(r"\s+\n", "\n", _strip_page_artifacts(directions)).strip()


def _dedupe_sections_by_part(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    targets = {}
    for section in sections:
        if not isinstance(section, dict):
            continue
        part = _part_number_from_title(str(section.get("title") or ""))
        if not part or section.get("groups") or _is_reading_title(str(section.get("title") or "")):
            result.append(section)
            continue
        target = targets.get(part)
        if target is None:
            target = {**section, "questions": []}
            targets[part] = target
            result.append(target)
        if len(str(section.get("description") or "")) > len(str(target.get("description") or "")):
            target["description"] = section["description"]
        for question in _section_questions(section):
            number = str(question.get("number") or "")
            stem = re.sub(r"\s+", "", str(question.get("stem") or "")).casefold()
            match = None
            for index, existing in enumerate(target["questions"]):
                previous = re.sub(r"\s+", "", str(existing.get("stem") or "")).casefold()
                if number and str(existing.get("number")) == number and (stem == previous or SequenceMatcher(None, stem, previous).ratio() >= 0.65):
                    match = index
                    break
            if match is None:
                target["questions"].append(question)
            else:
                target["questions"][match] = _merge_question(target["questions"][match], question)
    return result


def _apply_part_scores(
    sections: list[dict[str, Any]],
    part_meta: dict[str, dict[str, Any]],
) -> None:
    sections_by_part: dict[str, list[dict[str, Any]]] = {}
    for section in sections:
        part_number = _part_number_from_title(str(section.get("title") or ""))
        if part_number:
            sections_by_part.setdefault(part_number, []).append(section)

    for part_number, grouped_sections in sections_by_part.items():
        points = part_meta.get(part_number, {}).get("points")
        if not points:
            continue
        questions = [
            question
            for section in grouped_sections
            for question in _section_questions(section)
            if isinstance(question, dict)
        ]
        if not questions:
            continue
        score = round(_as_float(points, 0) / len(questions), 2)
        for section in grouped_sections:
            section_questions = _section_questions(section)
            if not section_questions:
                continue
            section["score"] = score
            section["total_score"] = round(score * len(section_questions), 2)
        delta = round(_as_float(points, 0) - score * len(questions), 2)
        if delta and grouped_sections:
            grouped_sections[-1]["total_score"] = round(
                _as_float(grouped_sections[-1].get("total_score"), 0) + delta,
                2,
            )


def _remove_leading_directions(text: str) -> str:
    raw = str(text or "").strip()
    if not re.match(r"Directions\s*:", raw, flags=re.IGNORECASE):
        return raw
    centre_match = re.search(r"centre\.", raw, flags=re.IGNORECASE)
    if centre_match:
        return raw[centre_match.end() :].strip()
    parts = re.split(r"\n\s*\n", raw, maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def _join_description_parts(*parts: str) -> str:
    cleaned = [str(part).strip() for part in parts if str(part or "").strip()]
    return "\n\n".join(cleaned)


def _repair_reading_sections_from_ocr(
    paper: dict[str, Any],
    scoped_pages: list[dict[str, Any]],
) -> dict[str, Any]:
    reading_text = _extract_reading_text_from_pages(scoped_pages)
    if not reading_text:
        return paper

    passages = _parse_reading_passages(reading_text)
    if not passages:
        return paper

    sections = paper.get("sections")
    if not isinstance(sections, list):
        return paper

    reading_indexes = [
        index for index, section in enumerate(sections) if _is_reading_title(str(section.get("title") or ""))
    ]
    if not reading_indexes:
        return paper

    base_section = sections[reading_indexes[0]]
    other_sections = [
        section for index, section in enumerate(sections) if index not in set(reading_indexes)
    ]
    repaired_section = _build_reading_section_from_passages(base_section, passages)

    insert_at = reading_indexes[0]
    sections[:] = other_sections[:insert_at] + [repaired_section] + other_sections[insert_at:]
    return _normalize_paper(paper, str(paper.get("id") or ""), str(paper.get("title") or ""))


def _is_reading_title(title: str) -> bool:
    cleaned = _clean_section_title(title).casefold()
    return "reading" in cleaned or "阅读" in cleaned


def _extract_reading_text_from_pages(scoped_pages: list[dict[str, Any]]) -> str:
    if not scoped_pages:
        return ""
    text = "\n\n".join(str(page.get("text") or "") for page in scoped_pages)
    title_match = re.search(
        r"Part\s*(?:III|Ⅲ)\s+Reading\s+Comprehension[^\n]*",
        text,
        flags=re.IGNORECASE,
    )
    if not title_match:
        return ""

    reading_text = text[title_match.end() :]
    next_part = re.search(r"\n\s*Part\s*(?:IV|Ⅳ)(?=\s|[（(])", reading_text, flags=re.IGNORECASE)
    if next_part:
        reading_text = reading_text[: next_part.start()]

    directions = re.search(
        r"Directions\s*:[\s\S]*?centre\.\s*",
        reading_text,
        flags=re.IGNORECASE,
    )
    if directions:
        reading_text = reading_text[directions.end() :]

    return _strip_page_artifacts(reading_text).strip()


def _parse_reading_passages(reading_text: str) -> list[dict[str, Any]]:
    passage_matches = list(
        re.finditer(r"(?:^|\n)\s*(?:☞\s*)?Passage\s+(\d+)\s*\n", reading_text, flags=re.IGNORECASE)
    )
    if not passage_matches:
        return []

    passages = []
    for index, match in enumerate(passage_matches):
        start = match.end()
        end = passage_matches[index + 1].start() if index + 1 < len(passage_matches) else len(reading_text)
        body = reading_text[start:end].strip()
        if not body:
            continue
        questions = _parse_reading_questions(body)
        if not questions:
            continue
        first_question_match = re.search(r"(?m)^\s*\d+\s*[\.\、]\s+", body)
        passage_body = body[: first_question_match.start()].strip() if first_question_match else body
        passages.append(
            {
                "number": match.group(1),
                "description": _strip_page_artifacts(passage_body).strip(),
                "questions": questions,
            }
        )
    return passages


def _parse_reading_questions(passage_body: str) -> list[dict[str, Any]]:
    matches = list(re.finditer(r"(?m)^\s*(\d+)\s*[\.\、]\s+", passage_body))
    questions = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(passage_body)
        block = passage_body[start:end].strip()
        parsed = _parse_choice_question_block(block)
        if parsed:
            questions.append(parsed)
    return questions


def _parse_choice_question_block(block: str) -> dict[str, Any] | None:
    question_match = re.match(r"^\s*(\d+)\s*[\.\、]\s*([\s\S]*)$", block)
    if not question_match:
        return None

    number = question_match.group(1)
    remainder = question_match.group(2).strip()
    option_matches = list(re.finditer(r"(?m)^\s*([A-D])\s*[\.\、]\s+", remainder))
    if option_matches:
        stem = remainder[: option_matches[0].start()].strip()
        options = []
        for index, option_match in enumerate(option_matches):
            start = option_match.end()
            end = option_matches[index + 1].start() if index + 1 < len(option_matches) else len(remainder)
            options.append({"id": option_match.group(1), "text": remainder[start:end].strip()})
    else:
        stem = remainder
        options = []

    return {
        "number": number,
        "type": "single_choice" if options else "unknown",
        "stem": _strip_page_artifacts(stem).strip(),
        "options": options,
        "answer": None,
        "analysis": "",
        "source_pages": [],
    }


def _build_reading_section_from_passages(
    base_section: dict[str, Any],
    passages: list[dict[str, Any]],
) -> dict[str, Any]:
    questions = []
    groups = []
    for passage in passages:
        passage_questions = [dict(question) for question in passage["questions"]]
        groups.append(
            {
                "id": f"reading-passage-{passage['number']}",
                "title": f"Passage {passage['number']}",
                "description": _clean_description_text(str(passage.get("description") or "")),
                "questions": passage_questions,
            }
        )
        questions.extend(passage_questions)
    total_score = _as_float(base_section.get("total_score"), 0)
    if total_score <= 0:
        total_score = 20
    score = round(total_score / len(questions), 2) if questions else 0
    return {
        "id": str(base_section.get("id") or "section-reading"),
        "title": _base_reading_title(str(base_section.get("title") or "Part III Reading Comprehension")),
        "description": str(base_section.get("description") or ""),
        "total_score": total_score,
        "score": score,
        "questions": questions,
        "groups": groups,
    }


def _base_reading_title(title: str) -> str:
    cleaned = _clean_section_title(title)
    cleaned = re.sub(r"\s+-\s+Passage\s+\d+\s*$", "", cleaned, flags=re.IGNORECASE)
    return cleaned or "Part III Reading Comprehension"


def _repair_cloze_sections_from_ocr(
    paper: dict[str, Any],
    scoped_pages: list[dict[str, Any]],
) -> dict[str, Any]:
    sections = paper.get("sections")
    if not isinstance(sections, list):
        return paper

    cloze_indexes = [
        index for index, section in enumerate(sections) if _is_cloze_title(str(section.get("title") or ""))
    ]
    if not cloze_indexes:
        return paper

    merged_questions: dict[str, dict[str, Any]] = {}
    for index in cloze_indexes:
        section = sections[index]
        for question in _section_questions(section):
            if not isinstance(question, dict):
                continue
            number = str(question.get("number") or "").strip()
            if not re.fullmatch(r"\d+", number):
                continue
            number_value = int(number)
            if number_value < 21 or number_value > 40:
                continue
            normalized = dict(question)
            normalized["number"] = number
            if not str(normalized.get("stem") or "").strip():
                normalized["stem"] = f"Blank {number}"
            existing = merged_questions.get(number)
            if existing is None:
                merged_questions[number] = normalized
            else:
                merged_questions[number] = _merge_question(existing, normalized)

    if not merged_questions:
        return paper

    first_section = sections[cloze_indexes[0]]
    description = _extract_cloze_passage_from_pages(scoped_pages)
    if not description:
        description = max(
            (str(sections[index].get("description") or "") for index in cloze_indexes),
            key=len,
            default="",
        )

    first_section["title"] = _clean_section_title(str(first_section.get("title") or "Part II Cloze"))
    first_section["description"] = description
    first_section["questions"] = [
        _normalize_cloze_question(merged_questions[str(number)], number)
        for number in range(21, 41)
        if str(number) in merged_questions
    ]

    for index in sorted(cloze_indexes[1:], reverse=True):
        del sections[index]

    return _normalize_paper(paper, str(paper.get("id") or ""), str(paper.get("title") or ""))


def _normalize_cloze_question(question: dict[str, Any], number: int) -> dict[str, Any]:
    normalized = dict(question)
    normalized["number"] = str(number)
    if not str(normalized.get("stem") or "").strip():
        normalized["stem"] = f"Blank {number}"
    normalized["options"] = _normalize_options(normalized.get("options"))
    normalized["source_pages"] = _normalize_pages(normalized.get("source_pages"))
    return normalized


def _extract_cloze_passage_from_pages(scoped_pages: list[dict[str, Any]]) -> str:
    if not scoped_pages:
        return ""
    text = "\n\n".join(str(page.get("text") or "") for page in scoped_pages)
    title_match = re.search(r"Part\s*(?:II|Ⅱ)\s+Cloze[^\n]*", text, flags=re.IGNORECASE)
    if not title_match:
        return ""

    after_title = text[title_match.end() :]
    next_part = re.search(r"\n\s*Part\s*(?:III|Ⅲ)(?=\s|[（(])", after_title, flags=re.IGNORECASE)
    if next_part:
        after_title = after_title[: next_part.start()]

    directions = re.search(r"Directions\s*:[\s\S]*?centre\.\s*", after_title, flags=re.IGNORECASE)
    if directions:
        passage = after_title[directions.end() :]
    else:
        passage = after_title

    first_option = re.search(r"\n\s*21\s*[\.\、]\s*A\s*[\.\、]", passage)
    if first_option:
        passage = passage[: first_option.start()]

    passage = _strip_page_artifacts(passage)
    return passage.strip()


def _strip_page_artifacts(text: str) -> str:
    lines = []
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue
        if re.fullmatch(r"[—-]\s*\d+\s*[—-]", stripped):
            continue
        if re.fullmatch(r"\d+\s*/\s*\d+", stripped):
            continue
        if re.fullmatch(r"_{3,}", stripped):
            continue
        if re.search(r"[|｜]\s*试题卷\s*$", stripped):
            continue
        if re.match(r"Part\s+[IVX\d]+\s+.*(?:continued|Choices for Questions)", stripped, re.I):
            continue
        if re.match(r"Passage\s+(?:\d+|One|Two|Three|Four)\s*[—–-]\s*Questions", stripped, re.I):
            continue
        if "海浪教育内部资料" in stripped or "绝密" in stripped:
            continue
        lines.append(line.rstrip())
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


def _merge_options(existing: list[dict[str, str]], incoming: list[dict[str, str]]) -> list[dict[str, str]]:
    by_id = {str(option.get("id") or ""): dict(option) for option in existing if option.get("id")}
    for option in incoming:
        option_id = str(option.get("id") or "")
        if not option_id:
            continue
        current = by_id.get(option_id)
        if current is None or len(str(option.get("text") or "")) > len(str(current.get("text") or "")):
            by_id[option_id] = {"id": option_id, "text": str(option.get("text") or "")}
    return [by_id[key] for key in sorted(by_id.keys())]


def _response_text(response: Any) -> str:
    if isinstance(response, str):
        return response
    content = getattr(response, "content", None)
    if content is not None:
        return str(content)
    if isinstance(response, dict):
        return str(response.get("content") or response.get("text") or response)
    return str(response)


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    if cleaned.startswith("["):
        raise PaperGenerationError("模型应返回完整的 JSON 对象，而不是对象列表。")
    start = cleaned.find("{")
    if start < 0:
        raise PaperGenerationError("模型没有返回 JSON 对象")
    try:
        # Never accept an inner question/options object when the outer JSON
        # was cut off: that silently turns a whole window into zero questions.
        value, _ = json.JSONDecoder().raw_decode(cleaned[start:])
    except json.JSONDecodeError as exc:
        raise PaperGenerationError("模型返回的 JSON 不完整或格式错误，需要重新整理该部分。") from exc
    if not isinstance(value, dict):
        raise PaperGenerationError("模型没有返回 JSON 对象")
    return value


async def grade_paper_submission(
    *,
    llm: LLMManager,
    paper: dict[str, Any],
    answers: dict[str, Any],
) -> dict[str, Any]:
    normalized_paper = normalize_paper_for_grading(paper)
    questions = flatten_questions_for_grading(normalized_paper)
    grading_items = split_grading_items(questions, answers)
    objective_results = grade_objective_items(grading_items["objective_items"])
    ai_results: dict[str, dict[str, Any]] = {}
    if grading_items["ai_items"]:
        ai_results = await grade_subjective_items_with_ai(
            llm=llm,
            paper=normalized_paper,
            ai_items=grading_items["ai_items"],
        )
    return merge_grade_results(
        paper=normalized_paper,
        answers=answers,
        questions=questions,
        objective_results=objective_results,
        ai_results=ai_results,
    )


def normalize_paper_for_grading(paper: dict[str, Any]) -> dict[str, Any]:
    return _normalize_paper(
        copy.deepcopy(paper),
        str(paper.get("id") or ""),
        str(paper.get("title") or ""),
    )


def flatten_questions_for_grading(paper: dict[str, Any]) -> list[dict[str, Any]]:
    return _flatten_questions_with_sections(paper)


def split_grading_items(
    questions: list[dict[str, Any]],
    answers: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    objective_items: list[dict[str, Any]] = []
    ai_items: list[dict[str, Any]] = []

    for item in questions:
        question = item["question"]
        answer = answers.get(question["id"], answers.get(str(question.get("number") or ""), ""))
        if not _has_answer(answer):
            continue
        if _can_grade_locally(question):
            objective_items.append({**item, "student_answer": answer})
        # Known-answer choices still need a concise contextual explanation.
        # Their score remains determined locally when results are merged.
        if not _can_grade_locally(question) or question.get("options"):
            ai_items.append(
                {
                    "id": question["id"],
                    "number": question["number"],
                    "section_title": item["section_title"],
                    "context_key": item.get("context_key", ""),
                    "context_title": item.get("context_title", ""),
                    "type": question["type"],
                    "score": item["score"],
                    "stem": question["stem"],
                    "options": question["options"],
                    "reference_answer": question.get("answer"),
                    "student_answer": answer,
                }
            )
    return {
        "objective_items": objective_items,
        "ai_items": ai_items,
    }


def grade_objective_items(objective_items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for item in objective_items:
        question = item["question"]
        result = _grade_objective_question(
            question,
            item.get("student_answer", ""),
            item["section_title"],
            item.get("score", 0),
        )
        results[question["id"]] = result
    return results


async def grade_subjective_items_with_ai(
    *,
    llm: LLMManager,
    paper: dict[str, Any],
    ai_items: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return await _grade_questions_with_ai(
        llm=llm,
        paper=paper,
        questions=ai_items,
    )


def merge_grade_results(
    *,
    paper: dict[str, Any],
    answers: dict[str, Any],
    questions: list[dict[str, Any]],
    objective_results: dict[str, dict[str, Any]],
    ai_results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    results = []
    for item in questions:
        question = item["question"]
        student_answer = answers.get(
            question["id"], answers.get(str(question.get("number") or ""), "")
        )
        result = objective_results.get(question["id"]) or ai_results.get(question["id"])
        if question["id"] in objective_results and question["id"] in ai_results:
            result = dict(result)
            analysis = ai_results[question["id"]]
            # Failed analysis must not replace a valid deterministic verdict.
            if analysis.get("is_correct") is not None and _normalize_answer_value(analysis.get("correct_answer")) == _normalize_answer_value(result.get("correct_answer")):
                for field in ("knowledge_points", "option_analysis", "key_phrases"):
                    if analysis.get(field):
                        result[field] = analysis[field]
                if analysis.get("is_correct") == result.get("is_correct"):
                    for field in ("reason", "suggestion"):
                        if analysis.get(field):
                            result[field] = analysis[field]
        if result is None:
            if not _has_answer(student_answer):
                result = _unanswered_grade_result(
                    {**question, "score": item.get("score", 0)},
                    item["section_title"],
                )
            else:
                result = _empty_grade_result(
                    {**question, "score": item.get("score", 0)},
                    item["section_title"],
                    "未能完成 AI 判卷，请人工复核。",
                )
        result["question_id"] = question["id"]
        result["number"] = str(question.get("number") or "")
        result["section_title"] = item["section_title"]
        result["max_score"] = round(_as_float(item.get("score"), 0), 2)
        result["score_awarded"] = min(
            result["max_score"],
            max(0, round(_as_float(result.get("score_awarded"), 0), 2)),
        )
        result["student_answer"] = student_answer
        results.append(result)

    total_score = round(sum(_as_float(result.get("score_awarded"), 0) for result in results), 2)
    return {
        "paper_id": paper["id"],
        "title": paper["title"],
        "total_score": min(100, total_score),
        "max_score": 100,
        "question_count": len(results),
        "graded_count": sum(
            1 for result in results if result.get("grading_status") != "unanswered"
        ),
        "unanswered_count": sum(
            1 for result in results if result.get("grading_status") == "unanswered"
        ),
        "correct_count": sum(1 for result in results if result.get("is_correct") is True),
        "results": results,
        "summary": _build_grade_summary(results),
    }


def _flatten_questions_with_sections(paper: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    for section_index, section in enumerate(paper.get("sections", []), start=1):
        if not isinstance(section, dict):
            continue
        section_title = str(section.get("title") or "题目")
        section_score = _as_float(section.get("score"), 0)
        section_description = str(section.get("description") or "").strip()
        groups = section.get("groups")
        grouped_questions = []
        if isinstance(groups, list) and groups:
            for group_index, group in enumerate(groups, start=1):
                if not isinstance(group, dict):
                    continue
                group_questions = group.get("questions")
                if not isinstance(group_questions, list):
                    continue
                context_key = f"section-{section_index}-group-{group_index}"
                context_title = str(group.get("title") or section_title)
                group_description = str(group.get("description") or "").strip()
                context_text = _join_context_text(section_description, group_description)
                grouped_questions.extend(
                    (
                        question,
                        context_key,
                        context_title,
                        context_text,
                    )
                    for question in group_questions
                    if isinstance(question, dict)
                )
        else:
            context_key = f"section-{section_index}"
            grouped_questions = [
                (question, context_key, section_title, section_description)
                for question in _section_questions(section)
                if isinstance(question, dict)
            ]

        questions = [entry[0] for entry in grouped_questions]
        if section_score <= 0:
            total_score = _as_float(section.get("total_score"), 0)
            section_score = round(total_score / len(questions), 2) if questions else 0
        for question, context_key, context_title, context_text in grouped_questions:
            items.append(
                {
                    "section_title": section_title,
                    "context_key": context_key,
                    "context_title": context_title,
                    "context_text": context_text,
                    "score": section_score,
                    "question": question,
                }
            )
    return items


def _join_context_text(*parts: str) -> str:
    return "\n\n".join(part.strip() for part in parts if part and part.strip())


def _can_grade_locally(question: dict[str, Any]) -> bool:
    answer = question.get("answer")
    if answer in (None, ""):
        return False
    return str(question.get("type") or "") in {"single_choice", "multiple_choice", "true_false"}


def _grade_objective_question(
    question: dict[str, Any],
    student_answer: Any,
    section_title: str,
    max_score: Any,
) -> dict[str, Any]:
    correct = _normalize_answer_value(question.get("answer"))
    submitted = _normalize_answer_value(student_answer)
    is_correct = bool(correct) and correct == submitted
    max_score = _as_float(max_score, 0)
    return {
        "question_id": question["id"],
        "number": str(question.get("number") or ""),
        "section_title": section_title,
        "is_correct": is_correct,
        "score_awarded": max_score if is_correct else 0,
        "max_score": max_score,
        "correct_answer": question.get("answer"),
        "student_answer": student_answer,
        "reason": "答案正确。" if is_correct else "答案与标准答案不一致。",
        "suggestion": "" if is_correct else "回到题干和选项，核对关键词与语境限制。",
    }


def _grading_materials_for_paper(
    paper: dict[str, Any],
    chunk: list[dict[str, Any]],
) -> dict[str, dict[str, str]]:
    requested_keys = {
        str(item.get("context_key") or "").strip()
        for item in chunk
        if str(item.get("context_key") or "").strip()
    }
    materials: dict[str, dict[str, str]] = {}
    for section_index, section in enumerate(paper.get("sections", []), start=1):
        if not isinstance(section, dict):
            continue
        section_title = str(section.get("title") or "题目")
        section_description = str(section.get("description") or "").strip()
        groups = section.get("groups")
        if isinstance(groups, list) and groups:
            for group_index, group in enumerate(groups, start=1):
                if not isinstance(group, dict):
                    continue
                context_key = f"section-{section_index}-group-{group_index}"
                if context_key not in requested_keys:
                    continue
                context_text = _join_context_text(
                    section_description,
                    str(group.get("description") or "").strip(),
                )
                if context_text:
                    materials[context_key] = {
                        "title": str(group.get("title") or section_title),
                        "text": context_text,
                    }
            continue

        context_key = f"section-{section_index}"
        if context_key in requested_keys and section_description:
            materials[context_key] = {
                "title": section_title,
                "text": section_description,
            }
    return materials


def _build_ai_grading_prompt(
    *,
    paper: dict[str, Any],
    chunk: list[dict[str, Any]],
    chunk_index: int,
) -> str:
    materials = _grading_materials_for_paper(paper, chunk)
    return f"""你是严格但公正的英语考试阅卷老师。请根据题目、参考答案（如果有）和学生答案判分，并指出错因。

只输出 JSON，不要 Markdown，不要解释。

总规则：
1. 每题最高分为题目对象中的 score（由所属 section.score 临时注入），不能超过该分值，不能为负数。
2. 客观题如果缺少参考答案，请根据题干、选项、相关材料和学生答案判断。
3. 完形填空题必须结合题目引用的完整完形文章判断，不能只看单个空的题干和选项。
4. 阅读理解题必须结合题目引用的对应阅读文章判断，不能脱离文章猜测。
5. 翻译、写作等主观题按语义准确性、语法、完整度给部分分。
6. reason 用中文，说明为什么得/失分；suggestion 用中文，给一个具体改进建议。
7. correct_answer 没有标准答案时可填写你判断的参考答案或空字符串。
8. 题目中的 context_key 对应“相关材料”中的 key；判分时必须先阅读并使用对应材料。
9. 翻译题的 correct_answer 给出自然、完整的参考译文；key_phrases 给出该句中的固定搭配或重点词组；reason 和 suggestion 具体说明学生译文的问题及修改方向。
10. 选择、完形、阅读题的 reason 简洁说明正确答案成立的关键搭配、语法或原文依据，通常一至三句话；suggestion 给出一句具体学习建议。不要逐项罗列 A/B/C/D 的考点与错点，不要输出 option_analysis 或 knowledge_points。主观题可按需要说明修改内容。
11. 有 reference_answer 的客观题严格保留标准答案，不重新改动答案或分值；若材料与答案存在冲突，在解析中指出需要人工复核，不编造支持理由。

JSON Schema：
{{
  "results": [
    {{
      "question_id": "q1",
      "is_correct": true,
      "score_awarded": 1.5,
      "correct_answer": "A",
      "key_phrases": ["固定搭配或重点词组"],
      "reason": "中文错因或得分说明",
      "suggestion": "中文建议"
    }}
  ]
}}

试卷：{paper.get("title", "")}
判卷批次：{chunk_index}
相关材料：
{json.dumps(materials, ensure_ascii=False)}
题目：
{json.dumps(chunk, ensure_ascii=False)}
"""


async def _grade_questions_with_ai(
    *,
    llm: LLMManager,
    paper: dict[str, Any],
    questions: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    chunks = _chunks(questions, 12)
    semaphore = asyncio.Semaphore(AI_GRADING_CONCURRENCY)

    async def grade_chunk(
        chunk_index: int,
        chunk: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        prompt = _build_ai_grading_prompt(
            paper=paper,
            chunk=chunk,
            chunk_index=chunk_index,
        )
        try:
            async with semaphore:
                response = await llm.invoke(
                    [{"role": "user", "content": prompt}],
                    model_id="default",
                    temperature=0,
                    max_tokens=6000,
                )
            data = _parse_json_object(_response_text(response))
            raw_results = data.get("results") if isinstance(data, dict) else []
            if not isinstance(raw_results, list):
                raw_results = []
            chunk_results: dict[str, dict[str, Any]] = {}
            questions_by_id = {str(question["id"]): question for question in chunk}
            for raw in raw_results:
                if not isinstance(raw, dict):
                    continue
                question_id = str(raw.get("question_id") or "")
                if question_id not in questions_by_id:
                    continue
                chunk_results[question_id] = {
                    "question_id": question_id,
                    "is_correct": raw.get("is_correct"),
                    "score_awarded": _as_float(raw.get("score_awarded"), 0),
                    "correct_answer": raw.get("correct_answer"),
                    "key_phrases": _normalize_text_list(
                        raw.get("key_phrases")
                        if raw.get("key_phrases") is not None
                        else raw.get("fixed_phrases")
                    ),
                    "reason": str(raw.get("reason") or ""),
                    "suggestion": str(raw.get("suggestion") or ""),
                    "knowledge_points": _normalize_text_list(raw.get("knowledge_points")),
                    "option_analysis": _normalize_option_analysis(raw.get("option_analysis"), questions_by_id[question_id].get("options", [])),
                }
            return chunk_results
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            chunk_results = {}
            for question in chunk:
                chunk_results[question["id"]] = _empty_grade_result(
                    {"id": question["id"], "number": question["number"], "score": question.get("score", 0)},
                    question.get("section_title", "题目"),
                    f"AI 判卷失败：{exc}",
                )
            return chunk_results

    chunk_results = await asyncio.gather(
        *(grade_chunk(chunk_index, chunk) for chunk_index, chunk in enumerate(chunks, start=1))
    )
    results: dict[str, dict[str, Any]] = {}
    for batch in chunk_results:
        results.update(batch)
    return results


def _normalize_option_analysis(raw: Any, options: list[Any]) -> list[dict[str, str]]:
    """Keep only supplied analysis for real option IDs, in source order."""
    by_id = {}
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("option_id") or "").strip()
        if key and key not in by_id:
            by_id[key] = item
    result = []
    for option in options:
        key = str(option.get("id") or "") if isinstance(option, dict) else str(option)
        item = by_id.get(key)
        if item is not None:
            result.append({"option_id": key, **{
                field: str(item.get(field) or "").strip()
                for field in ("knowledge_point", "error_point", "explanation")
            }})
    return result


def _empty_grade_result(question: dict[str, Any], section_title: str, reason: str) -> dict[str, Any]:
    return {
        "question_id": question["id"],
        "number": str(question.get("number") or ""),
        "section_title": section_title,
        "is_correct": None,
        "score_awarded": 0,
        "max_score": _as_float(question.get("score"), 0),
        "correct_answer": question.get("answer", ""),
        "student_answer": "",
        "reason": reason,
        "suggestion": "请稍后重试或人工复核该题。",
    }


def _unanswered_grade_result(
    question: dict[str, Any], section_title: str
) -> dict[str, Any]:
    return {
        "question_id": question["id"],
        "number": str(question.get("number") or ""),
        "section_title": section_title,
        "grading_status": "unanswered",
        "is_correct": None,
        "score_awarded": 0,
        "max_score": _as_float(question.get("score"), 0),
        "correct_answer": "",
        "student_answer": "",
        "reason": "未作答，未调用 AI 判卷。",
        "suggestion": "",
    }


def _has_answer(value: Any) -> bool:
    if isinstance(value, list):
        return any(str(part).strip() for part in value)
    return bool(str(value or "").strip())


def _normalize_answer_value(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, list):
        parts = value
    else:
        text = str(value).strip()
        if not text:
            return ()
        parts = re.split(r"[,，;；\s]+", text)
        if len(parts) == 1 and re.fullmatch(r"[A-Za-z]+", text) and len(text) > 1:
            parts = list(text)
    return tuple(sorted(str(part).strip().upper() for part in parts if str(part).strip()))


def _normalize_text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    return [text] if text else []


def _build_grade_summary(results: list[dict[str, Any]]) -> str:
    if not results:
        return "暂无判卷结果。"
    unanswered = [
        result for result in results if result.get("grading_status") == "unanswered"
    ]
    graded = [
        result for result in results if result.get("grading_status") != "unanswered"
    ]
    wrong = [result for result in graded if result.get("is_correct") is False]
    subjective = [result for result in graded if result.get("is_correct") is None]
    if not wrong and not subjective:
        if unanswered:
            return f"已判卷 {len(graded)} 题；另有 {len(unanswered)} 题未作答，未调用 AI 判卷。"
        return "整体表现很好，客观题答案基本正确。"
    focus = wrong[:3] + subjective[:2]
    numbers = "、".join(str(result.get("number") or result.get("question_id")) for result in focus)
    prefix = f"已判卷 {len(graded)} 题；另有 {len(unanswered)} 题未作答。" if unanswered else ""
    return f"{prefix}建议优先复盘第 {numbers} 题，重点看题干关键词、选项差异和主观题表达完整度。"


def _chunks(items: list[Any], size: int) -> list[list[Any]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _normalize_paper(
    data: dict[str, Any],
    paper_id: str,
    original_name: str,
) -> dict[str, Any]:
    data["id"] = str(data.get("id") or paper_id)
    data["title"] = str(data.get("title") or Path(original_name).stem)
    data["description"] = str(data.get("description") or "")
    sections = data.get("sections")
    if not isinstance(sections, list):
        sections = []
    normalized_sections = []
    question_index = 1
    for section_index, section in enumerate(sections, start=1):
        if not isinstance(section, dict):
            continue
        raw_groups = section.get("groups")
        normalized_groups = []
        grouped_questions: list[dict[str, Any]] = []
        if isinstance(raw_groups, list):
            for group_index, group in enumerate(raw_groups, start=1):
                if not isinstance(group, dict):
                    continue
                group_questions = group.get("questions")
                if not isinstance(group_questions, list):
                    group_questions = []
                normalized_group_questions = []
                for question in group_questions:
                    if not isinstance(question, dict):
                        continue
                    normalized_question = _normalize_question_for_paper(question, question_index)
                    question_index += 1
                    normalized_group_questions.append(normalized_question)
                    grouped_questions.append(dict(normalized_question))
                normalized_groups.append(
                    {
                        "id": str(group.get("id") or f"group-{section_index}-{group_index}"),
                        "title": str(group.get("title") or f"题组 {group_index}"),
                        "description": str(group.get("description") or ""),
                        "questions": normalized_group_questions,
                    }
                )

        questions = grouped_questions if normalized_groups else section.get("questions")
        if not isinstance(questions, list):
            questions = []
        normalized_questions = list(grouped_questions)
        question_scores = [
            _as_float(question.get("score"), 0)
            for question in questions
            if isinstance(question, dict) and _as_float(question.get("score"), 0) > 0
        ]
        section_score = _as_float(section.get("score"), 0)
        if section_score <= 0 and question_scores:
            section_score = round(sum(question_scores) / len(question_scores), 2)
        section_total_score = _as_float(section.get("total_score"), 0)
        if section_total_score <= 0 and section_score > 0:
            section_total_score = round(section_score * len([q for q in questions if isinstance(q, dict)]), 2)
        if not normalized_groups:
            for question in questions:
                if not isinstance(question, dict):
                    continue
                normalized_questions.append(_normalize_question_for_paper(question, question_index))
                question_index += 1
        normalized_section = {
            "id": str(section.get("id") or f"section-{section_index}"),
            "title": str(section.get("title") or f"第 {section_index} 部分"),
            "description": str(section.get("description") or ""),
            "total_score": section_total_score,
            "score": section_score,
            "questions": normalized_questions,
        }
        if section.get("type"):
            normalized_section["type"] = str(section["type"])
        if normalized_groups:
            normalized_section["groups"] = normalized_groups
        normalized_sections.append(normalized_section)
    data["sections"] = normalized_sections
    _normalize_scores_to_100(data)
    data["duration_minutes"] = int(_as_float(data.get("duration_minutes"), 120))
    return data


def _normalize_question_for_paper(question: dict[str, Any], question_index: int) -> dict[str, Any]:
    return {
        "id": str(question.get("id") or f"q{question_index}"),
        "number": str(question.get("number") or question_index),
        "type": str(question.get("type") or "unknown"),
        "stem": str(question.get("stem") or "").strip(),
        "options": _normalize_options(question.get("options")),
        "answer": question.get("answer"),
        "analysis": str(question.get("analysis") or ""),
        "source_pages": _normalize_pages(question.get("source_pages")),
    }


def _normalize_scores_to_100(data: dict[str, Any]) -> None:
    sections = [
        section
        for section in data.get("sections", [])
        if isinstance(section, dict) and _section_questions(section)
    ]
    if not sections:
        data["total_score"] = 0
        return

    for section in sections:
        questions = _section_questions(section)
        for question in questions:
            question.pop("score", None)
        score = _as_float(section.get("score"), 0)
        total = _as_float(section.get("total_score"), 0)
        if total <= 0 and score > 0:
            total = round(score * len(questions), 2)
            section["total_score"] = total
        elif score <= 0 and total > 0 and questions:
            section["score"] = round(total / len(questions), 2)

    current_total = sum(max(_as_float(section.get("total_score"), 0), 0) for section in sections)
    if current_total <= 0:
        question_count = sum(len(_section_questions(section)) for section in sections)
        even_score = round(100 / question_count, 2) if question_count else 0
        for section in sections:
            count = len(_section_questions(section))
            section["score"] = even_score
            section["total_score"] = round(even_score * count, 2)
    else:
        factor = 100 / current_total
        for section in sections:
            section["total_score"] = round(max(_as_float(section.get("total_score"), 0), 0) * factor, 2)
            count = len(_section_questions(section))
            section["score"] = round(section["total_score"] / count, 2) if count else 0

    rounded_total = round(sum(_as_float(section.get("total_score"), 0) for section in sections), 2)
    delta = round(100 - rounded_total, 2)
    if sections and delta:
        sections[-1]["total_score"] = round(_as_float(sections[-1].get("total_score"), 0) + delta, 2)
        count = len(_section_questions(sections[-1]))
        sections[-1]["score"] = round(_as_float(sections[-1].get("total_score"), 0) / count, 2) if count else 0
    data["total_score"] = 100


def _normalize_options(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    options = []
    for index, option in enumerate(value):
        default_id = chr(ord("A") + index)
        if isinstance(option, dict):
            options.append(
                {
                    "id": str(option.get("id") or default_id),
                    "text": str(option.get("text") or "").strip(),
                }
            )
        else:
            options.append({"id": default_id, "text": str(option).strip()})
    return options


def _normalize_pages(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    pages = []
    for item in value:
        try:
            pages.append(int(item))
        except (TypeError, ValueError):
            continue
    return pages


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _format_score_number(value: float) -> str:
    number = _as_float(value, 0)
    if number.is_integer():
        return str(int(number))
    return str(number)
