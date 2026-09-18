"""Durable generation jobs, checkpoints, validation and non-destructive repairs."""
import asyncio
import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import paper_generator as generator
from paper_quality import validate_paper, questions
from study_store import _write_json, list_submission_records

JOB_DIR = generator.DATA_DIR / "generation_jobs"
BACKUP_DIR = generator.DATA_DIR / "paper_backups"
RUNNING = {}
_llm = None


def now():
    return datetime.now(timezone.utc).isoformat()


def job_path(job_id):
    if not re.fullmatch(r"[a-f0-9]{32}", str(job_id)):
        raise ValueError("无效的生成任务编号")
    return JOB_DIR / f"{job_id}.json"


def save(job):
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    job["updated_at"] = now()
    _write_json(job_path(job["id"]), job)


def read(job_id):
    path = job_path(job_id)
    if not path.exists():
        raise ValueError("生成任务不存在")
    job = json.loads(path.read_text(encoding="utf-8"))
    if job["status"] in {"queued", "running"} and job_id not in RUNNING:
        job.update(status="interrupted", error="服务曾中断；已完成的步骤已保留，点击重试继续。")
        save(job)
    return job


def summary(job):
    return {key: job.get(key) for key in ("id", "original_name", "status", "stage", "progress", "error",
             "created_at", "updated_at", "result", "repair_of")}


def recent():
    from paper_trash import deleted_ids
    hidden = deleted_ids()
    paths = sorted(JOB_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:20]
    result = []
    for path in paths:
        job = read(path.stem)
        papers = job.get("result", {}).get("papers", [])
        if papers and all(p.get("id") in hidden for p in papers):
            continue
        result.append(summary(job))
    return result


def manager():
    global _llm
    if _llm is None:
        from agentclaw.model.manager import LLMManager
        _llm = LLMManager(config_path=str(generator.PROJECT_DIR / "models.json"))
    return _llm


def start(job):
    if job["id"] in RUNNING:
        return summary(job)
    job.update(status="queued", error=None)
    save(job)
    RUNNING[job["id"]] = asyncio.create_task(run(job))
    return summary(job)


def create(pdf_path, original_name, max_pages=None, ocr_concurrency=3):
    job_id = uuid4().hex
    job = {"id": job_id, "created_at": now(), "original_name": original_name,
           "pdf_path": str(pdf_path), "max_pages": max_pages, "ocr_concurrency": ocr_concurrency,
           "stage": "queued", "progress": {}, "state": {}}
    return start(job)


def retry(job_id):
    job = read(job_id)
    if job["status"] not in {"failed", "interrupted"}:
        raise ValueError("只能重试失败或中断的任务；卷子内容问题请使用“重新整理异常部分”。")
    if job.get("repair_of"):
        for active_id in RUNNING:
            if read(active_id).get("repair_of") == job["repair_of"]:
                raise ValueError("这份试卷已有修复任务正在运行")
    return start(job)


def repair(paper_id):
    for active_id in RUNNING:
        if read(active_id).get("repair_of") == paper_id:
            return summary(read(active_id))
    original = generator.read_paper(paper_id)
    if original.get("type") == "paper_collection":
        raise ValueError("请选择集合中的具体卷子")
    pages = original.get("ocr_pages")
    if not pages:
        source_id = original.get("source", {}).get("collection_id")
        pages = generator.read_ocr(source_id).get("pages", []) if source_id else []
    if not pages:
        raise ValueError("这份试卷没有已保存的原始识别文字，请重新上传 PDF")
    source = original.get("source", {})
    pages = copy.deepcopy([p for p in pages if int(source.get("start_page") or 1) <= p["page"] <= int(source.get("end_page") or max(x["page"] for x in pages))])
    job_id = uuid4().hex
    old_job_id = original.get("generation_job_id")
    cached = {}
    if old_job_id and job_path(old_job_id).exists():
        old_state = read(old_job_id).get("state", {})
        issues = [issue for issue in validate_paper(original)["issues"] if issue["code"] not in {"unconfirmed_format", "no_source"}]
        affected = {p for issue in issues for p in issue["pages"]}
        # If a structural issue has no page location, re-extract the whole selected paper.
        all_chunks = any(not issue["pages"] for issue in issues) or not issues
        namespace = original.get("chunk_namespace", original["id"])
        for key, chunk in old_state.get("chunks", {}).items():
            if key.startswith(namespace + ":") and not all_chunks and not affected.intersection(chunk.get("pages", [])):
                cached[original["id"] + key[len(namespace):]] = copy.deepcopy(chunk)
    doc = {"id": source.get("collection_id") or uuid4().hex,
           "source": {"file_name": source.get("file_name") or original["title"], "page_count": source.get("page_count", len(pages)),
                      "source_page_count": source.get("source_page_count", source.get("page_count", len(pages))),
                      "ocr_model": source.get("ocr_model", "saved"), "input_type": source.get("input_type", "pdf"),
                      "unit": source.get("unit", "页")}, "pages": pages}
    job = {"id": job_id, "created_at": now(), "original_name": doc["source"]["file_name"],
           "repair_of": paper_id, "stage": "queued", "progress": {},
           "state": {"ocr_doc": doc, "original": original, "chunks": cached,
                     "exams": [{"title": original["title"], "start_page": pages[0]["page"], "end_page": pages[-1]["page"]}]}}
    return start(job)


