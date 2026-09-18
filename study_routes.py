from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from study_store import (
    get_daily_plan,
    save_daily_feedback,
    save_daily_plan,
    update_daily_plan_state,
    update_daily_task,
)


router = APIRouter(prefix="/api/study", tags=["study"])


class PlanSubmission(BaseModel):
    date: str
    effective_minutes: int = 0
    title: str = ""
    paused: bool = False
    source: str = "assistant"
    tasks: list[dict[str, Any]] = Field(default_factory=list)


class PlanStateSubmission(BaseModel):
    paused: bool


class TaskActionSubmission(BaseModel):
    action: str


class DailyFeedbackSubmission(BaseModel):
    planned_minutes: int = 0
    actual_minutes: int = 0
    vocabulary_reviewed: int = 0
    vocabulary_correct: int = 0
    phrase_reviewed: int = 0
    phrase_correct: int = 0
    questions_completed: int = 0
    questions_correct: int = 0
    asked_questions: str = ""
    unknown_items: str = ""
    weak_points: str = ""
    mood: str = ""
    next_available_minutes: int = 0
    notes: str = ""


@router.get("/day")
async def get_study_day(date: str | None = None):
    try:
        return get_daily_plan(date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/plan")
async def put_study_plan(plan: PlanSubmission):
    try:
        return save_daily_plan(
            date=plan.date,
            effective_minutes=plan.effective_minutes,
            title=plan.title,
            paused=plan.paused,
            source=plan.source,
            tasks=plan.tasks,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/day/{date}/state")
async def set_study_day_state(date: str, state: PlanStateSubmission):
    try:
        return update_daily_plan_state(date, paused=state.paused)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/day/{date}/tasks/{task_id}/action")
async def act_on_study_task(date: str, task_id: str, action: TaskActionSubmission):
    try:
        plan = update_daily_task(date, task_id, action.action)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if plan is None:
        raise HTTPException(status_code=404, detail="学习任务不存在")
    return plan


@router.post("/day/{date}/feedback")
async def submit_daily_feedback(date: str, feedback: DailyFeedbackSubmission):
    try:
        return save_daily_feedback(
            date=date,
            planned_minutes=feedback.planned_minutes,
            actual_minutes=feedback.actual_minutes,
            vocabulary_reviewed=feedback.vocabulary_reviewed,
            vocabulary_correct=feedback.vocabulary_correct,
            phrase_reviewed=feedback.phrase_reviewed,
            phrase_correct=feedback.phrase_correct,
            questions_completed=feedback.questions_completed,
            questions_correct=feedback.questions_correct,
            asked_questions=feedback.asked_questions,
            unknown_items=feedback.unknown_items,
            weak_points=feedback.weak_points,
            mood=feedback.mood,
            next_available_minutes=feedback.next_available_minutes,
            notes=feedback.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
