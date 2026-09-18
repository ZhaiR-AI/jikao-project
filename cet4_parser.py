"""Parse complete CET-4 OCR papers without overlapping-window duplication.

Only accept the familiar 25 listening + 30 reading question structure after
validating every number and option set. Other layouts keep the normal pipeline.
"""
import re
import unicodedata


def build_cet4_paper(paper_id, original_name, exam_hint, scoped_pages):
    if not re.search(r"四级|CET[- ]?4", original_name, re.I):
        return None
    pages = []
    for page in scoped_pages:
        lines = []
        for line in unicodedata.normalize("NFKC", page.get("text", "")).splitlines():
            if re.search(r"小红书|20\d{2}.*四级.*(?:真题|考试)", line):
                continue
            lines.append(line)
        pages.append({"page": page["page"], "text": "\n".join(lines)})
    text = "\n\n".join(page["text"] for page in pages)
    headings = list(re.finditer(r"(?im)^\s*Part\s+([IVX]+)\s+([^\n]+)", text))
    parts = {m[1]: text[m.end():headings[i + 1].start() if i + 1 < len(headings) else len(text)].strip()
             for i, m in enumerate(headings)}
    if set(parts) != {"I", "II", "III", "IV"}:
        return None
    if not all(word.lower() in next(m[2] for m in headings if m[1] == key).lower()
               for key, word in [("I", "Writing"), ("II", "Listening"), ("III", "Reading"), ("IV", "Translation")]):
        return None

    def question(number, stem, options=None, kind="single_choice", score=1):
        return {"id": f"cet-{number}", "number": str(number), "type": kind,
                "stem": stem.strip(), "options": options or [], "score": score,
                "answer": None, "analysis": "", "source_pages": []}

    def choices(body, start, end, listening=False):
        markers = list(re.finditer(r"(?m)^\s*(\d{1,2})\s*[.、]\s*", body))
        found = []
        for i, marker in enumerate(markers):
            number = int(marker[1])
            if not start <= number <= end:
                continue
            block = body[marker.end():markers[i + 1].start() if i + 1 < len(markers) else len(body)]
            block = re.split(r"(?im)^\s*(?:Section\s+[A-C]\b|Directions\s*:|Questions\s+\d+\b)", block)[0]
            options = list(re.finditer(r"(?<!\w)([A-D])\s*[).、]\s*", block))
            if sorted(m[1] for m in options) != list("ABCD"):
                return []
            parsed = [{"id": m[1], "text": re.sub(r"\s+", " ", block[m.end():options[j + 1].start() if j + 1 < len(options) else len(block)]).strip()}
                      for j, m in enumerate(options)]
            parsed.sort(key=lambda option: option["id"])
            stem = "本题的问题在听力音频中，PDF 仅提供选项。请播放原卷配套音频后作答。" if listening else block[:options[0].start()]
            found.append(question(number, stem, parsed, score=(1 if number <= 15 else 2) if listening else 2))
        return found if [int(q["number"]) for q in found] == list(range(start, end + 1)) else []

    listening = choices(parts["II"], 1, 25, True)
    sections = list(re.finditer(r"(?im)^\s*Section\s+([ABC])\s*$", parts["III"]))
    reading = {m[1]: parts["III"][m.end():sections[i + 1].start() if i + 1 < len(sections) else len(parts["III"])].strip()
               for i, m in enumerate(sections)}
    if not listening or set(reading) != {"A", "B", "C"}:
        return None
    bank_start = re.search(r"(?m)^\s*A\)\s*", reading["A"])
    if not bank_start:
        return None
    bank_text = reading["A"][bank_start.start():]
    option_matches = list(re.finditer(r"\b([A-O])\)\s*", bank_text))
    if sorted(m[1] for m in option_matches) != list("ABCDEFGHIJKLMNO"):
        return None
    bank = [{"id": m[1], "text": bank_text[m.end():option_matches[i + 1].start() if i + 1 < len(option_matches) else len(bank_text)].strip()}
            for i, m in enumerate(option_matches)]
    bank.sort(key=lambda option: option["id"])
    bank_passage = reading["A"][:bank_start.start()].strip()
    if not all(re.search(rf"_+\s*{n}\s*_+", bank_passage) for n in range(26, 36)):
        return None
    wordbank = [question(n, f"第 {n} 空", bank, score=0.5) for n in range(26, 36)]

    statements = list(re.finditer(r"(?m)^\s*(\d{2})\.\s*", reading["B"]))
    if [int(m[1]) for m in statements] != list(range(36, 46)):
        return None
    matching_passage = reading["B"][:statements[0].start()].strip()
    letters = re.findall(r"(?m)^\s*([A-Z])\)\s+", matching_passage)
    if not letters or len(letters) != len(set(letters)):
        return None
    matching = [question(int(m[1]), reading["B"][m.end():statements[i + 1].start() if i + 1 < len(statements) else len(reading["B"])],
                         [{"id": letter, "text": f"对应 {letter} 段"} for letter in letters]) for i, m in enumerate(statements)]
    passage_markers = list(re.finditer(r"(?im)^\s*Passage\s+(One|Two)\s*$", reading["C"]))
    if [m[1].lower() for m in passage_markers] != ["one", "two"]:
        return None
    groups = []
    for i, marker in enumerate(passage_markers):
        body = reading["C"][marker.end():passage_markers[i + 1].start() if i + 1 < len(passage_markers) else len(reading["C"])]
        first = re.search(r"(?m)^\s*\d{2}\.\s*", body)
        qs = choices(body, 46 + i * 5, 50 + i * 5)
        if not first or not qs:
            return None
        groups.append({"title": f"Passage {marker[1]}", "description": body[:first.start()].strip(), "questions": qs})
    definitions = [
        ("writing", "作文", 15, "", [question("作文", parts["I"], kind="essay", score=15)]),
        ("listening", "听力（第 1—15 题）", 15, "请结合原卷听力音频作答。本 PDF 未提供音频。", listening[:15]),
        ("listening", "听力（第 16—25 题）", 20, "请结合原卷听力音频作答。本 PDF 未提供音频。", listening[15:]),
        ("wordbank", "选词填空", 5, bank_passage, wordbank),
        ("matching", "阅读匹配", 10, matching_passage, matching),
        ("reading", "阅读", 20, "", []),
        ("translation", "汉译英", 15, "", [question("翻译", parts["IV"], kind="short_answer", score=15)]),
    ]
    result = []
    for index, (kind, title, score, description, qs) in enumerate(definitions):
        section = {"id": f"cet-{kind}-{index}", "type": kind, "title": title, "total_score": score,
                   "description": description, "questions": qs}
        if kind == "reading":
            section["groups"] = groups
        for q in qs + [q for g in section.get("groups", []) for q in g["questions"]]:
            if str(q["number"]).isdigit():
                n = q["number"]
                q["source_pages"] = [p["page"] for p in pages if re.search(rf"(?m)^\s*{n}\.\s|_+\s*{n}\s*_+", p["text"])]
            else:
                q["source_pages"] = [pages[0 if kind == "writing" else -1]["page"]]
        result.append(section)
    return {"id": paper_id, "title": exam_hint.get("title") or original_name.rsplit(".", 1)[0],
            "exam_format": "cet4", "description": "按原卷题型整理；练习按百分制计分：作文 15、听力 35、阅读 35、翻译 15。听力题的问题需要原卷配套音频，PDF 仅含选项。",
            "duration_minutes": 125, "total_score": 100, "sections": result}
