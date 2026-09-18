// Layout helpers preserve original question IDs, numbering, and grading order.
function sectionKind(section) {
  if (["listening", "wordbank", "matching"].includes(section.type)) return section.type;
  const name = `${section.title || ""} ${section.type || ""}`.toLowerCase();
  if (/listening|听力/.test(name)) return "listening";
  if (/word.?bank|选词填空/.test(name)) return "wordbank";
  if (/matching|阅读匹配/.test(name)) return "matching";
  if (/cloze|完[形型]/.test(name)) return "cloze";
  if (/reading|阅读/.test(name)) return "reading";
  if (/translation|汉译英|翻译/.test(name)) return "translation";
  if (/writing|composition|essay|作文|写作/.test(name)) return "writing";
  if (/vocabulary|structure|grammar|choice|选择|词汇|语法/.test(name)) return "choice";
  return "other";
}

function sectionLabel(section) {
  return { choice: "选择题", cloze: "完形填空", translation: "汉译英", reading: "阅读", writing: "作文", listening: "听力", wordbank: "选词填空", matching: "阅读匹配" }[sectionKind(section)] || section.title || "题目";
}

function examKindOrder(paper, answerCard = false) {
  if (paper.exam_format === "cet4") return ["writing", "listening", "wordbank", "matching", "reading", "translation", "other"];
  return answerCard ? ["choice", "listening", "cloze", "wordbank", "matching", "reading", "translation", "writing", "other"]
    : ["choice", "listening", "cloze", "wordbank", "translation", "matching", "reading", "writing", "other"];
}

function usesStandardExamLayout(paper) {
  if (["cet4", "degree"].includes(paper.exam_format)) return true;
  // Keep the established degree-exam layout for older saved papers without metadata.
  const counts = {};
  for (const section of paper.sections || []) {
    const kind = sectionKind(section);
    counts[kind] = (counts[kind] || 0) + (section.groups?.length ? section.groups.flatMap(g => g.questions || []).length : (section.questions || []).length);
  }
  return counts.choice === 20 && counts.cloze === 20 && counts.reading > 0 && counts.translation > 0 && counts.writing === 1
    && Object.values(counts).reduce((sum, count) => sum + count, 0) === 54;
}

function buildExamPages(paper) {
  if (!usesStandardExamLayout(paper)) {
    return (paper.sections || []).map(section => ({ title: section.title || sectionLabel(section), sections: [section] }));
  }
  const pages = [];
  for (const kind of examKindOrder(paper)) {
    const sections = (paper.sections || []).filter((section) => sectionKind(section) === kind);
    if (!sections.length) continue;
    pages.push({ title: sectionLabel(sections[0]), sections });
  }
  return pages;
}

function activateExamPage(page) {
  hideAnnotationPopup();
  paperRoot.querySelectorAll(".exam-page").forEach((item) => { item.hidden = item !== page; });
  const ids = new Set([...page?.querySelectorAll("[data-mark]") || []].map((button) => button.dataset.mark));
  questionCard.querySelectorAll(".card-btn").forEach((button) => {
    button.classList.toggle("current-section", ids.has(button.dataset.goto));
    if (ids.has(button.dataset.goto)) button.setAttribute("aria-current", "true");
    else button.removeAttribute("aria-current");
  });
}

function navigateToQuestion(id) {
  const question = document.getElementById(`question-${id}`);
  if (!question) return;
  const page = question.closest(".exam-page");
  const switching = page.hidden;
  activateExamPage(page);
  // On entering cloze, show the article and all compact rows from the top.
  const target = switching && question.classList.contains("cloze-question") ? page : question;
  target.scrollIntoView({ behavior: switching ? "instant" : "smooth", block: "start" });
  paperRoot.querySelectorAll(".navigation-target").forEach((el) => el.classList.remove("navigation-target"));
  question.classList.add("navigation-target");
}

