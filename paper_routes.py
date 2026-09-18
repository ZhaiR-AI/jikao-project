from __future__ import annotations

import json
import asyncio
import hashlib
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from paper_generator import (
    DEFAULT_OCR_CONCURRENCY,
    PROJECT_DIR,
    ensure_data_dirs,
    read_ocr,
    read_paper,
)
from agents.paper_grading import workflow as paper_grading_workflow
from study_store import (
    create_submission_record,
    delete_submission_record,
    delete_wrong_question,
    get_submission,
    get_wrong_question_contexts,
    list_submission_records,
    list_wrong_questions,
    mark_wrong_question_reviewed,
    record_wrong_question_attempt,
    save_attempt,
    save_draft,
    sync_wrong_question_notes,
    update_wrong_question,
    upsert_wrong_questions,
)
from study_routes import router as study_router
from wrong_book_review import submit_wrong_book_practice
from wrong_book_records import create_record, delete_record, list_records, read_record, save_record, save_record_result
import generation_jobs
from paper_quality import validate_paper


router = APIRouter(prefix="/api/paper", tags=["paper"])


def exam_version():
    root = PROJECT_DIR / "static"
    names = ("index.html", "app.js", "exam-tools.js", "exam-generation.js", "styles.css")
    return hashlib.sha256(b"".join((root / name).read_bytes() for name in names)).hexdigest()[:16]


@router.get("/ui/version")
async def get_exam_version():
    from fastapi.responses import JSONResponse
    return JSONResponse({"version": exam_version()}, headers={"Cache-Control": "no-store"})


@router.get("/generation-jobs/recent")
async def get_generation_jobs():
    return {"jobs": generation_jobs.recent()}


@router.get("/generation-jobs/{job_id}")
async def get_generation_job(job_id: str):
    try:
        return generation_jobs.summary(generation_jobs.read(job_id))
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/generation-jobs/{job_id}/retry")
async def retry_generation_job(job_id: str):
    try:
        return generation_jobs.retry(job_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/generation-jobs", status_code=202)
async def create_generation_job(file: UploadFile = File(...), max_pages: int | None = None, ocr_concurrency: int = DEFAULT_OCR_CONCURRENCY):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "请上传 PDF 文件")
    if max_pages is not None and max_pages < 1:
        raise HTTPException(400, "最多处理页数必须大于 0")
    ensure_data_dirs()
    # Keep the source durable so a server restart can resume the job.
    from uuid import uuid4
    target = PROJECT_DIR / "data" / "uploads" / f"job-{uuid4().hex}.pdf"
    with target.open("wb") as handle:
        while chunk := await file.read(1024 * 1024):
            handle.write(chunk)
    return generation_jobs.create(target, file.filename, max_pages, ocr_concurrency)


@router.get("/{paper_id}/quality")
async def get_paper_quality(paper_id: str):
    try:
        paper = read_paper(paper_id)
        if paper.get("type") == "paper_collection":
            raise ValueError("请选择具体卷子")
        return validate_paper(paper)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/{paper_id}/source")
async def get_paper_source(paper_id: str):
    try:
        paper = read_paper(paper_id)
        pages = paper.get("ocr_pages", [])
        source_id = paper.get("source", {}).get("collection_id", "")
        if not pages and source_id:
            pages = read_ocr(source_id).get("pages", [])
            start = paper.get("source", {}).get("start_page", 1)
            end = paper.get("source", {}).get("end_page", len(pages))
            pages = [page for page in pages if start <= page["page"] <= end]
        pdf = PROJECT_DIR / "data/uploads" / f"{source_id}.pdf"
        pdf_url = f"/paper-data/uploads/{source_id}.pdf" if re.fullmatch(r"[a-f0-9]{32}", source_id) and pdf.exists() else None
        return {"pages": [{"page": p["page"], "text": p.get("text", "")} for p in pages], "pdf_url": pdf_url}
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/{paper_id}/repair", status_code=202)
async def repair_paper(paper_id: str):
    try:
        return generation_jobs.repair(paper_id)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(400, str(exc)) from exc


