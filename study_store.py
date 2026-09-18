from __future__ import annotations

import json
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


PROJECT_DIR = Path(__file__).resolve().parent
STUDY_DATA_DIR = PROJECT_DIR / "data" / "study"
SUBMISSION_DIR = STUDY_DATA_DIR / "submissions"
WRONG_BOOK_PATH = STUDY_DATA_DIR / "wrong_book.json"
DAILY_PLAN_PATH = STUDY_DATA_DIR / "daily_plans.json"

CATEGORY_LABELS = {
    "grammar": "语法",
    "vocabulary": "单词",
    "phrase": "词组",
    "translation": "翻译",
}
WRONG_BOOK_STATUSES = {"unreviewed", "reviewed", "mastered"}
WRONG_BOOK_EXAM_TYPES = {"choice", "translation", "cloze", "reading", "writing"}


def ensure_study_dirs() -> None:
    SUBMISSION_DIR.mkdir(parents=True, exist_ok=True)
    STUDY_DATA_DIR.mkdir(parents=True, exist_ok=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "", str(value or "")) or "unknown"


def _submission_path(paper_id: str) -> Path:
    return SUBMISSION_DIR / f"{_safe_id(paper_id)}.json"


def _safe_filename_part(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value or ""))
    value = re.sub(r"\s+", " ", value).strip(" ._")
    return (value[:80].rstrip(" .") or "未命名试卷")


def _record_submission_path(title: str, record_date: str, record_id: str) -> Path:
    return SUBMISSION_DIR / f"{_safe_filename_part(title)}-{record_date}-{record_id}.json"


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, value: Any) -> None:
    ensure_study_dirs()
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.stem}-",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
        json.dump(value, handle, ensure_ascii=False, indent=2)
    temp_path.replace(path)


def _empty_submission(paper_id: str, title: str = "") -> dict[str, Any]:
    return {
        "record_id": "",
        "record_date": "",
        "file_name": "",
        "paper_id": paper_id,
        "title": title,
        "draft": {
            "answers": {},
            "categories": {},
            "notes": {},
            "marks": [],
            "duration_seconds": 0,
            "updated_at": None,
        },
        "attempts": [],
    }


def _submission_record_key(path: Path, data: dict[str, Any]) -> str:
    record_id = str(data.get("record_id") or "").lower()
    if re.fullmatch(r"[0-9a-f]{32}", record_id):
        return record_id
    return f"legacy-{_safe_id(path.stem)}"


def _submission_candidates(paper_id: str) -> list[tuple[Path, dict[str, Any]]]:
    legacy_path = _submission_path(paper_id)
    candidates: list[tuple[Path, dict[str, Any]]] = []
    if SUBMISSION_DIR.exists():
        for path in SUBMISSION_DIR.glob("*.json"):
            data = _read_json(path, None)
            if not isinstance(data, dict):
                continue
            if path == legacy_path or data.get("paper_id") == paper_id:
                candidates.append((path, data))
    return candidates


def _load_submission(
    paper_id: str,
    record_id: str | None = None,
) -> tuple[Path | None, dict[str, Any]]:
    legacy_path = _submission_path(paper_id)
    candidates = _submission_candidates(paper_id)
    if record_id is not None:
        for path, data in candidates:
            if _submission_record_key(path, data) == record_id:
                return path, data
        raise ValueError("做题记录不存在")
    if not candidates:
        return None, _empty_submission(paper_id)
    return max(
        candidates,
        key=lambda item: (item[0].stat().st_mtime_ns, item[0] != legacy_path),
    )


def _normalize_submission(
    data: dict[str, Any],
    paper_id: str,
    source_path: Path | None = None,
) -> dict[str, Any]:
    if not isinstance(data, dict):
        return _empty_submission(paper_id)
    data = dict(data)
    data.setdefault("paper_id", paper_id)
    data.setdefault("title", "")
    data.setdefault("draft", _empty_submission(paper_id)["draft"])
    if not isinstance(data["draft"], dict):
        data["draft"] = _empty_submission(paper_id)["draft"]
    else:
        data["draft"] = dict(data["draft"])
    data["draft"].setdefault("answers", {})
    data["draft"].setdefault("categories", {})
    data["draft"].setdefault("notes", {})
    data["draft"].setdefault("marks", [])
    data["draft"].setdefault("duration_seconds", 0)
    data["draft"].setdefault("updated_at", None)
    data.setdefault("attempts", [])
    if source_path is not None:
        data["record_id"] = _submission_record_key(source_path, data)
        data["file_name"] = source_path.name
    return data


