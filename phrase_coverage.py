"""Compare phrase-list PDFs with the saved 2021-2025 true exams.

Examples:
    python phrase_coverage.py highschool.pdf middle_school.pdf
    python phrase_coverage.py highschool.pdf middle_school.pdf --out data/phrase_coverage.json --format json
    python phrase_coverage.py highschool.pdf middle_school.pdf --exams-dir data/papers --out data/phrase_coverage.md --format markdown
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


try:
    import fitz
except ImportError as exc:
    raise SystemExit("缺少 PyMuPDF，请运行: python -m pip install pymupdf") from exc


PLACEHOLDERS = {
    "sb",
    "sth",
    "somebody",
    "someone",
    "something",
    "somewhere",
    "__var__",
}


def normalize_phrase(value: str) -> str:
    value = value.replace("…", "...").replace("－", "-")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def extract_phrase_items(pdf_path: Path) -> list[dict[str, Any]]:
    """Extract numbered English phrases from the Word column of a PDF."""

    items: list[dict[str, Any]] = []
    with fitz.open(pdf_path) as document:
        for page_number, page in enumerate(document, start=1):
            for block in page.get_text("blocks"):
                block_text = block[4].strip()
                match = re.match(r"^(\d+)\s*\n(.+)$", block_text, flags=re.S)
                if not match:
                    continue
                number = int(match.group(1))
                phrase = normalize_phrase(match.group(2))
                if not phrase or phrase.lower() in {"word", "meaning"}:
                    continue
                items.append(
                    {
                        "number": number,
                        "phrase": phrase,
                        "page": page_number,
                    }
                )

    unique: dict[int, dict[str, Any]] = {}
    for item in items:
        unique.setdefault(item["number"], item)
    return [unique[number] for number in sorted(unique)]


def _question_text(question: dict[str, Any]) -> str:
    pieces = [str(question.get("stem") or ""), str(question.get("description") or "")]
    for option in question.get("options") or []:
        pieces.append(str(option.get("text") or ""))
    return " ".join(piece for piece in pieces if piece)


def load_exam_corpus(exams_dir: Path) -> list[dict[str, Any]]:
    corpus: list[dict[str, Any]] = []
    for path in sorted(exams_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        sections = data.get("sections") or []
        if not sections:
            continue
        title = str(data.get("title") or path.stem)
        year_match = re.search(r"(20\d{2})", title)
        year = year_match.group(1) if year_match else path.stem
        for section in sections:
            section_id = str(section.get("id") or "")
            if section_id not in {
                "section-vocabulary",
                "section-cloze",
                "section-reading",
            }:
                continue
            section_texts: list[str] = []
            description = str(section.get("description") or "")
            if description:
                section_texts.append(description)
            question_records: list[dict[str, Any]] = []
            for question in section.get("questions") or []:
                question_text = _question_text(question)
                section_texts.append(question_text)
                question_records.append(
                    {
                        "number": str(question.get("number") or ""),
                        "text": question_text,
                    }
                )
            corpus.append(
                {
                    "year": year,
                    "title": title,
                    "source_file": path.name,
                    "section": section_id.removeprefix("section-"),
                    "question_count": len(section.get("questions") or []),
                    "questions": question_records,
                    "text": " ".join(section_texts),
                }
            )
    return corpus


def normalize_exam_text(value: str) -> str:
    value = value.lower().replace("’", "'")
    value = re.sub(r"[^a-z0-9']+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _phrase_tokens(phrase: str) -> list[str]:
    phrase = re.sub(r"\bA\b|\bB\b", "__var__", phrase)
    phrase = phrase.lower().replace("…", "...")
    return re.findall(r"[a-z0-9]+(?:/[a-z0-9]+)+|[a-z0-9]+|\.\.\.", phrase)


def phrase_pattern(phrase: str) -> re.Pattern[str]:
    parts: list[str] = []
    for token in _phrase_tokens(phrase):
        if token in PLACEHOLDERS or token == "...":
            parts.append(r"[a-z0-9']+(?:\s+[a-z0-9']+){0,2}")
            continue
        if "/" in token:
            alternatives = token.split("/")
            parts.append(
                r"(?:" + "|".join(re.escape(item) for item in alternatives) + r")"
            )
            continue
        parts.append(re.escape(token))
    if not parts:
        return re.compile(r"(?!x)x")
    return re.compile(
        r"(?<![a-z0-9'])" + r"\s+".join(parts) + r"(?![a-z0-9'])"
    )


def match_phrase(
    phrase: str,
    corpus_text: str,
) -> int:
    normalized = normalize_exam_text(corpus_text)
    return len(phrase_pattern(phrase).findall(normalized))


def question_coverage(
    phrase_results: list[dict[str, Any]],
    corpus: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, int]], dict[str, dict[str, int]]]:
    by_section: dict[str, dict[str, int]] = {}
    by_year: dict[str, dict[str, int]] = {}
    for entry in corpus:
        section = entry["section"]
        year = entry["year"]
        by_section.setdefault(
            section,
            {"question_count": 0, "matched_questions": 0},
        )
        by_year.setdefault(
            year,
            {"question_count": 0, "matched_questions": 0},
        )
        for question in entry.get("questions") or []:
            by_section[section]["question_count"] += 1
            by_year[year]["question_count"] += 1
            matched = any(
                match_phrase(result["phrase"], question["text"]) > 0
                for result in phrase_results
            )
            if matched:
                by_section[section]["matched_questions"] += 1
                by_year[year]["matched_questions"] += 1
    for summary in [*by_section.values(), *by_year.values()]:
        total = summary["question_count"]
        summary["coverage_percent"] = round(
            summary["matched_questions"] / total * 100, 2
        ) if total else 0
    return by_section, by_year


def analyze(
    phrase_pdfs: list[Path],
    exams_dir: Path,
) -> dict[str, Any]:
    phrase_lists: list[dict[str, Any]] = []
    for pdf_path in phrase_pdfs:
        items = extract_phrase_items(pdf_path)
        phrase_lists.append(
            {
                "file": str(pdf_path.resolve()),
                "file_name": pdf_path.name,
                "title": fitz.open(pdf_path).metadata.get("title", ""),
                "count": len(items),
                "items": items,
            }
        )

    corpus = load_exam_corpus(exams_dir)
    years = sorted({entry["year"] for entry in corpus})
    corpus_by_year: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in corpus:
        corpus_by_year[entry["year"]].append(entry)

    all_exam_text = " ".join(entry["text"] for entry in corpus)
    all_phrase_results: list[dict[str, Any]] = []
    for phrase_list in phrase_lists:
        phrase_results: list[dict[str, Any]] = []
        for item in phrase_list["items"]:
            by_year: dict[str, int] = {}
            by_section: dict[str, int] = {}
            total = 0
            for year, entries in corpus_by_year.items():
                year_count = sum(match_phrase(item["phrase"], entry["text"]) for entry in entries)
                if year_count:
                    by_year[year] = year_count
                    total += year_count
            for entry in corpus:
                section_count = match_phrase(item["phrase"], entry["text"])
                if section_count:
                    by_section[entry["section"]] = (
                        by_section.get(entry["section"], 0) + section_count
                    )
            if total:
                phrase_results.append(
                    {
                        **item,
                        "occurrences": total,
                        "years": by_year,
                        "sections": by_section,
                    }
                )

        section_summary: dict[str, dict[str, int]] = {}
        for section in ("vocabulary", "cloze", "reading"):
            matched = {
                result["phrase"]
                for result in phrase_results
                if section in result["sections"]
            }
            occurrences = sum(
                result["sections"].get(section, 0) for result in phrase_results
            )
            section_summary[section] = {
                "matched_phrases": len(matched),
                "occurrences": occurrences,
            }

        by_year_summary: dict[str, dict[str, int]] = {}
        for year in years:
            matched = {
                result["phrase"]
                for result in phrase_results
                if year in result["years"]
            }
            by_year_summary[year] = {
                "matched_phrases": len(matched),
                "occurrences": sum(result["years"].get(year, 0) for result in phrase_results),
            }

        phrase_list["matched_count"] = len(phrase_results)
        phrase_list["coverage_percent"] = round(
            len(phrase_results) / phrase_list["count"] * 100, 2
        ) if phrase_list["count"] else 0
        phrase_list["occurrences"] = sum(
            result["occurrences"] for result in phrase_results
        )
        phrase_list["by_section"] = section_summary
        phrase_list["by_year"] = by_year_summary
        phrase_list["matches"] = sorted(
            phrase_results,
            key=lambda result: (-result["occurrences"], result["number"]),
        )
        phrase_list["question_by_section"], phrase_list["question_by_year"] = (
            question_coverage(phrase_results, corpus)
        )
        all_phrase_results.append(phrase_list)

    union: dict[str, set[str]] = {}
    union_matches: dict[str, dict[str, Any]] = {}
    for phrase_list in all_phrase_results:
        for result in phrase_list["matches"]:
            union.setdefault(result["phrase"].lower(), set()).add(phrase_list["title"])
            union_matches.setdefault(result["phrase"].lower(), result)

    union_question_by_section, union_question_by_year = question_coverage(
        list(union_matches.values()),
        corpus,
    )

    full_question_count = 0
    for path in sorted(exams_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("sections"):
            full_question_count += sum(
                len(section.get("questions") or [])
                for section in data["sections"]
            )
    phrase_sets = [
        {item["phrase"].lower() for item in phrase_list["items"]}
        for phrase_list in phrase_lists
    ]
    all_phrase_items = set().union(*phrase_sets) if phrase_sets else set()

    return {
        "phrase_lists": [
            {
                key: value
                for key, value in phrase_list.items()
                if key != "items"
            }
            for phrase_list in all_phrase_results
        ],
        "exam_corpus": {
            "directory": str(exams_dir.resolve()),
            "years": years,
            "exam_count": len(years),
            "section_documents": len(corpus),
            "question_count": full_question_count,
            "direct_match_question_count": sum(
                entry["question_count"] for entry in corpus
            ),
            "sections": dict(Counter(entry["section"] for entry in corpus)),
        },
        "union": {
            "matched_unique_phrases": len(union),
            "matched_by_both_lists": sum(len(titles) > 1 for titles in union.values()),
            "combined_phrase_count": len(all_phrase_items),
            "full_list_overlap": (
                len(phrase_sets[0] & phrase_sets[1])
                if len(phrase_sets) >= 2
                else 0
            ),
            "question_by_section": union_question_by_section,
            "question_by_year": union_question_by_year,
        },
        "method": {
            "matching": "case-insensitive phrase matching with limited wildcard support for sb/sth/A/B/ellipsis",
            "included_sections": ["vocabulary", "cloze", "reading"],
            "excluded_from_direct_matching": ["translation", "writing"],
            "caution": "命中表示短语出现在真题英文材料中，不等于该短语一定是正确答案或单独考点。",
        },
    }


def as_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# 真题短语覆盖度分析",
        "",
        "## 数据范围",
        "",
        f"- 真题年份：{', '.join(report['exam_corpus']['years'])}",
        f"- 真题套数：{report['exam_corpus']['exam_count']}",
        f"- 五套真题完整总题数：{report['exam_corpus']['question_count']}",
        f"- 直接匹配英文材料题数：{report['exam_corpus']['direct_match_question_count']}",
        "- 直接匹配范围：词汇语法、完形填空、阅读理解的英文材料",
        "- 翻译和作文：不进行直接英文短语命中统计",
        "",
        "> 命中只说明短语出现在真题英文材料中，不代表它就是该题的正确答案。",
        "",
        "## 书目结果",
        "",
        "| 资料 | 词组数 | 命中词组数 | 词组覆盖率 | 命中次数 |",
        "|---|---:|---:|---:|---:|",
    ]
    for item in report["phrase_lists"]:
        lines.append(
            f"| {item['title'] or item['file_name']} | {item['count']} | "
            f"{item['matched_count']} | {item['coverage_percent']}% | "
            f"{item['occurrences']} |"
        )
    lines.extend(
        [
            "",
            "## 按年份分布",
            "",
            "| 资料 | " + " | ".join(report["exam_corpus"]["years"]) + " |",
            "|---|" + "|".join("---:" for _ in report["exam_corpus"]["years"]) + "|",
        ]
    )
    for item in report["phrase_lists"]:
        values = [
            f"{item['by_year'][year]['matched_phrases']} 个 / "
            f"{item['by_year'][year]['occurrences']} 次"
            for year in report["exam_corpus"]["years"]
        ]
        lines.append(f"| {item['title'] or item['file_name']} | " + " | ".join(values) + " |")
    lines.extend(
        [
            "",
            "## 按题型分布",
            "",
            "| 资料 | 词汇语法 | 完形 | 阅读 |",
            "|---|---:|---:|---:|",
        ]
    )
    for item in report["phrase_lists"]:
        values = [
            f"{item['question_by_section'][section]['matched_questions']}/"
            f"{item['question_by_section'][section]['question_count']} 题 "
            f"({item['question_by_section'][section]['coverage_percent']}%)"
            for section in ("vocabulary", "cloze", "reading")
        ]
        lines.append(f"| {item['title'] or item['file_name']} | " + " | ".join(values) + " |")
    union_values = [
        f"{report['union']['question_by_section'][section]['matched_questions']}/"
        f"{report['union']['question_by_section'][section]['question_count']} 题 "
        f"({report['union']['question_by_section'][section]['coverage_percent']}%)"
        for section in ("vocabulary", "cloze", "reading")
    ]
    lines.append("| 两本合并（去重） | " + " | ".join(union_values) + " |")
    lines.extend(["", "## 高频命中短语", ""])
    for item in report["phrase_lists"]:
        lines.append(f"### {item['title'] or item['file_name']}")
        lines.append("")
        for result in item["matches"][:30]:
            years = ", ".join(
                f"{year}:{count}" for year, count in sorted(result["years"].items())
            )
            lines.append(f"- {result['phrase']}：{result['occurrences']} 次（{years}）")
        lines.append("")
    lines.extend(
        [
            "## 解读边界",
            "",
            "- 上面的题目覆盖率表示该题的题干、选项或阅读题文字中至少出现一个资料词组，不等于该词组就是正确答案。",
            "- 词组命中率衡量的是资料与真题英文材料的重合，不等于考试得分覆盖率。",
            "- 阅读中的命中更多反映阅读词汇熟悉度，不能直接换算成阅读题正确率。",
            "- 翻译和作文的价值要通过能否主动使用这些短语来判断，不能只看它们是否在英文题干中出现。",
            "- 由于词组资料包含固定搭配和短语动词，短词组可能有偶然命中，最终仍需结合上下文和考点位置复核。",
        ]
    )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="分析词组 PDF 对全部真题的覆盖度")
    parser.add_argument("phrase_pdfs", nargs="+", type=Path, help="词组 PDF 路径")
    parser.add_argument(
        "--exams-dir",
        type=Path,
        default=Path("data/papers"),
        help="保存真题 JSON 的目录，默认 data/papers",
    )
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    parser.add_argument("--out", type=Path, help="输出文件；不指定则输出到终端")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    report = analyze(args.phrase_pdfs, args.exams_dir)
    content = (
        json.dumps(report, ensure_ascii=False, indent=2)
        if args.format == "json"
        else as_markdown(report)
    )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(content, encoding="utf-8")
        print(f"已写入: {args.out.resolve()}")
    else:
        print(content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
