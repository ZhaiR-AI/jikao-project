"""Recoverable deletion, with a durable 15-day deadline and bounded cleanup."""
import json
import math
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from study_store import _write_json

DATA = Path(__file__).resolve().parent / "data"
TRASH = DATA / "paper_trash"
RETENTION_DAYS = 15


def now():
    return datetime.now(timezone.utc)


def safe_id(value):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", str(value)):
        raise ValueError("无效的卷子编号")
    return str(value)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def entries():
    return [read_json(p) for p in TRASH.glob("*.json")]


def deleted_ids():
    return {pid for entry in entries() for pid in entry["paper_ids"]}


def move_to_trash(paper_id):
    from collection_categories import display_name
    from generation_jobs import RUNNING, read
    paper_id = safe_id(paper_id)
    hidden = deleted_ids()
    if paper_id in hidden:
        raise ValueError("这份卷子已在回收站中")
    paper = read_json(DATA / "papers" / f"{paper_id}.json")
    if paper.get("superseded_by"):
        raise ValueError("请删除当前修正版")
    ids = [paper_id]
    if paper.get("type") == "paper_collection":
        ids += [safe_id(p["id"]) for p in paper.get("papers", []) if p["id"] not in hidden]
    for job_id in RUNNING:
        job = read(job_id)
        collection_id = job.get("state", {}).get("ocr_doc", {}).get("id")
        if job.get("repair_of") in ids or collection_id in ids:
            raise ValueError("这份卷子正在生成或修复，请完成后再删除")
    deleted = now()
    entry = {"id": uuid4().hex, "root_id": paper_id, "paper_ids": ids,
             "title": display_name(paper_id, paper.get("title", paper_id)),
             "paper_count": len(ids) - 1 if paper.get("type") == "paper_collection" else 1,
             "deleted_at": deleted.isoformat(), "expires_at": (deleted + timedelta(days=RETENTION_DAYS)).isoformat()}
    TRASH.mkdir(parents=True, exist_ok=True)
    _write_json(TRASH / f"{entry['id']}.json", entry)
    return entry


def restore(entry_id):
    path = TRASH / f"{safe_id(entry_id)}.json"
    entry = read_json(path)
    if entry.get("purged_at") or datetime.fromisoformat(entry["expires_at"]) <= now():
        purge_expired(only_id=entry_id)
        raise ValueError("15天保留期已到，卷子已无法恢复")
    # A child deleted earlier may belong to a separately trashed collection.
    remaining_hidden = {pid for e in entries() if e["id"] != entry_id for pid in e["paper_ids"]}
    for pid in entry["paper_ids"]:
        source = DATA / "papers" / f"{safe_id(pid)}.json"
        if not source.exists():
            raise ValueError("回收站文件缺失，无法恢复")
        parent = read_json(source).get("source", {}).get("collection_id")
        if parent and parent in remaining_hidden:
            raise ValueError("请先恢复所属的试卷集合，再恢复这份卷子")
    path.unlink()
    return entry


def _unlink(path):
    resolved = path.resolve()
    if not resolved.is_relative_to(DATA.resolve()):
        raise ValueError("清理路径超出试卷数据目录")
    if resolved.is_file():
        resolved.unlink()


def purge_expired(at=None, only_id=None):
    current = at or now()
    removed = []
    for entry in entries():
        if only_id and entry["id"] != only_id:
            continue
        if entry.get("purged_at") or datetime.fromisoformat(entry["expires_at"]) > current:
            continue
        ids = set(entry["paper_ids"])
        source_ids = set(entry.get("source_ids", []))
        for pid in ids:
            path = DATA / "papers" / f"{safe_id(pid)}.json"
            if path.exists():
                doc = read_json(path)
                source_id = doc.get("source", {}).get("collection_id") or (pid if doc.get("type") == "paper_collection" else None)
                if source_id:
                    source_ids.add(safe_id(source_id))
        entry["source_ids"] = sorted(source_ids)
        _write_json(TRASH / f"{entry['id']}.json", entry)
        # The marker stays until cleanup completes, so interrupted cleanup is
        # retried and the expired paper cannot be opened in the meantime.
        for pid in ids:
            safe_id(pid)
            _unlink(DATA / "papers" / f"{pid}.json")
            _unlink(DATA / "collection_categories" / f"{pid}.json")
        for path in (DATA / "study" / "submissions").glob("*.json"):
            if read_json(path).get("paper_id") in ids:
                _unlink(path)
        # Remove stale links from surviving collections, including empty ones.
        for path in (DATA / "papers").glob("*.json"):
            doc = read_json(path)
            if doc.get("type") != "paper_collection":
                continue
            old = doc.get("papers", [])
            kept = [p for p in old if p.get("id") not in ids]
            if len(kept) != len(old):
                doc["papers"] = kept
                _write_json(path, doc)
        # Other entries may still be inside their recovery window. Their jobs
        # and uploaded PDFs must survive until those entries also expire.
        all_deleted = ids | {pid for e in entries() if e.get("purged_at") for pid in e["paper_ids"]}
        for path in (DATA / "generation_jobs").glob("*.json"):
            job = read_json(path)
            results = job.get("result", {}).get("papers", [])
            if results and all(p.get("id") in all_deleted for p in results):
                _unlink(path)
                upload = Path(job.get("pdf_path", ""))
                if upload.is_file() and upload.resolve().is_relative_to((DATA / "uploads").resolve()):
                    # Uploaded job PDFs have a unique filename per upload.
                    if not any(read_json(j).get("pdf_path") == str(upload) for j in (DATA / "generation_jobs").glob("*.json")):
                        _unlink(upload)
        for directory in [DATA / "paper_backups", DATA / "backups"]:
            for path in directory.rglob("*.json"):
                doc = read_json(path)
                results = doc.get("result", {}).get("papers", [])
                if doc.get("id") in ids or (results and all(p.get("id") in all_deleted for p in results)):
                    _unlink(path)
        for source_id in source_ids:
            remaining = [read_json(p) for p in (DATA / "papers").glob("*.json")]
            if any((p.get("source", {}).get("collection_id") == source_id and p.get("type") != "paper_collection")
                   or (p.get("id") == source_id and p.get("papers")) for p in remaining):
                continue
            _unlink(DATA / "ocr" / f"{source_id}.json")
            _unlink(DATA / "uploads" / f"{source_id}.pdf")
            images = (DATA / "pages" / source_id).resolve()
            if images.is_relative_to((DATA / "pages").resolve()) and images.is_dir():
                shutil.rmtree(images)
        # Keep only a tombstone (no exam content) to block old task links.
        entry["purged_at"] = current.isoformat()
        entry.pop("title", None)
        _write_json(TRASH / f"{entry['id']}.json", entry)
        removed.append(entry["id"])
    return removed


def list_trash():
    purge_expired()
    result = []
    for entry in entries():
        if entry.get("purged_at"):
            continue
        seconds = (datetime.fromisoformat(entry["expires_at"]) - now()).total_seconds()
        result.append({**entry, "days_left": max(0, math.ceil(seconds / 86400))})
    return sorted(result, key=lambda e: e["deleted_at"], reverse=True)
