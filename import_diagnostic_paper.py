import json
import re
import sys
from pathlib import Path


def clean(text):
    return text.strip().replace("**", "")


def question(number, stem, options=None, kind="single_choice"):
    return dict(id=f"q{number}", number=str(number), type=kind, stem=clean(stem),
                options=options or [], answer=None, analysis="", source_pages=[])


def choices(text):
    result = []
    for match in re.finditer(r"(?ms)^(\d+)\. (.*?)(?=^\d+\. |\Z)", text):
        parts = re.split(r"(?:^|\s+)([A-D])\.\s+", match[2])
        options = [dict(id=parts[index], text=clean(parts[index + 1])) for index in range(1, len(parts), 2)]
        assert len(options) == 4
        result.append(question(int(match[1]), parts[0], options))
    return result


def build_paper(text):
    parts = re.split(r"(?m)^## Part [IVX]+ [^\n]+\n", text)
    assert len(parts) == 6
    sections = [dict(id=f"section-{index + 1}", title=title, total_score=score, questions=[])
                for index, (title, score) in enumerate(zip(
                    ["词汇和语法", "完形填空", "阅读理解", "汉译英", "短文写作"], [30, 20, 20, 15, 15]))]
    directions, vocabulary = re.split(r"(?m)(?=^1\. )", parts[1], maxsplit=1)
    sections[0]["description"] = clean(parts[0]) + "\n\n" + clean(directions)
    sections[0]["questions"] = choices(vocabulary)
    sections[1]["description"] = clean(parts[2].split("| 题号")[0])
    for match in re.finditer(r"(?m)^\|\s*(\d+)\s*\|\s*([^|]+)\|\s*([^|]+)\|", parts[2]):
        sections[1]["questions"].append(question(int(match[1]), f"请选择原文 __{match[1]}__ 处的答案。",
            [dict(id="A", text=match[2].strip()), dict(id="B", text=match[3].strip())]))
    reading = re.split(r"(?m)^### Passage \d+\s*\n", parts[3])
    sections[2]["description"] = clean(reading[0])
    sections[2]["groups"] = []
    for index, passage in enumerate(reading[1:], 1):
        description, items = re.split(r"(?m)(?=^\d+\. )", passage, maxsplit=1)
        questions = choices(items)
        sections[2]["groups"].append(dict(id=f"passage-{index}", title=f"Passage {index}",
                                           description=clean(description), questions=questions))
        sections[2]["questions"].extend(questions)
    sections[3]["description"] = clean(parts[4].split("49.")[0])
    sections[3]["questions"] = [question(int(match[1]), match[2], kind="short_answer")
        for match in re.finditer(r"(?ms)^(\d+)\. (.*?)(?=^\d+\. |\Z)", parts[4])]
    writing, submission = parts[5].split("\n---", 1)
    directions, essay = writing.split("54. ", 1)
    sections[4]["description"] = clean(directions)
    sections[4]["questions"] = [question(54, essay, kind="essay")]
    sections[0]["description"] += (
        "\n\n网页作答说明：选择选项或填写译文、作文。犹豫题可勾选标记，在笔记中写 ? 或 ??。"
        "各部分用时、查词/暂停/超时情况和最吃力部分请记在第54题笔记中。"
        "原文未附评分文件，交卷使用项目现有AI判卷，不代表官方评分。\n\n" + clean(submission))
    for section in sections:
        section["score"] = section["total_score"] / len(section["questions"])
    assert [int(item["number"]) for section in sections for item in section["questions"]] == list(range(1, 55))
    assert [len(section["questions"]) for section in sections] == [20, 20, 8, 5, 1]
    return dict(id="shandong-diagnostic-20260908-a", title="山东省学位英语考纲诊断卷 A（2026年9月8日）",
                description="原创诊断练习，非官方试卷、非押题卷。54题，100分，90分钟；原文未附答案。",
                duration_minutes=90, total_score=100, sections=sections,
                source=dict(file_name="山东省学位英语考纲诊断卷 A（用户提供文本）", collection_id="shandong-diagnostic-20260908"))


def main():
    paper = build_paper(Path(sys.argv[1]).read_text(encoding="utf-8-sig"))
    collection = dict(id=paper["source"]["collection_id"], type="paper_collection", title="山东省学位英语 · 原创诊断练习",
        description=paper["description"], source=paper["source"], papers=[dict(
            id=paper["id"], title=paper["title"], description=paper["description"], question_count=54,
            total_score=100, paper_url=f"/exam/{paper['id']}", json_url=f"/api/paper/{paper['id']}")])
    destination = Path(__file__).resolve().parent / "data" / "papers"
    for item in (paper, collection):
        (destination / f"{item['id']}.json").write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Imported 54 questions")


if __name__ == "__main__":
    main()