class GradeSubmission(BaseModel):
    record_id: str | None = None
    answers: dict[str, Any] = Field(default_factory=dict)
    categories: dict[str, list[str]] = Field(default_factory=dict)
    notes: dict[str, str] | None = None
    marks: list[str] | None = None
    duration_seconds: int = 0


class DraftSubmission(BaseModel):
    record_id: str | None = None
    answers: dict[str, Any] = Field(default_factory=dict)
    categories: dict[str, list[str]] = Field(default_factory=dict)
    notes: dict[str, str] | None = None
    marks: list[str] | None = None
    duration_seconds: int = 0


class WrongBookAttemptSubmission(BaseModel):
    answer: Any = ""
    is_correct: bool


class WrongBookUpdateSubmission(BaseModel):
    note: str | None = None
    categories: list[str] | None = None
    status: str | None = None


class WrongBookPracticeEntry(BaseModel):
    entry_id: str
    answer: Any = ""


class WrongBookPracticeSubmission(BaseModel):
    entries: list[WrongBookPracticeEntry] = Field(min_length=1, max_length=500)
    record_id: str | None = None


class WrongBookRecordCreate(BaseModel):
    exam_type: str
    entry_ids: list[str] = Field(min_length=1, max_length=2000)
    draft: dict[str, dict[str, Any]] = Field(default_factory=dict)


class WrongBookRecordDraft(BaseModel):
    draft: dict[str, dict[str, Any]] = Field(default_factory=dict)


@router.post("/generate")
async def generate_paper(
    file: UploadFile = File(...),
    max_pages: int | None = None,
    ocr_concurrency: int = DEFAULT_OCR_CONCURRENCY,
):
    job = await create_generation_job(file, max_pages, ocr_concurrency)
    await asyncio.shield(generation_jobs.RUNNING[job["id"]])
    finished = generation_jobs.read(job["id"])
    if finished["status"] == "failed":
        raise HTTPException(500, finished["error"])
    if finished["status"] in {"incomplete", "review"}:
        raise HTTPException(409, "试卷已保存，但需要核对生成问题。请刷新页面，从卷子列表进入检查；不要重复上传。")
    result = finished["result"]
    collection = read_paper(result["collection_id"])
    paper = read_paper(result["papers"][0]["id"])
    return {"type": "paper_collection", "collection_id": collection["id"], "collection": collection,
            "papers": collection["papers"], "paper_id": paper["id"], "paper_url": result["paper_url"],
            "json_url": f"/api/paper/{paper['id']}", "paper": paper, "generation_status": finished["status"]}


@router.get("/{paper_id}/submissions")
async def get_submission_history(paper_id: str):
    try:
        read_paper(paper_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="试卷不存在") from exc
    return {"records": list_submission_records(paper_id)}


@router.post("/{paper_id}/submissions")
async def create_saved_submission(paper_id: str):
    try:
        paper = read_paper(paper_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="试卷不存在") from exc
    return create_submission_record(paper_id, str(paper.get("title") or ""))


