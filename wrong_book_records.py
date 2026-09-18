"""Independent, durable practice records for each wrong-book question type."""
import copy
import re
from uuid import uuid4

from study_store import STUDY_DATA_DIR, _now, _read_json, _write_json, list_wrong_questions

RECORD_DIR = STUDY_DATA_DIR / "wrong_book_records"
VISIBLE_TYPES = {"choice", "translation", "reading"}


def _path(record_id):
    if not re.fullmatch(r"[a-f0-9]{32}", str(record_id)):
        raise ValueError("无效的做题记录编号")
    return RECORD_DIR / f"{record_id}.json"


def read_record(record_id):
    record = _read_json(_path(record_id), None)
    if not isinstance(record, dict):
        raise ValueError("做题记录不存在")
    return record


def delete_record(record_id):
    read_record(record_id)
    _path(record_id).unlink()
    return {"record_id": record_id, "deleted": True}


def record_summary(record):
    entries = list(record.get("draft", {}).values())
    return {key: record[key] for key in ("record_id", "exam_type", "created_at", "updated_at", "entry_ids")} | {
        "answered_count": sum(bool(entry.get("answer")) for entry in entries),
        "correct_count": sum(entry.get("result", {}).get("is_correct") is True for entry in entries if isinstance(entry.get("result"), dict)),
        "wrong_count": sum(entry.get("result", {}).get("is_correct") is False for entry in entries if isinstance(entry.get("result"), dict)),
        "submission_count": len(record.get("attempts", [])),
    }


def list_records(exam_type):
    if exam_type not in VISIBLE_TYPES:
        raise ValueError("不支持的错题类型")
    records = [_read_json(path, {}) for path in RECORD_DIR.glob("*.json")]
    return [record_summary(record) for record in sorted(
        (record for record in records if record.get("exam_type") == exam_type),
        key=lambda record: record.get("created_at", ""), reverse=True,
    )]


def create_record(exam_type, entry_ids, draft=None):
    if exam_type not in VISIBLE_TYPES:
        raise ValueError("不支持的错题类型")
    available = {str(item["id"]) for item in list_wrong_questions() if item.get("exam_type") == exam_type}
    ids = list(dict.fromkeys(entry_ids))
    if not ids or any(entry_id not in available for entry_id in ids):
        raise ValueError("题目列表为空或包含不属于当前类型的错题，请刷新后重试")
    now = _now()
    record = {"record_id": uuid4().hex, "exam_type": exam_type, "created_at": now, "updated_at": now,
              "entry_ids": ids, "draft": {key: copy.deepcopy(value) for key, value in (draft or {}).items() if key in ids}, "attempts": []}
    RECORD_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(_path(record["record_id"]), record)
    return record


def save_record(record_id, draft):
    record = read_record(record_id)
    record["draft"] = {key: copy.deepcopy(value) for key, value in draft.items() if key in record["entry_ids"]}
    record["updated_at"] = _now()
    _write_json(_path(record_id), record)
    return record


def save_record_result(record_id, results):
    record = read_record(record_id)
    for result in results:
        entry_id = result["entry_id"]
        if entry_id not in record["entry_ids"]:
            raise ValueError("提交的题目不属于本次做题记录")
        entry = record["draft"].setdefault(entry_id, {})
        entry.update(answer=result.get("student_answer", ""), result=copy.deepcopy(result), revealed=True,
                     previousAnswer=result.get("previous_answer", ""))
    record["updated_at"] = _now()
    record["attempts"].append({"submitted_at": record["updated_at"], "results": copy.deepcopy(results)})
    _write_json(_path(record_id), record)
    return record