function compactClozeQuestion(question) {
  question.classList.add("cloze-question");
  const row = document.createElement("div");
  row.className = "cloze-row";
  const number = document.createElement("span");
  number.className = "cloze-number";
  const mark = question.querySelector("[data-mark]");
  number.dataset.number = questionCard.querySelector(`[data-goto="${cssEscape(mark.dataset.mark)}"]`)?.textContent || "";
  number.textContent = `${number.dataset.number}（）`;
  row.append(number, question.querySelector(".answer-area"), mark);
  const details = document.createElement("details");
  details.className = "cloze-tools";
  const summary = document.createElement("summary");
  summary.textContent = "分类·笔记";
  summary.setAttribute("aria-label", `第 ${number.dataset.number} 题的不会类型、笔记和解析`);
  const body = document.createElement("div");
  body.className = "cloze-tools-body";
  body.append(question.querySelector(".question-head"), question.querySelector(".question-tags"), question.querySelector(".question-note"), question.querySelector(".question-foot"));
  details.append(summary, body);
  question.replaceChildren(row, details);
  question.querySelector(".note-box").addEventListener("input", () => updateClozeSummary(question));
}

function updateClozeSummary(question) {
  const summary = question.querySelector(".cloze-tools > summary");
  if (!summary) return;
  const count = question.querySelectorAll(".question-tag.selected").length;
  const hasNote = Boolean(question.querySelector(".note-box")?.value.trim());
  summary.textContent = `分类${count ? `(${count})` : ""}·笔记${hasNote ? "✓" : ""}`;
}

function arrangeCloze(sectionEl) {
  const split = (container) => {
    const passage = container.querySelector(":scope > .section-passage");
    const questions = [...container.querySelectorAll(":scope > .question")];
    if (!passage || !questions.length) return;
    const layout = document.createElement("div");
    layout.className = "cloze-layout";
    const scroller = document.createElement("div");
    scroller.className = "cloze-scroll";
    scroller.tabIndex = 0;
    scroller.setAttribute("role", "region");
    scroller.setAttribute("aria-label", "文章与全部题目，可左右滚动查看更多选项");
    const hint = document.createElement("p");
    hint.className = "cloze-scroll-hint";
    hint.textContent = "左右拖动底部滚动条可查看更多；每题的分类、笔记和解析可单独展开。";
    const options = document.createElement("div");
    options.className = "cloze-questions";
    questions.forEach((question) => options.appendChild(question));
    layout.append(passage, options);
    scroller.appendChild(layout);
    container.append(scroller, hint);
  };
  split(sectionEl);
  sectionEl.querySelectorAll(".question-group").forEach(split);
}

// Store only text offsets, never HTML. Highlights belong to the paper in this browser.
let annotationPopup = null;
let pendingAnnotation = null;
let annotationRanges = {};
let annotationPointerDown = false;
const annotationSelector = ".question-stem, .section-passage, .option > span";

function hideAnnotationPopup() {
  if (annotationPopup) annotationPopup.hidden = true;
  pendingAnnotation = null;
}

function paintAnnotation(element, ranges) {
  const text = element.textContent;
  element.replaceChildren();
  let offset = 0;
  for (const range of ranges) {
    element.append(document.createTextNode(text.slice(offset, range.start)));
    const mark = document.createElement("mark");
    mark.className = "sentence-highlight";
    mark.tabIndex = 0;
    mark.setAttribute("role", "button");
    mark.title = "点击取消此处加粗标黄";
    mark.setAttribute("aria-label", "取消此处加粗标黄");
    mark.dataset.start = range.start;
    mark.dataset.end = range.end;
    mark.textContent = text.slice(range.start, range.end);
    element.append(mark);
    offset = range.end;
  }
  element.append(document.createTextNode(text.slice(offset)));
}

function saveTextAnnotations() {
  try {
    localStorage.setItem(`paper-highlights:v1:${currentPaper.id}`, JSON.stringify(annotationRanges));
  } catch { setStatus("标注已更新，但浏览器存储不可用，刷新后可能无法保留。"); }
}

function removeTextAnnotation(mark) {
  const element = mark.closest("[data-annotation]");
  const saved = annotationRanges[element?.dataset.annotation];
  if (!saved) return;
  saved.ranges = saved.ranges.filter((range) => range.start !== Number(mark.dataset.start) || range.end !== Number(mark.dataset.end));
  paintAnnotation(element, saved.ranges);
  saveTextAnnotations();
  hideAnnotationPopup();
}

function mergeAnnotationRanges(ranges, length) {
  const merged = [];
  ranges.filter((r) => Number.isInteger(r.start) && Number.isInteger(r.end) && r.start >= 0 && r.end <= length && r.end > r.start)
    .sort((a, b) => a.start - b.start).forEach((range) => {
      const last = merged[merged.length - 1];
      if (last && range.start <= last.end) last.end = Math.max(last.end, range.end);
      else merged.push({ start: range.start, end: range.end });
    });
  return merged;
}

