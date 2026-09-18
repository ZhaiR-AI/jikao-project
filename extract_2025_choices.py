"""Extract the 2025 multiple-choice questions from the saved paper JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_INPUT = Path("data/papers/8fc1d0d6a3ee4ccbaf1a973e20c93fde-1.json")
DEFAULT_OUTPUT = Path("做的真题/2025年选择题.md")


def extract_questions(paper: dict) -> list[tuple[dict, str]]:
    questions: list[tuple[dict, str]] = []
    for section in paper.get("sections", []):
        section_title = str(section.get("title") or "")
        for question in section.get("questions", []):
            if question.get("type") == "single_choice":
                questions.append((question, section_title))
    return questions


def render_markdown(paper: dict, questions: list[tuple[dict, str]]) -> str:
    section_names = {
        "Part I": "第一部分 词汇与结构",
        "Part II": "第二部分 完形填空",
        "Part III": "第三部分 阅读理解",
    }
    lines = [
        "# 2025年山东省成人高等教育学士学位英语考试选择题",
        "",
        "> 来源：2025年山东省成人高等教育学士学位英语考试真题汇编（一）",
        "> 共48题：词汇与结构20题、完形填空20题、阅读理解8题。原始数据未提供答案，本文不补写答案。",
        "",
        "## 作答记录",
        "",
        "- 建议先独立完成，再按错题原因归类：语法、单词、词组、阅读理解。",
        "- 总分按原试卷计：词汇与结构每题1.5分，完形填空每题1分，阅读理解每题2.5分。",
        "",
    ]

    previous_section = ""
    for question, section_title in questions:
        section_key = next(
            (key for key in section_names if section_title.startswith(key)),
            "",
        )
        if section_key != previous_section:
            heading = section_names.get(section_key, section_title or "选择题")
            lines.extend([f"## {heading}", ""])
            previous_section = section_key

        number = question.get("number", "")
        stem = str(question.get("stem") or "").strip()
        lines.extend([f"### {number}. {stem}", ""])
        for option in question.get("options", []):
            option_id = str(option.get("id") or "").strip()
            option_text = str(option.get("text") or "").strip()
            lines.append(f"- **{option_id}.** {option_text}")
        source_pages = question.get("source_pages") or []
        if source_pages:
            lines.append(f"- 作答：____　原文页码：{', '.join(str(page) for page in source_pages)}")
        else:
            lines.append("- 作答：____")
        lines.append("")

    lines.extend(
        [
            "## 答题卡",
            "",
            "| 题号 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
            "| 选择 |   |   |   |   |   |   |   |   |   |   |",
            "",
            "| 题号 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
            "| 选择 |   |   |   |   |   |   |   |   |   |   |",
            "",
            "| 题号 | 21 | 22 | 23 | 24 | 25 | 26 | 27 | 28 | 29 | 30 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
            "| 选择 |   |   |   |   |   |   |   |   |   |   |",
            "",
            "| 题号 | 31 | 32 | 33 | 34 | 35 | 36 | 37 | 38 | 39 | 40 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
            "| 选择 |   |   |   |   |   |   |   |   |   |   |",
            "",
            "| 题号 | 41 | 42 | 43 | 44 | 45 | 46 | 47 | 48 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
            "| 选择 |   |   |   |   |   |   |   |   |",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract 2025 single-choice questions")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    paper = json.loads(args.input.read_text(encoding="utf-8"))
    questions = extract_questions(paper)
    if len(questions) != 48:
        raise SystemExit(f"Expected 48 single-choice questions, found {len(questions)}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_markdown(paper, questions), encoding="utf-8")
    print(f"Wrote {len(questions)} questions to {args.output}")


if __name__ == "__main__":
    main()