def _prepare_submission(
    paper_id: str,
    title: str,
    record_id: str | None = None,
) -> tuple[dict[str, Any], Path]:
    source_path, data = _load_submission(paper_id, record_id)
    data = _normalize_submission(data, paper_id, source_path)
    data["title"] = title or data.get("title") or ""

    saved_record_id = str(data.get("record_id") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{32}", saved_record_id):
        saved_record_id = uuid4().hex
    record_date = str(data.get("record_date") or "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", record_date):
        record_date = datetime.now().astimezone().date().isoformat()

    legacy_path = _submission_path(paper_id)
    if source_path and source_path != legacy_path and data.get("record_id") == saved_record_id:
        target_path = source_path
    else:
        target_path = _record_submission_path(data["title"], record_date, saved_record_id)

    data["record_id"] = saved_record_id
    data["record_date"] = record_date
    data["file_name"] = target_path.name
    return data, target_path


def get_submission(paper_id: str, record_id: str | None = None) -> dict[str, Any]:
    source_path, data = _load_submission(paper_id, record_id)
    return _normalize_submission(data, paper_id, source_path)


def create_submission_record(paper_id: str, title: str) -> dict[str, Any]:
    record_id = uuid4().hex
    record_date = datetime.now().astimezone().date().isoformat()
    target_path = _record_submission_path(title, record_date, record_id)
    data = _empty_submission(paper_id, title)
    data["record_id"] = record_id
    data["record_date"] = record_date
    data["file_name"] = target_path.name
    data["draft"]["updated_at"] = _now()
    _write_json(target_path, data)
    return data


def _has_answer(value: Any) -> bool:
    if isinstance(value, list):
        return any(str(part).strip() for part in value)
    return bool(str(value or "").strip())


def list_submission_records(paper_id: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path, stored in _submission_candidates(paper_id):
        data = _normalize_submission(stored, paper_id, path)
        attempts = data.get("attempts") if isinstance(data.get("attempts"), list) else []
        last_attempt = attempts[-1] if attempts and isinstance(attempts[-1], dict) else {}
        grade = last_attempt.get("grade") if isinstance(last_attempt.get("grade"), dict) else {}
        answers = data["draft"].get("answers")
        if not isinstance(answers, dict):
            answers = {}
        updated_at = (
            data["draft"].get("updated_at")
            or last_attempt.get("submitted_at")
            or datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        )
        records.append(
            {
                "record_id": data["record_id"],
                "record_date": data.get("record_date") or "",
                "file_name": path.name,
                "updated_at": updated_at,
                "answered_count": sum(1 for answer in answers.values() if _has_answer(answer)),
                "attempt_count": len(attempts),
                "last_score": grade.get("total_score"),
                "status": "submitted" if attempts else "in_progress" if answers else "new",
            }
        )
    return sorted(records, key=lambda item: item["updated_at"] or "", reverse=True)


def delete_submission_record(paper_id: str, record_id: str) -> dict[str, Any]:
    path, data = _load_submission(paper_id, record_id)
    if path is None:
        raise ValueError("做题记录不存在")
    deleted = {
        "record_id": _submission_record_key(path, data),
        "file_name": path.name,
    }
    path.unlink()
    return deleted


def save_draft(
    *,
    paper_id: str,
    title: str,
    answers: dict[str, Any],
    categories: dict[str, list[str]],
    notes: dict[str, str] | None,
    marks: list[str] | None = None,
    duration_seconds: int = 0,
    record_id: str | None = None,
) -> dict[str, Any]:
    data, target_path = _prepare_submission(paper_id, title, record_id)
    saved_notes = notes if notes is not None else data["draft"].get("notes", {})
    saved_marks = marks if marks is not None else data["draft"].get("marks", [])
    data["draft"] = {
        "answers": answers or {},
        "categories": categories or {},
        "notes": saved_notes,
        "marks": saved_marks,
        "duration_seconds": max(0, int(duration_seconds or 0)),
        "updated_at": _now(),
    }
    _write_json(target_path, data)
    return data


def save_attempt(
    *,
    paper_id: str,
    title: str,
    answers: dict[str, Any],
    categories: dict[str, list[str]],
    notes: dict[str, str] | None,
    duration_seconds: int,
    grade: dict[str, Any],
    marks: list[str] | None = None,
    record_id: str | None = None,
) -> dict[str, Any]:
    data, target_path = _prepare_submission(paper_id, title, record_id)
    saved_notes = notes if notes is not None else data["draft"].get("notes", {})
    saved_marks = marks if marks is not None else data["draft"].get("marks", [])
    attempt = {
        "id": uuid4().hex,
        "submitted_at": _now(),
        "answers": answers or {},
        "categories": categories or {},
        "notes": saved_notes,
        "marks": saved_marks,
        "duration_seconds": max(0, int(duration_seconds or 0)),
        "grade": grade,
    }
    attempts = data.get("attempts")
    if not isinstance(attempts, list):
        attempts = []
    data["attempts"] = [*attempts[-29:], attempt]
    data["draft"] = {
        "answers": answers or {},
        "categories": categories or {},
        "notes": saved_notes,
        "marks": saved_marks,
        "duration_seconds": max(0, int(duration_seconds or 0)),
        "updated_at": attempt["submitted_at"],
    }
    _write_json(target_path, data)
    return attempt


def _iter_questions(paper: dict[str, Any]) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    for section in paper.get("sections", []):
        if not isinstance(section, dict):
            continue
        groups = section.get("groups")
        if isinstance(groups, list) and groups:
            for group in groups:
                if isinstance(group, dict) and isinstance(group.get("questions"), list):
                    questions.extend(
                        question
                        for question in group["questions"]
                        if isinstance(question, dict)
                    )
        elif isinstance(section.get("questions"), list):
            questions.extend(
                question
                for question in section["questions"]
                if isinstance(question, dict)
            )
    return questions


def _question_map(paper: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(question.get("id") or question.get("number") or ""): question
        for question in _iter_questions(paper)
    }


def _join_question_context(*parts: Any) -> str:
    return "\n\n".join(
        str(part or "").strip()
        for part in parts
        if str(part or "").strip()
    )


def _context_question(question: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(question.get("id") or question.get("number") or ""),
        "number": str(question.get("number") or ""),
        "type": str(question.get("type") or "unknown"),
        "stem": str(question.get("stem") or ""),
        "options": question.get("options") or [],
    }


def _question_context_map(paper: dict[str, Any]) -> dict[str, dict[str, Any]]:
    contexts: dict[str, dict[str, Any]] = {}
    paper_id = str(paper.get("id") or "")
    for section_index, section in enumerate(paper.get("sections", [])):
        if not isinstance(section, dict):
            continue
        section_title = str(section.get("title") or "题目")
        section_description = str(section.get("description") or "").strip()
        groups = section.get("groups")
        if isinstance(groups, list) and groups:
            for group_index, group in enumerate(groups):
                if not isinstance(group, dict):
                    continue
                group_description = str(group.get("description") or "").strip()
                context_text = _join_question_context(section_description, group_description)
                group_questions = [
                    question
                    for question in group.get("questions") or []
                    if isinstance(question, dict)
                ]
                context_key = f"{paper_id}:section-{section_index}:group-{group_index}"
                review_context = {
                    "key": context_key,
                    "paper_id": paper_id,
                    "section_title": section_title,
                    "title": str(group.get("title") or section_title),
                    "directions": section_description,
                    "passage": group_description,
                    "questions": [
                        _context_question(question) for question in group_questions
                    ],
                }
                for question in group_questions:
                    question_id = str(question.get("id") or question.get("number") or "")
                    if question_id:
                        contexts[question_id] = {
                            "section_title": section_title,
                            "context_text": context_text,
                            "context_key": context_key,
                            "review_context": review_context,
                        }
            continue

        section_questions = [
            question
            for question in section.get("questions") or []
            if isinstance(question, dict)
        ]
        context_key = f"{paper_id}:section-{section_index}"
        review_context = {
            "key": context_key,
            "paper_id": paper_id,
            "section_title": section_title,
            "title": section_title,
            "directions": "",
            "passage": section_description,
            "questions": [
                _context_question(question) for question in section_questions
            ],
        }
        for question in section_questions:
            question_id = str(question.get("id") or question.get("number") or "")
            if question_id:
                contexts[question_id] = {
                    "section_title": section_title,
                    "context_text": section_description,
                    "context_key": context_key,
                    "review_context": review_context,
                }
    return contexts


def _is_cloze_question(question_type: str, section_title: str) -> bool:
    title = section_title.casefold()
    return question_type in {"single_choice", "multiple_choice", "true_false"} and (
        "cloze" in title or "完形" in section_title or "完型" in section_title
    )


def _is_translation_question(question_type: str, section_title: str) -> bool:
    title = section_title.casefold()
    return question_type in {"translation", "short_answer"} and (
        "translation" in title or "翻译" in section_title or "汉译英" in section_title
    )


def _is_reading_question(question_type: str, section_title: str) -> bool:
    title = section_title.casefold()
    return question_type in {"single_choice", "multiple_choice", "true_false"} and (
        "reading" in title or "阅读" in section_title
    )


def _is_writing_question(question_type: str, section_title: str) -> bool:
    title = section_title.casefold()
    return question_type in {"essay", "writing", "composition"} or any(
        marker in title for marker in ("writing", "composition")
    ) or "作文" in section_title


def _wrong_book_exam_type(question_type: str, section_title: str) -> str:
    if _is_cloze_question(question_type, section_title):
        return "cloze"
    if _is_reading_question(question_type, section_title):
        return "reading"
    if _is_writing_question(question_type, section_title):
        return "writing"
    if _is_translation_question(question_type, section_title):
        return "translation"
    return "choice"


def _extract_cloze_sentence(text: str, number: Any) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    number_text = re.escape(str(number or "").strip())
    if not normalized or not number_text:
        return ""
    match = None
    for pattern in (
        rf"_+\s*{number_text}\s*_+",
        rf"(?<![A-Za-z0-9_]){number_text}(?![A-Za-z0-9_])",
    ):
        match = re.search(pattern, normalized)
        if match:
            break
    if not match:
        return ""

    boundaries = ".!?。！？"
    start = max((normalized.rfind(mark, 0, match.start()) for mark in boundaries), default=-1) + 1
    end_positions = [normalized.find(mark, match.end()) for mark in boundaries]
    end_positions = [position for position in end_positions if position >= 0]
    end = min(end_positions) + 1 if end_positions else len(normalized)
    return normalized[start:end].strip()


def _normalize_text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    return [text] if text else []


def _wrong_entry_id(paper_id: str, question_id: str) -> str:
    return f"{_safe_id(paper_id)}__{_safe_id(question_id)}"


def _question_note(
    notes: dict[str, str] | None,
    question_id: str,
    number: Any = "",
) -> str | None:
    if not isinstance(notes, dict):
        return None
    for key in (question_id, str(number or "")):
        if key and key in notes:
            return str(notes.get(key) or "").strip()
    return None


def sync_wrong_question_notes(
    *,
    paper_id: str,
    notes: dict[str, str] | None,
) -> int:
    """Copy notes from an exam submission to existing wrong-book entries."""
    if not isinstance(notes, dict) or not notes:
        return 0
    stored = _read_json(WRONG_BOOK_PATH, [])
    if not isinstance(stored, list):
        return 0

    updated_count = 0
    for entry in stored:
        if not isinstance(entry, dict) or entry.get("paper_id") != paper_id:
            continue
        question_id = str(entry.get("question_id") or "")
        note = _question_note(notes, question_id, entry.get("number"))
        if note is None or entry.get("note") == note:
            continue
        entry["note"] = note
        entry["note_updated_at"] = _now()
        updated_count += 1

    if updated_count:
        _write_json(WRONG_BOOK_PATH, stored)
    return updated_count


def upsert_wrong_questions(
    *,
    paper: dict[str, Any],
    grade: dict[str, Any],
    categories: dict[str, list[str]],
    notes: dict[str, str] | None = None,
    attempt_id: str = "",
) -> list[str]:
    ensure_study_dirs()
    stored = _read_json(WRONG_BOOK_PATH, [])
    if not isinstance(stored, list):
        stored = []
    by_id = {
        str(item.get("id")): item
        for item in stored
        if isinstance(item, dict) and item.get("id")
    }
    question_map = _question_map(paper)
    context_map = _question_context_map(paper)
    wrong_ids: list[str] = []
    for result in grade.get("results", []):
        if not isinstance(result, dict):
            continue
        question_id = str(result.get("question_id") or "")
        if not question_id:
            continue
        question = question_map.get(question_id, {})
        question_type = str(question.get("type") or "unknown")
        context = context_map.get(question_id, {})
        section_title = str(
            result.get("section_title") or context.get("section_title") or ""
        )
        student_answer = result.get("student_answer")
        is_wrong = result.get("is_correct") is False
        note = _question_note(
            notes,
            question_id,
            result.get("number") or question.get("number"),
        )
        has_note = bool(note)
        is_translation = _is_translation_question(question_type, section_title)
        is_writing = _is_writing_question(question_type, section_title)
        if is_translation:
            should_save = True
        else:
            should_save = is_wrong or has_note
            if not should_save:
                continue
            if not is_writing and not has_note and not _has_answer(student_answer):
                continue

        entry_id = _wrong_entry_id(str(paper.get("id") or ""), question_id)
        previous = by_id.get(entry_id, {})
        tags = categories.get(question_id) or categories.get(str(result.get("number") or "")) or []
        tags = [tag for tag in tags if tag in CATEGORY_LABELS]
        seen_at = _now()
        explanation = "\n".join(
            text
            for text in [
                str(result.get("reason") or "").strip(),
                str(result.get("suggestion") or "").strip(),
            ]
            if text
        )
        wrong_history = previous.get("wrong_history")
        if not isinstance(wrong_history, list):
            wrong_history = []
        if is_wrong:
            wrong_history.append(
                {
                    "attempt_id": attempt_id,
                    "student_answer": student_answer,
                    "correct_answer": result.get("correct_answer"),
                    "explanation": explanation,
                    "seen_at": seen_at,
                }
            )
        previous_phrases = _normalize_text_list(previous.get("key_phrases"))
        key_phrases = _normalize_text_list(result.get("key_phrases")) or previous_phrases
        stem = str(question.get("stem") or "")
        if _is_cloze_question(question_type, section_title):
            stem = _extract_cloze_sentence(
                context.get("context_text", ""),
                result.get("number") or question.get("number"),
            ) or stem
        previous_status = str(previous.get("status") or "unreviewed")
        if previous_status not in WRONG_BOOK_STATUSES:
            previous_status = "unreviewed"
        entry = {
            "id": entry_id,
            "paper_id": paper.get("id"),
            "paper_title": paper.get("title") or "",
            "question_id": question_id,
            "number": str(result.get("number") or question.get("number") or ""),
            "section_title": section_title,
            "question_type": question_type,
            "exam_type": _wrong_book_exam_type(question_type, section_title),
            "context_key": context.get("context_key") or "",
            "stem": stem,
            "options": question.get("options") or [],
            "student_answer": student_answer,
            "correct_answer": result.get("correct_answer"),
            "key_phrases": key_phrases,
            "reason": result.get("reason") or "",
            "suggestion": result.get("suggestion") or "",
            "explanation": explanation,
            "categories": tags or previous.get("categories") or [],
            "source_pages": question.get("source_pages") or [],
            "status": "unreviewed" if is_wrong else previous_status,
            "is_correct": result.get("is_correct"),
            "saved_reason": (
                "wrong_answer"
                if is_wrong
                else "translation_all"
                if is_translation
                else "question_note"
            ),
            "wrong_count": int(previous.get("wrong_count") or 0) + int(is_wrong),
            "wrong_history": wrong_history,
            "review_count": int(previous.get("review_count") or 0),
            "correct_review_count": int(previous.get("correct_review_count") or 0),
            "review_history": previous.get("review_history") or [],
            "note": note if note is not None else previous.get("note") or "",
            "note_updated_at": (
                seen_at if note is not None else previous.get("note_updated_at") or ""
            ),
            "first_seen_at": previous.get("first_seen_at") or seen_at,
            "last_seen_at": seen_at,
        }
        by_id[entry_id] = entry
        wrong_ids.append(entry_id)
    _write_json(WRONG_BOOK_PATH, list(by_id.values()))
    return wrong_ids


def list_wrong_questions(
    *,
    category: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    entries = _read_json(WRONG_BOOK_PATH, [])
    if not isinstance(entries, list):
        return []
    paper_cache: dict[str, dict[str, Any] | None] = {}
    context_map_cache: dict[str, dict[str, dict[str, Any]]] = {}
    changed = False
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        section_title = str(entry.get("section_title") or "")
        question_type = str(entry.get("question_type") or "")
        paper_id = str(entry.get("paper_id") or "")
        if paper_id not in paper_cache:
            paper_path = PROJECT_DIR / "data" / "papers" / f"{_safe_id(paper_id)}.json"
            paper_cache[paper_id] = _read_json(paper_path, None)
        paper = paper_cache[paper_id]
        question_id = str(entry.get("question_id") or "")
        if isinstance(paper, dict) and paper_id not in context_map_cache:
            context_map_cache[paper_id] = _question_context_map(paper)
        context = context_map_cache.get(paper_id, {}).get(question_id, {})
        exam_type = _wrong_book_exam_type(question_type, section_title)
        context_key = context.get("context_key") if exam_type in {"cloze", "reading"} else ""
        if entry.get("exam_type") != exam_type:
            entry["exam_type"] = exam_type
            changed = True
        if entry.get("context_key") != (context_key or ""):
            entry["context_key"] = context_key or ""
            changed = True
        if exam_type == "cloze":
            stem = _extract_cloze_sentence(context.get("context_text", ""), entry.get("number"))
            if stem and entry.get("stem") != stem:
                entry["stem"] = stem
                changed = True
    if changed:
        _write_json(WRONG_BOOK_PATH, entries)
    filtered = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if category and category not in entry.get("categories", []):
            continue
        if status and entry.get("status") != status:
            continue
        filtered.append(entry)
    return sorted(filtered, key=lambda item: item.get("last_seen_at") or "", reverse=True)


def get_wrong_question_contexts(
    entries: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    contexts: dict[str, dict[str, Any]] = {}
    paper_cache: dict[str, dict[str, Any] | None] = {}
    context_map_cache: dict[str, dict[str, dict[str, Any]]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("exam_type") not in {"cloze", "reading"}:
            continue
        paper_id = str(entry.get("paper_id") or "")
        if paper_id not in paper_cache:
            paper_path = PROJECT_DIR / "data" / "papers" / f"{_safe_id(paper_id)}.json"
            paper_cache[paper_id] = _read_json(paper_path, None)
        paper = paper_cache[paper_id]
        if not isinstance(paper, dict):
            continue
        if paper_id not in context_map_cache:
            context_map_cache[paper_id] = _question_context_map(paper)
        question_id = str(entry.get("question_id") or "")
        context = context_map_cache[paper_id].get(question_id, {})
        review_context = context.get("review_context")
        context_key = str(context.get("context_key") or "")
        if context_key and isinstance(review_context, dict):
            contexts[context_key] = review_context
    return contexts


def delete_wrong_question(entry_id: str) -> dict[str, Any] | None:
    entries = _read_json(WRONG_BOOK_PATH, [])
    if not isinstance(entries, list):
        return None
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or str(entry.get("id")) != entry_id:
            continue
        deleted = entries.pop(index)
        _write_json(WRONG_BOOK_PATH, entries)
        return deleted
    return None


def mark_wrong_question_reviewed(entry_id: str) -> dict[str, Any] | None:
    entries = _read_json(WRONG_BOOK_PATH, [])
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if not isinstance(entry, dict) or str(entry.get("id")) != entry_id:
            continue
        if entry.get("status") == "mastered":
            return entry
        entry["status"] = "reviewed"
        entry["review_count"] = int(entry.get("review_count") or 0) + 1
        entry["reviewed_at"] = _now()
        _write_json(WRONG_BOOK_PATH, entries)
        return entry
    return None


def record_wrong_question_attempt(
    entry_id: str,
    *,
    answer: Any,
    is_correct: bool,
) -> dict[str, Any] | None:
    entries = _read_json(WRONG_BOOK_PATH, [])
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if not isinstance(entry, dict) or str(entry.get("id")) != entry_id:
            continue
        reviewed_at = _now()
        history = entry.get("review_history")
        if not isinstance(history, list):
            history = []
        history.append(
            {
                "answer": answer,
                "is_correct": bool(is_correct),
                "reviewed_at": reviewed_at,
            }
        )
        entry["review_history"] = history
        entry["review_count"] = int(entry.get("review_count") or 0) + 1
        entry["correct_review_count"] = int(entry.get("correct_review_count") or 0) + int(is_correct)
        entry["last_review_answer"] = answer
        entry["last_review_correct"] = bool(is_correct)
        entry["reviewed_at"] = reviewed_at
        entry["status"] = "mastered" if is_correct else "unreviewed"
        _write_json(WRONG_BOOK_PATH, entries)
        return entry
    return None


def update_wrong_question(
    entry_id: str,
    *,
    note: str | None = None,
    categories: list[str] | None = None,
    status: str | None = None,
) -> dict[str, Any] | None:
    if status is not None and status not in WRONG_BOOK_STATUSES:
        raise ValueError("错题状态必须是 unreviewed、reviewed 或 mastered")
    if categories is not None:
        invalid = [category for category in categories if category not in CATEGORY_LABELS]
        if invalid:
            raise ValueError(f"不支持的不会类型：{invalid[0]}")

    entries = _read_json(WRONG_BOOK_PATH, [])
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if not isinstance(entry, dict) or str(entry.get("id")) != entry_id:
            continue
        if note is not None:
            entry["note"] = str(note).strip()
        if categories is not None:
            entry["categories"] = list(dict.fromkeys(categories))
        if status is not None:
            entry["status"] = status
        entry["updated_at"] = _now()
        _write_json(WRONG_BOOK_PATH, entries)
        return entry
    return None


def _normalize_date(value: str | None = None) -> str:
    text = str(value or "").strip()
    if not text:
        return datetime.now().date().isoformat()
    try:
        return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise ValueError("日期必须使用 YYYY-MM-DD 格式") from exc


def _empty_daily_plan(date: str) -> dict[str, Any]:
    now = _now()
    return {
        "date": date,
        "effective_minutes": 0,
        "paused": False,
        "tasks": [],
        "report": None,
        "created_at": now,
        "updated_at": now,
        "version": 0,
    }


def _load_daily_data() -> dict[str, Any]:
    data = _read_json(DAILY_PLAN_PATH, {"plans": {}, "history": []})
    if not isinstance(data, dict):
        return {"plans": {}, "history": []}
    if not isinstance(data.get("plans"), dict):
        data["plans"] = {}
    if not isinstance(data.get("history"), list):
        data["history"] = []
    return data


def _save_daily_data(data: dict[str, Any]) -> None:
    _write_json(DAILY_PLAN_PATH, data)


def _normalize_task(task: dict[str, Any], index: int) -> dict[str, Any]:
    raw_id = str(task.get("id") or "").strip()
    status = str(task.get("status") or "pending").strip()
    if status not in {"pending", "active", "paused", "completed", "skipped", "deferred"}:
        status = "pending"
    planned_minutes = max(0, int(task.get("planned_minutes") or task.get("minutes") or 0))
    actual_seconds = max(0, int(task.get("actual_seconds") or 0))
    return {
        "id": raw_id or uuid4().hex,
        "order": int(task.get("order") or index + 1),
        "title": str(task.get("title") or task.get("name") or "未命名任务").strip(),
        "type": str(task.get("type") or "其他").strip(),
        "planned_minutes": planned_minutes,
        "acceptance": str(task.get("acceptance") or task.get("completion_standard") or "").strip(),
        "priority": str(task.get("priority") or "normal").strip(),
        "status": status,
        "actual_seconds": actual_seconds,
        "active_started_at": task.get("active_started_at"),
        "completed_at": task.get("completed_at"),
        "updated_at": task.get("updated_at"),
        "notes": str(task.get("notes") or "").strip(),
        "carried_from": task.get("carried_from"),
        "carried_to": task.get("carried_to"),
    }


def _materialize_plan(plan: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    tasks = []
    for index, raw_task in enumerate(plan.get("tasks") or []):
        if not isinstance(raw_task, dict):
            continue
        task = _normalize_task(raw_task, index)
        elapsed_seconds = task["actual_seconds"]
        if task["status"] == "active" and task.get("active_started_at"):
            try:
                started_at = datetime.fromisoformat(str(task["active_started_at"]))
                if started_at.tzinfo is None:
                    started_at = started_at.replace(tzinfo=timezone.utc)
                elapsed_seconds += max(0, int((now - started_at).total_seconds()))
            except ValueError:
                task["active_started_at"] = None
        task["elapsed_seconds"] = elapsed_seconds
        tasks.append(task)
    plan["tasks"] = sorted(tasks, key=lambda item: (int(item.get("order") or 0), item["id"]))
    plan["planned_minutes"] = sum(int(task.get("planned_minutes") or 0) for task in tasks)
    plan["actual_seconds"] = sum(int(task.get("elapsed_seconds") or 0) for task in tasks)
    plan["completed_count"] = sum(1 for task in tasks if task.get("status") == "completed")
    plan["task_count"] = len(tasks)
    plan["report_text"] = _build_daily_report_text(plan)
    return plan


def _settle_task(task: dict[str, Any]) -> None:
    started_at = task.get("active_started_at")
    if not started_at:
        return
    try:
        started = datetime.fromisoformat(str(started_at))
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        elapsed = max(0, int((datetime.now(timezone.utc) - started).total_seconds()))
        task["actual_seconds"] = max(0, int(task.get("actual_seconds") or 0)) + elapsed
    except ValueError:
        pass
    task["active_started_at"] = None


def get_daily_plan(date: str | None = None) -> dict[str, Any]:
    date_key = _normalize_date(date)
    data = _load_daily_data()
    plan = data["plans"].get(date_key)
    if not isinstance(plan, dict):
        plan = _empty_daily_plan(date_key)
    else:
        plan = {**_empty_daily_plan(date_key), **plan, "date": date_key}
    return _materialize_plan(plan)


def save_daily_plan(
    *,
    date: str,
    effective_minutes: int,
    tasks: list[dict[str, Any]],
    title: str = "",
    paused: bool = False,
    source: str = "assistant",
) -> dict[str, Any]:
    date_key = _normalize_date(date)
    data = _load_daily_data()
    previous = data["plans"].get(date_key)
    if isinstance(previous, dict) and previous.get("tasks"):
        data["history"].append(
            {
                "date": date_key,
                "saved_at": _now(),
                "source": source,
                "tasks": previous.get("tasks") or [],
                "effective_minutes": previous.get("effective_minutes") or 0,
            }
        )
        data["history"] = data["history"][-100:]
    old_plan = previous if isinstance(previous, dict) else _empty_daily_plan(date_key)
    normalized_tasks = [_normalize_task(task, index) for index, task in enumerate(tasks or []) if isinstance(task, dict)]
    plan = {
        **_empty_daily_plan(date_key),
        **old_plan,
        "date": date_key,
        "title": str(title or "").strip(),
        "effective_minutes": max(0, int(effective_minutes or 0)),
        "paused": bool(paused),
        "tasks": normalized_tasks,
        "version": int(old_plan.get("version") or 0) + 1,
        "updated_at": _now(),
        "source": source,
        "report": old_plan.get("report"),
    }
    data["plans"][date_key] = plan
    _save_daily_data(data)
    return _materialize_plan(plan)


def update_daily_plan_state(date: str, *, paused: bool) -> dict[str, Any]:
    date_key = _normalize_date(date)
    data = _load_daily_data()
    plan = data["plans"].get(date_key)
    if not isinstance(plan, dict):
        plan = _empty_daily_plan(date_key)
    if paused:
        for task in plan.get("tasks", []):
            if isinstance(task, dict) and task.get("status") == "active":
                _settle_task(task)
                task["status"] = "paused"
    plan["paused"] = bool(paused)
    plan["updated_at"] = _now()
    data["plans"][date_key] = plan
    _save_daily_data(data)
    return _materialize_plan(plan)


def update_daily_task(date: str, task_id: str, action: str) -> dict[str, Any] | None:
    date_key = _normalize_date(date)
    data = _load_daily_data()
    plan = data["plans"].get(date_key)
    if not isinstance(plan, dict):
        return None
    task = next((item for item in plan.get("tasks", []) if isinstance(item, dict) and str(item.get("id")) == str(task_id)), None)
    if task is None:
        return None

    action = str(action or "").strip().lower()
    now = _now()
    if action in {"start", "resume"}:
        if plan.get("paused"):
            raise ValueError("今天的计划已经暂停，请先恢复今天的计划")
        for other in plan.get("tasks", []):
            if isinstance(other, dict) and other is not task and other.get("status") == "active":
                _settle_task(other)
                other["status"] = "paused"
                other["updated_at"] = now
        task["status"] = "active"
        task["active_started_at"] = task.get("active_started_at") or now
    elif action == "pause":
        _settle_task(task)
        task["status"] = "paused"
    elif action == "complete":
        _settle_task(task)
        task["status"] = "completed"
        task["completed_at"] = now
    elif action == "skip":
        _settle_task(task)
        task["status"] = "skipped"
    elif action == "reset":
        _settle_task(task)
        task["status"] = "pending"
        task["completed_at"] = None
    elif action == "carryover":
        _settle_task(task)
        next_date = (datetime.strptime(date_key, "%Y-%m-%d").date() + timedelta(days=1)).isoformat()
        next_plan = data["plans"].get(next_date)
        if not isinstance(next_plan, dict):
            next_plan = _empty_daily_plan(next_date)
        next_tasks = next_plan.get("tasks") if isinstance(next_plan.get("tasks"), list) else []
        carried = {
            **_normalize_task(task, len(next_tasks)),
            "id": uuid4().hex,
            "order": len(next_tasks) + 1,
            "status": "pending",
            "actual_seconds": 0,
            "active_started_at": None,
            "completed_at": None,
            "carried_from": date_key,
        }
        next_tasks.append(carried)
        next_plan["tasks"] = next_tasks
        next_plan["updated_at"] = now
        data["plans"][next_date] = next_plan
        task["status"] = "deferred"
        task["carried_to"] = next_date
    else:
        raise ValueError("不支持的任务操作")

    task["updated_at"] = now
    plan["updated_at"] = now
    data["plans"][date_key] = plan
    _save_daily_data(data)
    return _materialize_plan(plan)


def save_daily_feedback(
    *,
    date: str,
    planned_minutes: int,
    actual_minutes: int,
    vocabulary_reviewed: int = 0,
    vocabulary_correct: int = 0,
    phrase_reviewed: int = 0,
    phrase_correct: int = 0,
    questions_completed: int = 0,
    questions_correct: int = 0,
    asked_questions: str = "",
    unknown_items: str = "",
    weak_points: str = "",
    mood: str = "",
    next_available_minutes: int = 0,
    notes: str = "",
) -> dict[str, Any]:
    date_key = _normalize_date(date)
    data = _load_daily_data()
    plan = data["plans"].get(date_key)
    if not isinstance(plan, dict):
        plan = _empty_daily_plan(date_key)
    report = {
        "date": date_key,
        "planned_minutes": max(0, int(planned_minutes or 0)),
        "actual_minutes": max(0, int(actual_minutes or 0)),
        "vocabulary_reviewed": max(0, int(vocabulary_reviewed or 0)),
        "vocabulary_correct": max(0, int(vocabulary_correct or 0)),
        "phrase_reviewed": max(0, int(phrase_reviewed or 0)),
        "phrase_correct": max(0, int(phrase_correct or 0)),
        "questions_completed": max(0, int(questions_completed or 0)),
        "questions_correct": max(0, int(questions_correct or 0)),
        "asked_questions": str(asked_questions or "").strip(),
        "unknown_items": str(unknown_items or "").strip(),
        "weak_points": str(weak_points or "").strip(),
        "mood": str(mood or "").strip(),
        "next_available_minutes": max(0, int(next_available_minutes or 0)),
        "notes": str(notes or "").strip(),
        "updated_at": _now(),
    }
    plan["report"] = report
    plan["updated_at"] = report["updated_at"]
    data["plans"][date_key] = plan
    _save_daily_data(data)
    return _materialize_plan(plan)


def _report_value(value: Any, fallback: str = "无") -> str:
    text = str(value or "").strip()
    return text or fallback


def _build_daily_report_text(plan: dict[str, Any]) -> str:
    report = plan.get("report") or {}
    if not isinstance(report, dict) or not report.get("updated_at"):
        return ""
    tasks = plan.get("tasks") or []
    completed = [task.get("title") for task in tasks if task.get("status") == "completed"]
    unfinished = [task.get("title") for task in tasks if task.get("status") not in {"completed", "skipped"}]
    return "\n".join(
        [
            f"日期：{report.get('date') or plan.get('date')}",
            f"计划有效学习时间：{int(report.get('planned_minutes') or 0)}分钟",
            f"实际有效学习时间：{int(report.get('actual_minutes') or 0)}分钟",
            f"已完成：{_report_value('、'.join(completed))}",
            f"未完成：{_report_value('、'.join(unfinished))}",
            f"单词复习：{int(report.get('vocabulary_reviewed') or 0)}个，测试正确{int(report.get('vocabulary_correct') or 0)}个",
            f"短语复习：{int(report.get('phrase_reviewed') or 0)}个，测试正确{int(report.get('phrase_correct') or 0)}个",
            f"真题完成：{int(report.get('questions_completed') or 0)}道，正确{int(report.get('questions_correct') or 0)}道",
            f"今天问过的题：{_report_value(report.get('asked_questions'))}",
            f"仍然不会：{_report_value(report.get('unknown_items'))}",
            f"新增薄弱点：{_report_value(report.get('weak_points'))}",
            f"明天可用学习时间：{int(report.get('next_available_minutes') or 0)}分钟",
            f"精神状态：{_report_value(report.get('mood'))}",
            f"补充说明：{_report_value(report.get('notes'))}",
        ]
    )