def advance(job, stage, **progress):
    job.update(stage=stage, status="running")
    job.setdefault("progress", {})[stage] = progress
    save(job)


def public_paper(paper):
    return {"id": paper["id"], "title": paper["title"], "quality": paper["quality"],
            "paper_url": f"/exam/{paper['id']}", "repaired_from": paper.get("repaired_from"),
            "question_count": sum(len(questions(s)) for s in paper["sections"])}


def persist_repair(job, paper):
    original = job["state"]["original"]
    original_id = original["id"]
    # Any record protects the original, including blank records and note-only drafts.
    protected = bool(list_submission_records(original_id))
    # Changing question identifiers/content may invalidate browser-local drafts too.
    def signature(p):
        return [(s.get("title"), q.get("id"), q.get("number"), q.get("stem"), q.get("options")) for s in p.get("sections", []) for q in questions(s)]
    changed = signature(paper) != signature(original)
    separate = protected or changed
    target_id = f"{original_id}-r{job['id'][:8]}" if separate else original_id
    paper.update(id=target_id, repaired_from=original_id if separate else original.get("repaired_from"))
    if separate:
        paper["title"] = original["title"] + "（修正版）"
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    original_path = generator.PAPER_DIR / f"{original_id}.json"
    backup_path = BACKUP_DIR / f"{original_id}-{job['id']}.json"
    if not backup_path.exists():
        backup_path.write_bytes(original_path.read_bytes())
    generator.persist_exam_papers([paper])
    # Keep the original entry in collections and put the correction directly beside it.
    collection_id = original.get("source", {}).get("collection_id")
    if collection_id and (generator.PAPER_DIR / f"{collection_id}.json").exists():
        collection_path = generator.PAPER_DIR / f"{collection_id}.json"
        collection = json.loads(collection_path.read_text(encoding="utf-8"))
        if collection.get("type") == "paper_collection":
            backup = BACKUP_DIR / f"{collection_id}-{job['id']}.json"
            if not backup.exists():
                backup.write_bytes(collection_path.read_bytes())
            entries = collection.get("papers", [])
            entry = {**public_paper(paper), "description": paper.get("description", ""), "total_score": paper["total_score"],
                     "start_page": paper["source"].get("start_page"), "end_page": paper["source"].get("end_page")}
            if not any(p["id"] == target_id for p in entries):
                index = next((i for i, p in enumerate(entries) if p["id"] == original_id), len(entries))
                entries.insert(index, entry)
            else:
                entries[:] = [entry if p["id"] == target_id else p for p in entries]
            collection["papers"] = entries
            _write_json(collection_path, collection)
    return paper


async def refresh_pdf_pages(job, llm):
    """Repair old text-layer checkpoints using the actual saved page images."""
    state = job["state"]
    doc = state["ocr_doc"]
    if not job["original_name"].lower().endswith(".pdf"):
        return
    pending = [(i, p) for i, p in enumerate(doc["pages"]) if p.get("extraction_method") != "vision_ocr"]
    if not pending:
        return
    # Extracted chunks based on obsolete text must not survive re-recognition.
    state["chunks"] = {}
    total = len(doc["pages"])
    done = total - len(pending)
    advance(job, "ocr", done=done, total=total)
    semaphore = asyncio.Semaphore(max(1, min(job.get("ocr_concurrency", 3), 4)))

    async def refresh(index, page):
        nonlocal done
        image = (generator.PROJECT_DIR / page.get("image", "")).resolve()
        if not image.is_relative_to(generator.PAGE_DIR.resolve()) or not image.is_file():
            raise ValueError("旧识别结果需要重新读取页面图片，但图片已不存在，请重新上传原 PDF。")
        async with semaphore:
            text = await generator._ocr_page(llm, image, page["page"], doc["source"]["page_count"])
            doc["pages"][index] = {**page, "text": text.strip(), "extraction_method": "vision_ocr"}
            done += 1
            advance(job, "ocr", done=done, total=total)

    await asyncio.gather(*(refresh(i, p) for i, p in pending))
    doc["source"]["ocr_model"] = generator.get_vision_model_name(llm)
    save(job)


