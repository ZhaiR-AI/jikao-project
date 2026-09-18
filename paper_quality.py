"""Conservative structural checks against the supplied OCR, never invent answers."""
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone


LABELS = {"choice": "选择题", "cloze": "完型", "reading": "阅读", "listening": "听力",
          "writing": "作文", "translation": "翻译", "wordbank": "选词填空", "matching": "阅读匹配"}


def kind(title):
    title = str(title).lower()
    for key, pattern in [("listening", r"listening|听力"), ("wordbank", r"word.?bank|选词"),
                         ("matching", r"matching|匹配"), ("cloze", r"cloze|完[型形]"),
                         ("reading", r"reading|阅读"), ("translation", r"translation|翻译|汉译英"),
                         ("writing", r"writing|composition|essay|作文|写作"),
                         ("choice", r"vocabulary|structure|grammar|choice|词汇|语法|选择")]:
        if re.search(pattern, title):
            return key
    return "other"


def section_key(section):
    title = unicodedata.normalize("NFKC", str(section.get("title", "")))
    part = re.search(r"\bPart\s+([IVX]+|\d+)\b", title, re.I)
    if part:
        return "part-" + part[1].upper()
    return section.get("type") or kind(title) if kind(title) != "other" else title.casefold().strip()


def questions(section):
    if section.get("groups"):
        return [q for group in section["groups"] for q in group.get("questions", [])]
    return section.get("questions", [])


