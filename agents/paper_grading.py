from __future__ import annotations

from agentclaw import Input, Workflow

from paper_generator import (
    PaperGenerationError,
    flatten_questions_for_grading,
    grade_objective_items,
    grade_subjective_items_with_ai,
    merge_grade_results,
    normalize_paper_for_grading,
    read_paper,
    split_grading_items,
)


workflow = Workflow(
    id="paper_grading",
    name="AI 试卷判卷工作流",
    description="读取试卷 JSON、整理作答、调用模型判卷并返回每题错因的显式节点工作流。",
    timeout=1800,
    inputs=[
        Input("paper_id", str, required=True, description="试卷 ID"),
        Input("answers", dict, required=False, default={}, description="学生作答，key 为题目 id"),
    ],
)


@workflow.node(id="load_paper", output_to_user=False, description="读取并校验试卷")
def load_paper(state):
    paper_id = str(state.get("paper_id") or "").strip()
    if not paper_id:
        raise PaperGenerationError("缺少试卷 ID")
    try:
        paper = read_paper(paper_id)
    except FileNotFoundError as exc:
        raise PaperGenerationError("试卷不存在") from exc
    if paper.get("type") == "paper_collection":
        raise PaperGenerationError("请选择具体一套试卷后再提交")
    return {
        "paper_id": paper_id,
        "paper": paper,
        "workflow_stage": "paper_loaded",
    }


@workflow.node(id="normalize_answers", output_to_user=False, description="整理学生作答")
def normalize_answers(state):
    answers = state.get("answers") or {}
    if not isinstance(answers, dict):
        raise PaperGenerationError("answers 必须是对象")
    return {
        "answers": answers,
        "answer_count": len([value for value in answers.values() if value not in ("", None, [])]),
        "workflow_stage": "answers_normalized",
    }


@workflow.node(id="normalize_paper", output_to_user=False, description="归一化试卷结构与 100 分分值")
def normalize_paper(state):
    normalized_paper = normalize_paper_for_grading(state["paper"])
    return {
        "normalized_paper": normalized_paper,
        "workflow_stage": "paper_normalized",
    }


@workflow.node(id="flatten_questions", output_to_user=False, description="展开试卷题目为判卷条目")
def flatten_questions(state):
    questions = flatten_questions_for_grading(state["normalized_paper"])
    return {
        "grading_questions": questions,
        "question_count": len(questions),
        "workflow_stage": "questions_flattened",
    }


@workflow.node(id="split_grading_items", output_to_user=False, description="拆分客观题和需要 AI 判卷的题")
def split_items_for_grading(state):
    items = split_grading_items(
        questions=state["grading_questions"],
        answers=state["answers"],
    )
    return {
        "objective_items": items["objective_items"],
        "ai_items": items["ai_items"],
        "objective_count": len(items["objective_items"]),
        "ai_count": len(items["ai_items"]),
        "workflow_stage": "grading_items_split",
    }


@workflow.node(id="grade_objective_items", output_to_user=False, description="确定性判客观题")
def grade_objective(state):
    objective_results = grade_objective_items(state["objective_items"])
    return {
        "objective_results": objective_results,
        "workflow_stage": "objective_graded",
    }


@workflow.node(id="grade_subjective_items", output_to_user=False, description="调用模型判主观题/无答案题")
async def grade_subjective(state, context):
    llm = context.llm_manager
    if llm is None:
        raise PaperGenerationError("工作流 LLMManager 未初始化")
    ai_results = await grade_subjective_items_with_ai(
        llm=llm,
        paper=state["normalized_paper"],
        ai_items=state["ai_items"],
    )
    return {
        "ai_results": ai_results,
        "workflow_stage": "subjective_graded",
    }


@workflow.node(id="merge_grade_results", output_to_user=False, description="合并判卷结果并计算总分")
def merge_results(state):
    grade_result = merge_grade_results(
        paper=state["normalized_paper"],
        answers=state["answers"],
        questions=state["grading_questions"],
        objective_results=state["objective_results"],
        ai_results=state["ai_results"],
    )
    return {
        "grade_result": grade_result,
        "total_score": grade_result.get("total_score", 0),
        "workflow_stage": "graded",
    }


@workflow.node(id="format_response", output_to_user=True, description="生成判卷响应摘要")
def format_response(state):
    grade_result = state["grade_result"]
    return {
        "paper_grading_summary": {
            "paper_id": grade_result.get("paper_id"),
            "total_score": grade_result.get("total_score"),
            "max_score": grade_result.get("max_score"),
            "question_count": grade_result.get("question_count"),
            "correct_count": grade_result.get("correct_count"),
        }
    }


workflow.add_edge("__start__", "load_paper")
workflow.add_edge("load_paper", "normalize_answers")
workflow.add_edge("normalize_answers", "normalize_paper")
workflow.add_edge("normalize_paper", "flatten_questions")
workflow.add_edge("flatten_questions", "split_grading_items")
workflow.add_edge("split_grading_items", "grade_objective_items")
workflow.add_edge("grade_objective_items", "grade_subjective_items")
workflow.add_edge("grade_subjective_items", "merge_grade_results")
workflow.add_edge("merge_grade_results", "format_response")
workflow.add_edge("format_response", "__end__")

workflow.publish()