function setupTextAnnotations() {
  hideAnnotationPopup();
  annotationRanges = {};
  try {
    const saved = JSON.parse(localStorage.getItem(`paper-highlights:v1:${currentPaper.id}`) || "{}");
    if (saved && typeof saved === "object" && !Array.isArray(saved)) annotationRanges = saved;
  } catch { /* An unavailable browser store does not prevent highlighting. */ }
  paperRoot.querySelectorAll(annotationSelector).forEach((element, index) => {
    const key = element.dataset.annotationKey || String(index);
    element.dataset.annotation = key;
    const saved = annotationRanges[key];
    if (saved?.text === element.textContent && Array.isArray(saved.ranges)) {
      paintAnnotation(element, mergeAnnotationRanges(saved.ranges, element.textContent.length));
    }
  });
  if (annotationPopup) return;
  annotationPopup = document.createElement("button");
  annotationPopup.type = "button";
  annotationPopup.className = "annotation-popup";
  annotationPopup.textContent = "是否需要加粗标黄";
  annotationPopup.hidden = true;
  document.body.appendChild(annotationPopup);
  annotationPopup.addEventListener("pointerdown", (event) => event.preventDefault());
  annotationPopup.addEventListener("click", () => {
    if (!pendingAnnotation) return;
    const { element, start, end } = pendingAnnotation;
    const text = element.textContent;
    const old = annotationRanges[element.dataset.annotation];
    const ranges = mergeAnnotationRanges([...(old?.text === text ? old.ranges : []), { start, end }], text.length);
    annotationRanges[element.dataset.annotation] = { text, ranges };
    paintAnnotation(element, ranges);
    saveTextAnnotations();
    window.getSelection()?.removeAllRanges();
    hideAnnotationPopup();
  });
  document.addEventListener("pointerdown", (event) => {
    if (annotationPopup.contains(event.target)) return;
    annotationPointerDown = event.button === 0 && paperRoot.contains(event.target);
    hideAnnotationPopup();
  });
  paperRoot.addEventListener("click", (event) => {
    const mark = event.target.closest(".sentence-highlight");
    if (!mark || !window.getSelection()?.isCollapsed) return;
    // Clicking an option's highlight must not select its radio/checkbox.
    event.preventDefault();
    removeTextAnnotation(mark);
  });
  paperRoot.addEventListener("keydown", (event) => {
    const mark = event.target.closest(".sentence-highlight");
    if (!mark || !["Enter", " "].includes(event.key)) return;
    event.preventDefault();
    removeTextAnnotation(mark);
  });
  document.addEventListener("pointerup", (event) => {
    if (!annotationPointerDown || event.button !== 0) return;
    annotationPointerDown = false;
    showSelectionAnnotation();
  });
  document.addEventListener("keyup", (event) => {
    if (event.key === "Escape") hideAnnotationPopup();
    else if (event.shiftKey) showSelectionAnnotation();
  });
  document.addEventListener("scroll", hideAnnotationPopup, true);
  window.addEventListener("resize", hideAnnotationPopup);
}

function showSelectionAnnotation() {
  const selection = window.getSelection();
  if (!selection?.rangeCount || selection.isCollapsed || !selection.toString().trim()) return;
  const range = selection.getRangeAt(0);
  const parent = range.startContainer.nodeType === Node.ELEMENT_NODE ? range.startContainer : range.startContainer.parentElement;
  const element = parent?.closest("[data-annotation]");
  if (!element || !paperRoot.contains(element) || !element.contains(range.endContainer)) return;
  const prefix = document.createRange();
  prefix.selectNodeContents(element);
  prefix.setEnd(range.startContainer, range.startOffset);
  const start = prefix.toString().length;
  const end = start + range.toString().length;
  pendingAnnotation = { element, start, end };
  const rect = range.getBoundingClientRect();
  annotationPopup.hidden = false;
  const width = annotationPopup.offsetWidth;
  const height = annotationPopup.offsetHeight;
  annotationPopup.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - width - 8))}px`;
  annotationPopup.style.top = `${rect.top >= height + 12 ? rect.top - height - 8 : Math.min(rect.bottom + 8, window.innerHeight - height - 8)}px`;
}
