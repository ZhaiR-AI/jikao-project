"""Grade a wrong-book practice batch without creating an exam submission."""
from typing import Any, Awaitable, Callable

from paper_generator import grade_objective_items
from study_store import list_wrong_questions, record_wrong_question_attempt


async def submit_wrong_book_practice(
    entries: list[dict[str, Any]],
    run_grader: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    by_id = {str(item["id"]): item for item in list_wrong_questions()}
    ids = [str(entry.get("entry_id") or "") for entry in entries]
    if len(set(ids)) != len(ids):
        raise ValueError("同一道错题不能重复提交")
    if any(entry_id not in by_id for entry_id in ids):
        raise ValueError("部分错题已删除，请刷新错题本后重试")
    results = {}
    pending = {}
    for entry in entries:
        entry_id = str(entry["entry_id"])
        item = by_id[entry_id]
        answer = entry.get("answer", "")
        if answer is None or (isinstance(answer, str) and not answer.strip()) or answer == []:
            results[entry_id] = {"is_correct": None, "grading_status": "unanswered", "reason": "本题未作答。"}
            continue
        if item.get("options") and item.get("correct_answer") not in (None, "", []):
            question = {"id": entry_id, "number": item.get("number"), "answer": item["correct_answer"]}
            result = grade_objective_items([{"question": question, "student_answer": answer, "section_title": item.get("section_title", ""), "score": 1}])[entry_id]
            result["reason"] = item.get("reason") or item.get("explanation") or result["reason"]
            result["suggestion"] = item.get("suggestion") or result["suggestion"]
            results[entry_id] = result
        else:
            pending.setdefault(str(item.get("paper_id") or ""), []).append((entry_id, item, answer))

    for paper_id, batch in pending.items():
        try:
            if not paper_id or any(not item.get("question_id") for _, item, _ in batch):
                raise ValueError("缺少原卷信息，暂时无法自动判卷")
            run = await run_grader({"paper_id": paper_id, "answers": {item["question_id"]: answer for _, item, answer in batch}})
            graded = {str(result["question_id"]): result for result in run["state"]["grade_result"]["results"]}
            for entry_id, item, _ in batch:
                result = dict(graded.get(str(item["question_id"]), {}))
                if not isinstance(result.get("is_correct"), bool):
                    result.update(is_correct=None, grading_status="pending", reason=result.get("reason") or "未能完成判卷，请稍后重试。")
                results[entry_id] = result
        except Exception as exc:
            for entry_id, _, _ in batch:
                results[entry_id] = {"is_correct": None, "grading_status": "pending", "reason": f"暂未判定：{exc}"}

    output = []
    updated_items = []
    for entry in entries:
        entry_id = str(entry["entry_id"])
        item = by_id[entry_id]
        result = {**results[entry_id], "entry_id": entry_id, "student_answer": entry.get("answer", ""),
                  "previous_answer": item.get("last_review_answer", item.get("student_answer", ""))}
        result.setdefault("correct_answer", item.get("correct_answer"))
        if isinstance(result.get("is_correct"), bool):
            updated = record_wrong_question_attempt(entry_id, answer=entry.get("answer"), is_correct=result["is_correct"])
            if updated is not None:
                updated_items.append(updated)
        output.append(result)
    return {"results": output, "items": updated_items}