def validate_paper(paper):
    issues = []
    def add(code, message, severity="warning", section=None, numbers=None, pages=None):
        issue = {"code": code, "message": message, "severity": severity,
                 "section": section or "", "numbers": list(numbers or []), "pages": sorted(set(pages or []))}
        if issue not in issues:
            issues.append(issue)

    sections = paper.get("sections", [])
    seen_ids, seen_numbers, actual = set(), defaultdict(dict), defaultdict(set)
    source = paper.get("ocr_pages", [])
    total_questions = 0
    for section in sections:
        label = section.get("title", "题目")
        key = section_key(section)
        skind = kind(section.get("type") or label)
        qs = questions(section)
        total_questions += len(qs)
        if not qs:
            add("empty_section", f"“{label}”没有提取到题目。", section=label)
        for q in qs:
            number, qid = str(q.get("number", "")), q.get("id")
            pages = q.get("source_pages", [])
            if not qid or qid in seen_ids:
                add("duplicate_id", f"“{label}”第 {number} 题的定位编号缺失或重复，答题卡无法准确定位。", "error", label, [number], pages)
            seen_ids.add(qid)
            if number in seen_numbers[key]:
                previous = seen_numbers[key][number]
                same = re.sub(r"\s+", "", previous.get("stem", "")) == re.sub(r"\s+", "", q.get("stem", ""))
                add("duplicate_number", f"“{label}”第 {number} 题重复出现，请核对题干及所属小题组。", "error" if same else "warning", label, [number], pages)
            seen_numbers[key][number] = q
            actual[key].add(number)
            # Source reading parts may comprise word bank, matching and passages.
            actual["kind-" + ("reading" if skind in {"wordbank", "matching"} else skind)].add(number)
            options = q.get("options") or []
            ids = [o.get("id") for o in options]
            if q.get("type") in {"single_choice", "multiple_choice"} and len(options) < 2:
                add("missing_options", f"“{label}”第 {number} 题的选项缺失。", "error", label, [number], pages)
            if len(ids) != len(set(ids)) or any(not o.get("text", "").strip() for o in options):
                add("invalid_options", f"“{label}”第 {number} 题有重复或空白选项。", "error", label, [number], pages)
            if not q.get("stem", "").strip() and skind not in {"listening", "cloze", "wordbank"}:
                add("missing_stem", f"“{label}”第 {number} 题缺少题干。", "error", label, [number], pages)
        if skind in {"reading", "cloze", "wordbank", "matching"}:
            containers = section.get("groups") or [section]
            for group in containers:
                passage = str(group.get("description") or section.get("description") or "")
                body = re.sub(r"(?is)^Directions?\s*[:：].*?(?:\n\s*\n|$)", "", passage).strip()
                if len(body) < 60:
                    add("missing_passage", f"“{label} / {group.get('title', '')}”的文章缺失或过短，请核对原文。", section=label,
                        pages=[p for q in group.get("questions", []) for p in q.get("source_pages", [])])
        score = float(section.get("score") or 0)
        total = float(section.get("total_score") or 0)
        if score and abs(score * len(qs) - total) > max(0.11, len(qs) * 0.011):
            add("section_score", f"“{label}”的题目分值与大题总分不一致。", section=label)
    if not total_questions:
        add("no_questions", "没有提取到可作答的题目。", "error")
    if abs(sum(float(s.get("total_score") or 0) for s in sections) - float(paper.get("total_score") or 0)) > 0.11:
        add("total_score", "分项分值与试卷总分不一致。", "error")

    # Track real source headings, rather than guessing expected counts from a filename.
    source_blocks = defaultdict(list)
    current = "unscoped"
    source_kinds = {}
    for page in source:
        text = unicodedata.normalize("NFKC", page.get("text", ""))
        for line in text.splitlines():
            heading = re.match(r"\s*Part\s+([IVX]+|\d+)\s+(.+)", line, re.I)
            if heading:
                current = "part-" + heading[1].upper()
                source_kinds[current] = kind(heading[2])
            source_blocks[current].append((page.get("page"), line))
    for key, lines in source_blocks.items():
        declared = re.search(r"共\s*(?:\d+\s*篇\s*[、,，]?\s*)?(\d+)\s*题", "\n".join(line for _, line in lines))
        if declared:
            found = actual.get(key, actual.get("kind-" + source_kinds.get(key, ""), set()))
            if len(found) != int(declared[1]):
                add("declared_question_count", f"原文明确要求 {declared[1]} 题，当前大题只识别到 {len(found)} 个不同题号。",
                    "error", key, pages=[page for page, _ in lines])
        expected = defaultdict(set)
        if source_kinds.get(key) == "writing":
            source_text = "\n".join(line for _, line in lines)
            topic = re.search(r"\btopic\s*[:：]\s*(.+?)(?:\.(?:\s|$)|\n\s*\n|$)", source_text, re.I | re.S)
            if topic:
                retained = "\n".join(str(s.get("description", "")) + "\n" + "\n".join(q.get("stem", "") for q in questions(s))
                                     for s in sections if section_key(s) == key or kind(s.get("title", "")) == "writing")
                compact = lambda value: re.sub(r"\s+", "", value).casefold()
                if compact(topic[1]) not in compact(retained):
                    add("missing_writing_prompt", "作文题目未完整保留，请对照原文重新整理。", "error", key,
                        pages=[page for page, _ in lines])
        writing_outline = False
        for page_number, line in lines:
            numbered = re.match(r"\s*(\d{1,3})\s*[.、]\s+\S", line)
            if numbered and not writing_outline:
                expected[numbered[1]].add(page_number)
            if source_kinds.get(key) == "writing" and re.search(r"\boutline\b|提纲|要点", line, re.I):
                writing_outline = True
            for blank in re.findall(r"_+\s*(\d{1,3})\s*_+", line):
                expected[blank].add(page_number)
        actual_numbers = actual.get(key)
        if actual_numbers is None and key in source_kinds:
            actual_numbers = actual.get("kind-" + source_kinds[key])
        if actual_numbers is None:
            if expected:
                add("unmatched_source", "原文中的一组编号题尚无法对应到大题，请核对是否漏题或题号重新编号。",
                    numbers=sorted(expected, key=int), pages=[p for v in expected.values() for p in v])
            continue
        missing = set(expected) - actual_numbers
        if missing:
            add("missing_numbers", f"原文“{LABELS.get(source_kinds.get(key), key)}”识别到题号 { '、'.join(sorted(missing, key=int)) }，当前卷子未找到对应题目。",
                "warning", key, sorted(missing, key=int), [p for n in missing for p in expected[n]])
            missing_blanks = {n for n in missing if any(re.search(rf"_+\s*{re.escape(n)}\s*_+", line) for _, line in lines)}
            if missing_blanks:
                add("missing_blanks", f"原文明确标注了第 {'、'.join(sorted(missing_blanks, key=int))} 空，当前卷子缺少对应作答项。",
                    "error", key, sorted(missing_blanks, key=int), [p for n in missing_blanks for p in expected[n]])
        if source_kinds.get(key) in {"reading", "cloze"}:
            related = [s for s in sections if section_key(s) == key or kind(s.get("type") or s.get("title")) in
                       ({"reading", "wordbank", "matching"} if source_kinds[key] == "reading" else {"cloze"})]
            material = "\n".join(str(s.get("description", "")) + "\n" + "\n".join(g.get("description", "") for g in s.get("groups", [])) for s in related)
            # Long source prose lines should mostly survive in the rendered passages.
            source_words = {word.lower() for _, line in lines if len(line.split()) > 12 and not re.match(r"\s*(?:\d+[.、]|[A-D][).])", line)
                            for word in re.findall(r"[A-Za-z]{5,}", line)}
            material_words = set(re.findall(r"[a-z]{5,}", material.lower()))
            if len(source_words) > 60 and len(source_words & material_words) / len(source_words) < 0.55:
                add("passage_coverage", "生成文章与对应原文覆盖不足，可能漏掉跨页续文或关联到了其他文章，请核对。",
                    section=key, pages=[page for page, _ in lines])
        # Compare explicit option labels within each original numbered question.
        block = "\n".join(line for _, line in lines)
        markers = list(re.finditer(r"(?m)^\s*(\d{1,3})\s*[.、]\s+", block))
        for i, marker in enumerate(markers):
            segment = block[marker.end():markers[i + 1].start() if i + 1 < len(markers) else len(block)]
            segment = re.split(r"(?im)^\s*(?:Section\s+[A-Z]|Directions|Questions\s+\d|Passage\s+\w+)", segment)[0]
            labels = set(re.findall(r"(?<!\w)([A-D])\s*[).、]\s*", segment))
            if labels == set("ABCD"):
                candidates = [q for s in sections if section_key(s) == key or kind(s.get("type") or s.get("title")) == source_kinds.get(key)
                              for q in questions(s) if str(q.get("number")) == marker[1]]
                if candidates and any(not labels.issubset({o.get("id") for o in q.get("options", [])}) for q in candidates):
                    add("source_options", f"第 {marker[1]} 题原文有 A—D 选项，生成结果未完整保留。", "error", key, [marker[1]], expected.get(marker[1], []))
                elif not candidates and marker[1] in missing:
                    add("confirmed_missing", f"原文有第 {marker[1]} 题及 A—D 选项，但卷子中缺少该题。", "error", key, [marker[1]], expected.get(marker[1], []))
    for warning in paper.get("warnings", []):
        add("extraction_warning", "有页面提取失败或未完成，请检查对应原文。", "error", pages=warning.get("pages", []))
    if not source:
        add("no_source", "缺少可核对的原始识别文字，目前仅检查了试卷结构。")
    metadata = paper.get("source", {})
    if metadata.get("source_page_count", 0) > metadata.get("page_count", 0):
        add("limited_pages", f"原 PDF 共 {metadata['source_page_count']} 页，本次只处理了前 {metadata['page_count']} 页，不能据此确认整卷完整。")
    if paper.get("exam_format") not in {"cet4", "degree"}:
        add("unconfirmed_format", "采用原卷大题结构；非标准卷的题量与文章完整性仍需对照原文核对。")
    state = "incomplete" if any(i["severity"] == "error" for i in issues) else "review" if issues else "ready"
    return {"status": state, "label": {"ready": "生成完成", "review": "生成完成，待检查", "incomplete": "生成不完整"}[state],
            "checked_at": datetime.now(timezone.utc).isoformat(), "question_count": total_questions, "issues": issues,
            "note": "自动检查用于发现结构问题，不能代替逐题核对原卷。"}