@router.delete("/{paper_id}/submissions/{record_id}")
async def delete_saved_submission(paper_id: str, record_id: str):
    try:
        read_paper(paper_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="试卷不存在") from exc
    try:
        return delete_submission_record(paper_id, record_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{paper_id}/submission")
async def get_saved_submission(paper_id: str, record_id: str | None = None):
    try:
        paper = read_paper(paper_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="试卷不存在") from exc
    try:
        data = get_submission(paper_id, record_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    data["title"] = paper.get("title") or data.get("title") or ""
    return data


@router.put("/{paper_id}/submission")
async def save_saved_submission(paper_id: str, submission: DraftSubmission):
    try:
        paper = read_paper(paper_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="试卷不存在") from exc
    try:
        saved = save_draft(
            paper_id=paper_id,
            title=str(paper.get("title") or ""),
            answers=submission.answers,
            categories=submission.categories,
            notes=submission.notes,
            marks=submission.marks,
            duration_seconds=submission.duration_seconds,
            record_id=submission.record_id,
        )
        sync_wrong_question_notes(
            paper_id=paper_id,
            notes=submission.notes,
        )
        return saved
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/wrong-book")
async def get_wrong_book(category: str | None = None, status: str | None = None):
    items = list_wrong_questions(category=category, status=status)
    return {
        "items": items,
        "contexts": get_wrong_question_contexts(items),
    }


@router.delete("/wrong-book/{entry_id}")
async def delete_wrong_book_item(entry_id: str):
    entry = delete_wrong_question(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="错题不存在")
    return entry


@router.post("/wrong-book/submit")
async def submit_wrong_book_batch(submission: WrongBookPracticeSubmission):
    try:
        if submission.record_id:
            record = read_record(submission.record_id)
            if any(entry.entry_id not in record["entry_ids"] for entry in submission.entries):
                raise ValueError("提交的题目不属于当前做题记录")
        result = await submit_wrong_book_practice(
            [entry.model_dump() for entry in submission.entries], paper_grading_workflow.run,
        )
        if submission.record_id:
            result["record"] = save_record_result(submission.record_id, result["results"])
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/wrong-book/records")
async def get_wrong_book_records(exam_type: str):
    try:
        return {"records": list_records(exam_type)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wrong-book/records")
async def create_wrong_book_record(submission: WrongBookRecordCreate):
    try:
        return create_record(submission.exam_type, submission.entry_ids, submission.draft)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/wrong-book/records/{record_id}")
async def get_wrong_book_record(record_id: str):
    try:
        return read_record(record_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/wrong-book/records/{record_id}")
async def put_wrong_book_record(record_id: str, submission: WrongBookRecordDraft):
    try:
        return save_record(record_id, submission.draft)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/wrong-book/records/{record_id}")
async def delete_wrong_book_record(record_id: str):
    try:
        return delete_record(record_id)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/wrong-book/{entry_id}/review")
async def review_wrong_book_item(entry_id: str):
    entry = mark_wrong_question_reviewed(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="错题不存在")
    return entry


@router.post("/wrong-book/{entry_id}/attempt")
async def submit_wrong_book_attempt(entry_id: str, submission: WrongBookAttemptSubmission):
    entry = record_wrong_question_attempt(
        entry_id,
        answer=submission.answer,
        is_correct=submission.is_correct,
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="错题不存在")
    return entry


@router.patch("/wrong-book/{entry_id}")
async def patch_wrong_book_item(entry_id: str, submission: WrongBookUpdateSubmission):
    try:
        entry = update_wrong_question(
            entry_id,
            note=submission.note,
            categories=submission.categories,
            status=submission.status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if entry is None:
        raise HTTPException(status_code=404, detail="错题不存在")
    return entry


@router.get("/{paper_id}")
async def get_paper(paper_id: str):
    try:
        return read_paper(paper_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="试卷不存在") from exc


@router.post("/{paper_id}/grade")
async def grade_paper(paper_id: str, submission: GradeSubmission):
    try:
        paper = read_paper(paper_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="试卷不存在") from exc

    if paper.get("quality", {}).get("status") == "incomplete":
        raise HTTPException(409, "这份试卷尚有结构问题，请先查看检查结果并修复；当前作答可以继续保存。")
    if paper.get("type") == "paper_collection":
        raise HTTPException(status_code=400, detail="请选择具体一套试卷后再提交")

    try:
        saved_record = save_draft(
            paper_id=paper_id,
            title=str(paper.get("title") or ""),
            answers=submission.answers,
            categories=submission.categories,
            notes=submission.notes,
            marks=submission.marks,
            duration_seconds=submission.duration_seconds,
            record_id=submission.record_id,
        )
        sync_wrong_question_notes(
            paper_id=paper_id,
            notes=submission.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    active_record_id = saved_record["record_id"]
    try:
        run_result = await paper_grading_workflow.run(
            {
                "paper_id": paper_id,
                "answers": submission.answers,
            }
        )
        grade_result = run_result["state"]["grade_result"]
        grade_result["record_id"] = active_record_id
        grade_result["record_file_name"] = saved_record["file_name"]
        attempt = save_attempt(
            paper_id=paper_id,
            title=str(paper.get("title") or ""),
            answers=submission.answers,
            categories=submission.categories,
            notes=submission.notes,
            duration_seconds=submission.duration_seconds,
            grade=grade_result,
            marks=submission.marks,
            record_id=active_record_id,
        )
        grade_result["attempt_id"] = attempt["id"]
        grade_result["wrong_question_ids"] = upsert_wrong_questions(
            paper=paper,
            grade=grade_result,
            categories=submission.categories,
            notes=submission.notes,
            attempt_id=attempt["id"],
        )
        return grade_result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"AI 判卷失败：{exc}") from exc


@router.get("/ocr/{doc_id}")
async def get_ocr(doc_id: str):
    try:
        return read_ocr(doc_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="OCR 文稿不存在") from exc


@router.get("/-/collections")
async def list_collections():
    from collection_categories import get_category, display_name, shelves
    from paper_trash import deleted_ids, purge_expired, list_trash
    purge_expired()
    hidden = deleted_ids()
    papers_dir = PROJECT_DIR / "data" / "papers"
    collections = []
    for path in sorted(papers_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("type") != "paper_collection" or data.get("superseded_by") or data.get("id", path.stem) in hidden:
            continue
        papers = data.get("papers") if isinstance(data.get("papers"), list) else []
        papers = [p for p in papers if p.get("id") not in hidden]
        if not papers:
            continue
        data.setdefault("id", path.stem)
        category, manual = get_category(data)
        data["title"] = display_name(data["id"], data.get("title", path.stem))
        for paper in papers:
            paper["title"] = display_name(paper["id"], paper.get("title", paper["id"]))
        collections.append(
            {
                "id": data.get("id") or path.stem,
                "title": data.get("title") or path.stem,
                "source": data.get("source") or {},
                "paper_count": len(papers),
                "question_count": sum(int(paper.get("question_count") or 0) for paper in papers if isinstance(paper, dict)),
                "papers": papers,
                "paper_url": f"/exam/{data.get('id') or path.stem}",
                "json_url": f"/api/paper/{data.get('id') or path.stem}",
                "updated_at": path.stat().st_mtime,
                "category": category,
                "category_manual": manual,
            }
        )
    return {"collections": collections, "categories": shelves(), "trash_count": len(list_trash())}


@router.get("/-/trash")
async def get_paper_trash():
    from paper_trash import list_trash
    return {"items": list_trash(), "retention_days": 15}


@router.post("/-/trash/{paper_id}")
async def trash_library_paper(paper_id: str):
    from paper_trash import move_to_trash
    try:
        return move_to_trash(paper_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, "卷子不存在") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/-/trash/{entry_id}/restore")
async def restore_library_paper(entry_id: str):
    from paper_trash import restore
    try:
        return restore(entry_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, "回收站记录不存在") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class LibraryNameUpdate(BaseModel):
    name: str


@router.post("/-/shelves", status_code=201)
async def create_shelf(update: LibraryNameUpdate):
    from collection_categories import save_shelf
    try:
        return {"id": save_shelf(update.name), "name": update.name.strip()}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.patch("/-/shelves/{shelf_id}")
async def rename_shelf(shelf_id: str, update: LibraryNameUpdate):
    from collection_categories import save_shelf
    try:
        return {"id": save_shelf(update.name, shelf_id), "name": update.name.strip()}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/-/shelves/{shelf_id}")
async def remove_shelf(shelf_id: str):
    from collection_categories import delete_shelf
    try:
        delete_shelf(shelf_id)
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.patch("/-/names/{paper_id}")
async def rename_library_paper(paper_id: str, update: LibraryNameUpdate):
    from collection_categories import rename, category_path
    try:
        category_path(paper_id)
        paper = read_paper(paper_id)
        if paper.get("superseded_by"):
            raise ValueError("请在修正版上修改名称")
        rename(paper_id, update.name)
        if paper.get("type") == "paper_collection" and len(paper.get("papers", [])) == 1:
            rename(paper["papers"][0]["id"], update.name)
        return {"id": paper_id, "title": update.name.strip()}
    except FileNotFoundError as exc:
        raise HTTPException(404, "卷子不存在") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class CollectionCategoryUpdate(BaseModel):
    category: str


@router.patch("/-/collections/{collection_id}/category")
async def update_collection_category(collection_id: str, update: CollectionCategoryUpdate):
    from collection_categories import get_category, set_category, category_path
    try:
        category_path(collection_id)
        collection = read_paper(collection_id)
        if collection.get("type") != "paper_collection" or collection.get("superseded_by"):
            raise ValueError("请选择有效的试卷集合")
        set_category(collection_id, update.category)
        category, manual = get_category(collection)
        return {"id": collection_id, "category": category, "category_manual": manual}
    except FileNotFoundError as exc:
        raise HTTPException(404, "试卷集合不存在") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def mount_paper_app(app) -> None:
    from contextlib import suppress, asynccontextmanager
    from paper_trash import purge_expired
    import logging

    async def cleanup_loop():
        while True:
            try:
                purge_expired()
            except Exception:
                logging.getLogger(__name__).exception("回收站到期清理失败，将自动重试")
            await asyncio.sleep(60)

    async def start_cleanup():
        app.state.trash_cleanup = asyncio.create_task(cleanup_loop())

    async def stop_cleanup():
        app.state.trash_cleanup.cancel()
        with suppress(asyncio.CancelledError):
            await app.state.trash_cleanup

    previous_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def trash_lifespan(application):
        async with previous_lifespan(application) as state:
            await start_cleanup()
            try:
                yield state
            finally:
                await stop_cleanup()

    app.router.lifespan_context = trash_lifespan
    ensure_data_dirs()
    app.include_router(router)
    app.include_router(study_router)

    static_dir = PROJECT_DIR / "static"
    data_dir = PROJECT_DIR / "data"
    app.mount("/paper-static", StaticFiles(directory=str(static_dir)), name="paper-static")
    app.mount("/paper-data", StaticFiles(directory=str(data_dir)), name="paper-data")

    @app.get("/exam")
    async def exam_home():
        return HTMLResponse((static_dir / "index.html").read_text(encoding="utf-8").replace("__EXAM_VERSION__", exam_version()), headers={"Cache-Control": "no-store"})

    @app.get("/exam/{paper_id}")
    async def exam_page(paper_id: str):
        try:
            paper = read_paper(paper_id)
            replacement = paper.get("superseded_by")
            if replacement and replacement != paper_id and re.fullmatch(r"[A-Za-z0-9_-]+", replacement):
                read_paper(replacement)  # Never redirect to a missing replacement.
                return RedirectResponse(f"/exam/{replacement}", status_code=307,
                                        headers={"Cache-Control": "no-store"})
        except FileNotFoundError:
            pass
        return await exam_home()

    @app.get("/study")
    async def study_page():
        return FileResponse(static_dir / "study.html")

    @app.get("/wrong-book")
    async def wrong_book_page():
        return FileResponse(
            static_dir / "wrong_book.html",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/")
    async def exam_root():
        return RedirectResponse("/exam")