async def run(job):
    state = job["state"]
    try:
        async with asyncio.timeout(3600):
            llm = manager()
            if "ocr_doc" not in state and Path(job["pdf_path"]).suffix.lower() != ".pdf":
                from document_reader import read_document_pages
                advance(job, "render", done=0)
                pages = await asyncio.to_thread(read_document_pages, Path(job["pdf_path"]))
                collection_id = uuid4().hex
                import shutil
                shutil.copy2(job["pdf_path"], generator.UPLOAD_DIR / (collection_id + Path(job["pdf_path"]).suffix.lower()))
                advance(job, "render", done=1)
                advance(job, "ocr", done=len(pages), total=len(pages))
                state["ocr_doc"] = generator.persist_ocr_document(collection_id=collection_id, original_name=job["original_name"],
                    page_count=len(pages), ocr_model="document_text", ocr_pages=pages)
                state["ocr_doc"]["source"].update(input_type="document", unit="段", source_page_count=len(pages))
                _write_json(generator.OCR_DIR / f"{collection_id}.json", state["ocr_doc"])
                save(job)
            if "ocr_doc" not in state:
                if "render" not in state:
                    advance(job, "render", done=0)
                    state["render"] = await asyncio.to_thread(generator.render_pdf_for_ocr, Path(job["pdf_path"]), dpi=160, max_pages=job.get("max_pages"))
                    save(job)
                rendered = state["render"]
                cached = state["ocr_pages"] = [p for p in state.get("ocr_pages", []) if p.get("extraction_method") == "vision_ocr"]
                advance(job, "ocr", done=len(cached), total=rendered["page_count"])
                def on_page(page):
                    cached.append(page)
                    advance(job, "ocr", done=len(cached), total=rendered["page_count"])
                pages = await generator.ocr_page_images(llm=llm, page_images=rendered["page_images"],
                    ocr_concurrency=job.get("ocr_concurrency", 3), cached_pages=cached, on_page=on_page,
                    source_pdf=Path(rendered.get("stored_pdf") or job["pdf_path"]))
                state["ocr_doc"] = generator.persist_ocr_document(collection_id=rendered["collection_id"], original_name=job["original_name"],
                    page_count=rendered["page_count"], ocr_model=generator.get_vision_model_name(llm), ocr_pages=pages)
                state["ocr_doc"]["source"]["source_page_count"] = rendered.get("source_page_count", rendered["page_count"])
                _write_json(generator.OCR_DIR / f"{rendered['collection_id']}.json", state["ocr_doc"])
                save(job)
            await refresh_pdf_pages(job, llm)
            doc = state["ocr_doc"]
            if "exams" not in state:
                advance(job, "split", done=0)
                state["exams"] = await generator.split_exam_ranges(llm=llm, original_name=job["original_name"], ocr_doc=doc)
                if not state["exams"]:
                    raise ValueError("未识别到试卷范围，请核对原文后重试。")
                save(job)
            jobs = generator.create_exam_build_jobs(original_name=job["original_name"], ocr_doc=doc, exams=state["exams"])
            if job.get("repair_of"):
                jobs[0]["paper_id"] = job["repair_of"]
            cached_chunks = state["chunks"] = {
                key: chunk for key, chunk in state.get("chunks", {}).items()
                if isinstance(chunk, dict) and isinstance(chunk.get("data"), dict)
                and isinstance(chunk["data"].get("sections"), list)
            }
            keys = [f"{j['paper_id']}:{i}" for j in jobs if not j.get("standard_paper")
                    for i, _ in enumerate(generator._make_page_windows(j["scoped_pages"], window_size=2, step=1), 1)]
            advance(job, "extract", done=sum(k in cached_chunks for k in keys), total=len(keys), standard_papers=sum(bool(j.get("standard_paper")) for j in jobs))
            def on_chunk(key, chunk):
                cached_chunks[key] = chunk
                advance(job, "extract", done=sum(k in cached_chunks for k in keys), total=len(keys))
            extracted = await generator.extract_exam_questions_for_jobs(llm=llm, exam_jobs=jobs, cached_chunks=cached_chunks, on_chunk=on_chunk)
            advance(job, "validate", done=0, total=len(jobs))
            papers = generator.assemble_exam_papers(ocr_doc=doc, extracted_jobs=extracted)
            for i, paper in enumerate(papers):
                paper["source"]["source_page_count"] = doc["source"].get("source_page_count", doc["source"]["page_count"])
                paper["generation_job_id"] = job["id"]
                paper["chunk_namespace"] = jobs[i]["paper_id"]
                paper["quality"] = validate_paper(paper)
                advance(job, "validate", done=i + 1, total=len(papers))
            advance(job, "save", done=0)
            if job.get("repair_of"):
                papers = [persist_repair(job, papers[0])]
                result = {"papers": [public_paper(p) for p in papers], "paper_url": f"/exam/{papers[0]['id']}"}
            else:
                generator.persist_exam_papers(papers)
                generated = generator.persist_paper_collection(original_name=job["original_name"], ocr_doc=doc, papers=papers)
                result = {"collection_id": generated["id"], "papers": [public_paper(p) for p in papers],
                          "paper_url": f"/exam/{papers[0]['id'] if len(papers) == 1 else generated['id']}"}
            statuses = [p["quality"]["status"] for p in papers]
            job.update(status="incomplete" if "incomplete" in statuses else "review" if "review" in statuses else "completed",
                       stage="done", result=result)
            job["progress"]["save"] = {"done": len(papers), "total": len(papers)}
            save(job)
    except asyncio.CancelledError:
        job.update(status="interrupted", error="服务中断，已完成部分已保留，可重试继续。")
        save(job)
        raise
    except Exception as exc:
        job.update(status="failed", error=str(exc) or "处理超时，请重试继续。")
        save(job)
    finally:
        RUNNING.pop(job["id"], None)
