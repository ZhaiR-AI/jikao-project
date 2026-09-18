const uploadForm = document.querySelector("#upload-form");
const fileInput = document.querySelector("#pdf-file");
const fileName = document.querySelector("#file-name");
const maxPages = document.querySelector("#max-pages");
const generateBtn = document.querySelector("#generate-btn");
const statusBox = document.querySelector("#status");
const paperRoot = document.querySelector("#paper");
const paperTitle = document.querySelector("#paper-title");
const paperDesc = document.querySelector("#paper-desc");
const paperMeta = document.querySelector("#paper-meta");
const questionCount = document.querySelector("#question-count");
const totalScore = document.querySelector("#total-score");
const duration = document.querySelector("#duration");
const answeredCount = document.querySelector("#answered-count");
const questionCard = document.querySelector("#question-card");
const exportJson = document.querySelector("#export-json");
const exportAnswers = document.querySelector("#export-answers");
const saveAnswers = document.querySelector("#save-answers");
const wrongBookPanel = document.querySelector("#wrong-book-panel");
const closeWrongBook = document.querySelector("#close-wrong-book");
const wrongBookList = document.querySelector("#wrong-book-list");
const clearAnswers = document.querySelector("#clear-answers");
const submitPaper = document.querySelector("#submit-paper");
const gradePanel = document.querySelector("#grade-panel");
const gradeScore = document.querySelector("#grade-score");
const gradeSummary = document.querySelector("#grade-summary");
const reviewWrong = document.querySelector("#review-wrong");
const actions = document.querySelector(".actions");
const navPanel = document.querySelector(".nav-panel");
const recordPanel = document.querySelector("#record-panel");
const currentRecord = document.querySelector("#current-record");
const toggleRecordHistory = document.querySelector("#toggle-record-history");
const newRecord = document.querySelector("#new-record");
const recordHistory = document.querySelector("#record-history");

let currentPaper = null;
let currentPaperId = null;
let currentGrade = null;
let currentRecordId = null;
let submissionRecords = [];
let sessionStartedAt = Date.now();
let autoSaveTimer = null;
let draftRevision = 0;
let savedDraftRevision = 0;
let draftSaveInProgress = false;
let draftSavePromise = null;

const AUTO_SAVE_INTERVAL_MS = 10_000;
const LOCAL_DRAFT_PREFIX = "paper-exam-draft:v1:";

const questionCategories = [
  ["grammar", "语法"],
  ["vocabulary", "单词"],
  ["phrase", "词组"],
  ["translation", "翻译"],
];

fileInput.addEventListener("change", () => {
  fileName.textContent = fileInput.files[0]?.name || "尚未选择文件";
});

uploadForm.addEventListener("submit", startPaperGeneration);

exportJson.addEventListener("click", () => {
  if (!currentPaper) return;
  downloadJson(`${currentPaper.id}.json`, currentPaper);
});

exportAnswers.addEventListener("click", () => {
  if (!currentPaper) return;
  downloadJson(`${currentPaper.id}-answers.json`, collectSubmission());
});

saveAnswers.addEventListener("click", () => {
  saveDraft(true);
});

toggleRecordHistory.addEventListener("click", () => {
  const willOpen = recordHistory.classList.contains("hidden");
  recordHistory.classList.toggle("hidden", !willOpen);
  toggleRecordHistory.setAttribute("aria-expanded", String(willOpen));
});

newRecord.addEventListener("click", createNewSubmissionRecord);


closeWrongBook.addEventListener("click", () => {
  wrongBookPanel.classList.add("hidden");
});

clearAnswers.addEventListener("click", () => {
  document.querySelectorAll("[data-answer]").forEach((el) => {
    if (el.type === "checkbox" || el.type === "radio") {
      el.checked = false;
    } else {
      el.value = "";
    }
  });
  document.querySelectorAll(".question-tag.selected").forEach((tag) => {
    tag.classList.remove("selected");
  });
  currentGrade = null;
  hideGrade();
  clearGradeDetails();
  updateProgress();
  markDraftDirty();
  setStatus("已清空作答，题目笔记已保留。");
});

submitPaper.addEventListener("click", async () => {
  if (!currentPaper) return;
  if (paperQualityState?.status === "incomplete") {
    setStatus("这份试卷仍有结构问题，请先查看检查结果并重新整理，当前作答可以保存。");
    document.querySelector("#paper-quality").scrollIntoView({ block: "start" });
    return;
  }
  const marks = new Set(collectMarks());
  const doubtfulQuestions = flattenQuestions(currentPaper).filter((question) => marks.has(question.id));
  if (doubtfulQuestions.length) {
    const numbers = doubtfulQuestions.map((question) => question.number).join("、");
    const confirmed = window.confirm(
      `还有 ${doubtfulQuestions.length} 道题标记为“存疑”：\n第 ${numbers} 题。\n\n是否仍然提交答案并开始 AI 判卷？\n点击“确定”继续提交；点击“取消”返回检查，答案和存疑标记都会保留。`,
    );
    if (!confirmed) {
      setStatus(`已取消提交。第 ${numbers} 题仍有存疑，可点击答题卡题号检查；确认后再次提交。`);
      return;
    }
  }
  submitPaper.disabled = true;
  setExamEditingDisabled(true);
  const paperId = currentPaper.id;
  const submission = collectDraftPayload();
  saveLocalDraftBackup(submission);
  setStatus("正在保存作答，保存成功后将开始 AI 判卷。");

  try {
    const savedRecord = await saveDraft(false, submission);
    if (!savedRecord) {
      setStatus("提交已停止：服务器未能保存作答。本页和浏览器本地备份仍保留答案，请勿清空或关闭浏览器数据。");
      return;
    }

    submission.record_id = savedRecord.record_id || submission.record_id;
    currentRecordId = submission.record_id;
    const knownAttemptIds = new Set(
      (savedRecord.attempts || []).map((attempt) => attempt?.id).filter(Boolean),
    );
    setStatus("作答已保存，正在 AI 判卷，请稍等。");

    let shouldRecoverResult = true;
    try {
      const response = await fetch(`/api/paper/${encodeURIComponent(paperId)}/grade`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(submission),
      });
      const payload = await response.json();
      if (!response.ok) {
        shouldRecoverResult = false;
        throw new Error(payload.detail || `判卷请求失败（HTTP ${response.status}）`);
      }
      shouldRecoverResult = false;
      showCompletedGrade(payload);
      setStatus(`判卷完成：${formatNumber(payload.total_score)}/100；作答已保存。`);
      refreshGradeRelatedData();
    } catch (error) {
      const recovered = shouldRecoverResult
        ? await recoverCompletedGrade(submission.record_id, knownAttemptIds)
        : null;
      if (recovered) {
        showCompletedGrade(recovered);
        setStatus(`判卷完成：${formatNumber(recovered.total_score)}/100；连接曾中断，已恢复服务端结果，作答已保存。`);
        refreshGradeRelatedData();
      } else {
        const reason = error?.message || "网络连接中断";
        setStatus(`AI 判卷未返回：${reason}。作答已经保存，可稍后重试判卷或从历史记录查看结果。`);
      }
    }
  } finally {
    setExamEditingDisabled(false);
    submitPaper.disabled = false;
  }
});

window.addEventListener("pagehide", () => {
  if (currentPaper) saveLocalDraftBackup(collectDraftPayload());
});

reviewWrong.addEventListener("click", () => {
  const target = document.querySelector(".exam-page:not([hidden]) .question.wrong, .exam-page:not([hidden]) .question.partial");
  if (target) {
    target.scrollIntoView({ behavior: "smooth", block: "start" });
  } else {
    questionCard.querySelector(".card-btn.wrong, .card-btn.partial")?.focus();
    setStatus("请点击答题卡中需要复盘的题号，切换到对应大题。");
  }
});

function setStatus(message) {
  statusBox.textContent = message;
}

function setViewMode(mode) {
  document.body.dataset.view = mode;
  actions.classList.toggle("overview", mode !== "paper");
  navPanel.classList.toggle("hidden", mode !== "paper");
}

function showWrongBookPanel() {
  wrongBookPanel.classList.remove("hidden");
  loadWrongBook();
  wrongBookPanel.scrollIntoView({ behavior: "smooth", block: "start" });
}

function normalizePaper(paper) {
  if (!paper || paper.type === "paper_collection") return paper;
  paper.total_score = 100;
  for (const section of paper.sections || []) {
    const questions = getSectionQuestions(section);
    const sectionScore = Number(section.score || 0);
    const sectionTotal = Number(section.total_score || 0);
    if (!sectionScore && sectionTotal && questions.length) {
      section.score = sectionTotal / questions.length;
    }
    if (!sectionTotal && section.score && questions.length) {
      section.total_score = Number(section.score) * questions.length;
    }
  }
  return paper;
}

function renderPaper(paper) {
  if (paper?.type === "paper_collection") {
    renderCollection(paper);
    return;
  }
  stopAutoSave();
  setViewMode("paper");
  draftRevision = 0;
  savedDraftRevision = 0;
  currentPaper = normalizePaper(paper);
  currentGrade = null;
  currentRecordId = null;
  submissionRecords = [];
  sessionStartedAt = Date.now();
  hideGrade();
  recordPanel.classList.remove("hidden");
  recordHistory.classList.add("hidden");
  toggleRecordHistory.setAttribute("aria-expanded", "false");
  currentRecord.textContent = "未保存的新记录";
  recordHistory.innerHTML = "";
  wrongBookPanel.classList.add("hidden");

  const questions = flattenQuestions(currentPaper);
  paperTitle.textContent = currentPaper.title || "未命名试卷";
  paperDesc.textContent = currentPaper.description || "";
  paperMeta.textContent = `${currentPaper.source?.file_name || "试卷文件"} · 第 ${currentPaper.source?.start_page || "-"}-${currentPaper.source?.end_page || "-"} ${currentPaper.source?.unit || "页"}`;
  questionCount.textContent = questions.length;
  totalScore.textContent = "100";
  duration.textContent = currentPaper.duration_minutes || 120;

  paperRoot.classList.remove("empty");
  paperRoot.innerHTML = "";

  const pages = buildExamPages(currentPaper);
  for (const [pageIndex, page] of pages.entries()) {
    const pageEl = document.createElement("section");
    pageEl.className = "exam-page";
    const pageHead = document.createElement("div");
    pageHead.className = "exam-page-heading";
    pageHead.textContent = `${page.title} · 第 ${pageIndex + 1} / ${pages.length} 页`;
    pageEl.appendChild(pageHead);
    for (const section of page.sections) {
      const sectionEl = document.createElement("section");
      sectionEl.className = "section";
      sectionEl.innerHTML = `<h3 class="section-title"></h3>`;
      sectionEl.querySelector("h3").textContent = section.title || "题目";
      if (section.description) {
        const passage = document.createElement("div");
        passage.className = "section-passage";
        passage.textContent = section.description;
        sectionEl.appendChild(passage);
      }

      if (section.groups?.length) {
        for (const group of section.groups) {
          sectionEl.appendChild(renderQuestionGroup(group, section));
        }
      } else {
        for (const question of section.questions || []) {
          sectionEl.appendChild(renderQuestion(question, section));
        }
      }
      if (["cloze", "wordbank"].includes(sectionKind(section))) arrangeCloze(sectionEl);
      pageEl.appendChild(sectionEl);
    }
    paperRoot.appendChild(pageEl);
  }

  renderQuestionCard();
  setupTextAnnotations();
  paperRoot.querySelectorAll(".cloze-questions > .question").forEach(compactClozeQuestion);
  activateExamPage(paperRoot.querySelector(".exam-page"));
  enableExamActions(true);
  updateProgress();
  startAutoSave();
  showPaperQuality(currentPaper).then(checkRenderedExamNavigation);
}

function renderCollection(collection) {
  showPaperQuality(null);
  stopAutoSave();
  setViewMode("collection");
  currentPaper = null;
  currentGrade = null;
  currentRecordId = null;
  submissionRecords = [];
  hideGrade();
  recordPanel.classList.add("hidden");
  paperTitle.textContent = collection.title || "试卷集合";
  paperDesc.textContent = `已从文件中识别出 ${collection.papers?.length || 0} 套试卷`;
  paperMeta.textContent = `${collection.source?.file_name || "试卷文件"} · ${collection.source?.page_count || 0} ${collection.source?.unit || "页"}`;
  questionCount.textContent = collection.papers?.reduce((sum, paper) => sum + Number(paper.question_count || 0), 0) || 0;
  totalScore.textContent = String((collection.papers || []).length * 100 || 100);
  duration.textContent = "-";
  answeredCount.textContent = "0/0";
  questionCard.innerHTML = "";

  paperRoot.classList.remove("empty");
  paperRoot.innerHTML = "";

  const list = document.createElement("section");
  list.className = "collection-list";
  for (const paper of collection.papers || []) {
    const item = document.createElement("article");
    item.className = "collection-item";
    item.innerHTML = `
      <div>
        <h3></h3>
        <p></p>
      </div>
      <a></a>
    `;
    item.querySelector("h3").textContent = paper.title || paper.id;
    item.querySelector("h3").appendChild(libraryRenameButton(paper, async () => {
      const response = await fetch(`/api/paper/${encodeURIComponent(collection.id)}`);
      if (!response.ok) throw new Error("名称已保存，重新打开集合即可查看。");
      renderCollection(await response.json());
    }));
    item.querySelector("h3").appendChild(libraryDeleteButton(paper));
    item.querySelector("p").textContent = `${paper.question_count || 0} 题 · 100 分 · 第 ${paper.start_page || "-"}-${paper.end_page || "-"} ${collection.source?.unit || "页"} · ${paper.quality?.label || "尚未检查"}${paper.repaired_from ? " · 修正版（保留原作答）" : ""}`;
    const link = item.querySelector("a");
    link.href = paper.paper_url;
    link.textContent = paper.quality && paper.quality.status !== "ready" ? "预览并检查" : "进入考试";
    list.appendChild(item);
  }
  paperRoot.appendChild(list);

  exportJson.disabled = false;
  exportAnswers.disabled = true;
  saveAnswers.disabled = true;
  clearAnswers.disabled = true;
  submitPaper.disabled = true;
  exportJson.onclick = () => downloadJson(`${collection.id}.json`, collection);
}

function renderQuestionGroup(group, section = {}) {
  const groupEl = document.createElement("div");
  groupEl.className = "question-group";

  const title = document.createElement("h4");
  title.className = "group-title";
  title.textContent = group.title || "题组";
  groupEl.appendChild(title);

  if (group.description) {
    const passage = document.createElement("div");
    passage.className = "section-passage group-passage";
    passage.textContent = group.description;
    groupEl.appendChild(passage);
  }

  for (const question of group.questions || []) {
    groupEl.appendChild(renderQuestion(question, section));
  }
  return groupEl;
}

function renderQuestion(question, section = {}) {
  const el = document.createElement("article");
  el.className = "question";
  el.id = `question-${question.id}`;
  const sourcePages = (question.source_pages || []).join(", ") || "-";
  const questionScore = Number(section.score || 0);
  el.innerHTML = `
    <div class="question-head">
      <div>
        <span class="question-number">第 ${escapeHtml(question.number)} 题</span>
        <div class="question-title"></div>
      </div>
      <span class="badge"></span>
    </div>
    <div class="question-response">
      <div class="answer-area"></div>
      <label class="question-note">
        <span>笔记</span>
        <textarea class="note-box" rows="2" data-note="${escapeAttr(question.id)}" placeholder="记录这道题的要点"></textarea>
      </label>
    </div>
    <div class="question-tags">
      <span class="question-tags-label">不会类型</span>
      <div class="question-tag-list"></div>
    </div>
    <div class="question-foot">
      <span></span>
    </div>
  `;
  const stem = document.createElement("span");
  stem.className = "question-stem";
  stem.textContent = question.stem || "请作答";
  const doubt = document.createElement("button");
  doubt.type = "button";
  doubt.className = "doubt-button";
  doubt.dataset.mark = question.id;
  doubt.setAttribute("aria-pressed", "false");
  doubt.textContent = "[存疑]";
  el.querySelector(".question-title").append(stem, doubt);
  el.querySelector(".badge").textContent = `${typeLabel(question.type)} · ${formatNumber(questionScore)} 分`;
  el.querySelector(".question-foot span").textContent = `来源${currentPaper.source?.unit || "页"}：${sourcePages}`;
  el.querySelector(".answer-area").appendChild(renderAnswerControl(question));
  el.querySelector(".note-box").addEventListener("input", markDraftDirty);
  doubt.addEventListener("click", () => {
    doubt.setAttribute("aria-pressed", String(doubt.getAttribute("aria-pressed") !== "true"));
    updateProgress();
    markDraftDirty();
  });
  const tagList = el.querySelector(".question-tag-list");
  for (const [category, label] of questionCategories) {
    const tag = document.createElement("button");
    tag.type = "button";
    tag.className = "question-tag";
    tag.dataset.category = category;
    tag.dataset.question = question.id;
    tag.textContent = label;
    tag.addEventListener("click", () => {
      tag.classList.toggle("selected");
      updateClozeSummary(el);
      markDraftDirty();
    });
    tagList.appendChild(tag);
  }
  return el;
}

function renderAnswerControl(question) {
  const choiceTypes = new Set(["single_choice", "multiple_choice", "true_false"]);
  if (choiceTypes.has(question.type) && question.options?.length) {
    const wrap = document.createElement("div");
    wrap.className = "options";
    for (const option of question.options) {
      const label = document.createElement("label");
      label.className = "option";
      const input = document.createElement("input");
      input.type = question.type === "multiple_choice" ? "checkbox" : "radio";
      input.name = question.id;
      input.value = option.id;
      input.dataset.answer = question.id;
      input.addEventListener("change", () => {
        updateProgress();
        markDraftDirty();
      });
      const text = document.createElement("span");
      text.textContent = `${option.id}. ${option.text}`;
      label.append(input, text);
      wrap.appendChild(label);
    }
    return wrap;
  }

  const textarea = document.createElement("textarea");
  textarea.className = "answer-box";
  textarea.dataset.answer = question.id;
  textarea.placeholder = "在此作答";
  textarea.addEventListener("input", () => {
    updateProgress();
    markDraftDirty();
  });
  return textarea;
}

function renderQuestionCard() {
  questionCard.innerHTML = "";
  const order = examKindOrder(currentPaper, true);
  const standard = usesStandardExamLayout(currentPaper);
  const sections = [...(currentPaper.sections || [])];
  if (standard) sections.sort((a, b) => order.indexOf(sectionKind(a)) - order.indexOf(sectionKind(b)));
  const blocks = new Map();
  for (const section of sections) {
    const kind = sectionKind(section);
    const key = !standard || kind === "other" ? section : kind;
    let grid = blocks.get(key);
    if (!grid) {
      const block = document.createElement("div");
      block.className = "answer-card-group";
      const heading = document.createElement("h4");
      heading.textContent = standard ? sectionLabel(section) : section.title || sectionLabel(section);
      grid = document.createElement("div");
      grid.className = "answer-card-grid";
      block.append(heading, grid);
      questionCard.appendChild(block);
      blocks.set(key, grid);
    }
    for (const question of getSectionQuestions(section)) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "card-btn";
      btn.dataset.goto = question.id;
      btn.textContent = question.number;
      btn.addEventListener("click", () => {
        navigateToQuestion(question.id);
      });
      grid.appendChild(btn);
    }
  }
}

function updateProgress() {
  if (!currentPaper) return;
  const questions = flattenQuestions(currentPaper);
  const answers = collectAnswers();
  const marks = new Set(collectMarks());
  const answered = questions.filter((question) => hasAnswer(answers[question.id])).length;
  answeredCount.textContent = `${answered}/${questions.length}`;
  questionCard.querySelectorAll(".card-btn").forEach((btn) => {
    const questionId = btn.dataset.goto;
    btn.classList.toggle("answered", hasAnswer(answers[questionId]));
    btn.classList.toggle("marked", marks.has(questionId));
    btn.title = `第 ${btn.textContent} 题，${hasAnswer(answers[questionId]) ? "已作答" : "未作答"}${marks.has(questionId) ? "，存疑" : ""}`;
    btn.setAttribute("aria-label", btn.title);
  });
  paperRoot.querySelectorAll(".cloze-question").forEach((question) => {
    const label = question.querySelector(".cloze-number");
    const value = answers[question.querySelector("[data-mark]").dataset.mark];
    label.textContent = `${label.dataset.number}（${Array.isArray(value) ? value.join("、") : value || ""}）`;
    updateClozeSummary(question);
  });
}

function renderGrade(grade) {
  gradePanel.classList.remove("hidden");
  gradeScore.textContent = formatNumber(grade.total_score || 0);
  gradeSummary.textContent = grade.summary || "";

  const byId = {};
  for (const result of grade.results || []) {
    byId[result.question_id] = result;
  }

  clearGradeDetails();
  paperRoot.classList.add("review-mode");

  for (const question of flattenQuestions(currentPaper)) {
    const result = byId[question.id];
    if (!result) continue;
    const el = document.querySelector(`#question-${cssEscape(question.id)}`);
    if (!el) continue;
    const gotScore = Number(result.score_awarded || 0);
    const state = result.grading_status === "unanswered"
      ? "unanswered"
      : result.is_correct == null
        ? "pending"
      : result.is_correct === true
        ? "correct"
        : gotScore > 0
          ? "partial"
          : "wrong";
    el.classList.add(state);
    const detail = document.createElement("div");
    detail.className = "question-result";
    detail.setAttribute("aria-label", `第 ${question.number} 题解析`);
    detail.innerHTML = `
      <p class="result-answer"></p>
      <p class="result-reason"></p>
      <p class="result-suggestion"></p>
    `;
    if (state === "unanswered" || state === "pending") {
      detail.querySelector(".result-answer").textContent = result.reason || "本题未作答，未调用 AI 判卷。";
      detail.querySelector(".result-reason").remove();
      detail.querySelector(".result-suggestion").remove();
    } else {
      detail.querySelector(".result-answer").textContent = `参考答案：${formatAnswer(result.correct_answer) || "未提供"}；你的答案：${formatAnswer(result.student_answer) || "未作答"}`;
      detail.querySelector(".result-reason").textContent = `解析：${result.reason || "暂无解析。"}`;
      detail.querySelector(".result-suggestion").textContent = `建议：${result.suggestion || "复盘题干和答案。"}`;
    }
    const questionBody = document.createElement("div");
    questionBody.className = "question-review-body";
    questionBody.append(...el.childNodes);
    // Move the existing controls so their values and save handlers stay intact.
    // Placeholders let us restore the exact examination layout when changing records.
    detail.reviewControls = [];
    for (const selector of [".question-note", ".question-tags", ".question-foot"]) {
      const control = questionBody.querySelector(selector);
      if (!control) continue;
      const placeholder = document.createComment("review-control-home");
      control.replaceWith(placeholder);
      detail.reviewControls.push({ control, placeholder });
      detail.appendChild(control);
    }
    el.append(questionBody, detail);
    el.classList.add("has-review");
    updateClozeSummary(el);
  }

  questionCard.querySelectorAll(".card-btn").forEach((btn) => {
    const result = byId[btn.dataset.goto];
    btn.classList.remove("correct", "wrong", "partial", "unanswered");
    if (!result) return;
    if (result.grading_status === "unanswered" || result.is_correct == null) {
      btn.classList.add("unanswered");
      btn.title = result.grading_status === "unanswered" ? `第 ${btn.textContent} 题，未作答，未判卷` : `第 ${btn.textContent} 题，待复核`;
      return;
    }
    const gotScore = Number(result.score_awarded || 0);
    const maxScore = Number(result.max_score || 0);
    if (result.is_correct === true || (maxScore > 0 && gotScore >= maxScore)) {
      btn.classList.add("correct");
    } else if (gotScore > 0) {
      btn.classList.add("partial");
    } else {
      btn.classList.add("wrong");
    }
  });
}

function clearGradeDetails() {
  paperRoot.classList.remove("review-mode");
  document.querySelectorAll(".question-result").forEach((el) => {
    for (const { control, placeholder } of el.reviewControls || []) {
      placeholder.replaceWith(control);
    }
    el.remove();
  });
  paperRoot.querySelectorAll(".question-review-body").forEach((body) => body.replaceWith(...body.childNodes));
  document.querySelectorAll(".question").forEach((el) => {
    el.classList.remove("correct", "wrong", "partial", "unanswered", "pending", "has-review");
  });
  questionCard.querySelectorAll(".card-btn").forEach((btn) => {
    btn.classList.remove("correct", "wrong", "partial", "unanswered");
  });
}

function hideGrade() {
  gradePanel.classList.add("hidden");
  gradeScore.textContent = "0";
  gradeSummary.textContent = "";
}

function enableExamActions(enabled) {
  exportJson.disabled = !enabled;
  exportAnswers.disabled = !enabled;
  saveAnswers.disabled = !enabled;
  clearAnswers.disabled = !enabled;
  submitPaper.disabled = !enabled;
}

function setExamEditingDisabled(disabled) {
  document.querySelectorAll("[data-answer], [data-note], [data-mark], .question-tag").forEach((control) => {
    control.disabled = disabled;
  });
  recordHistory.querySelectorAll("button").forEach((button) => {
    button.disabled = disabled;
  });
  saveAnswers.disabled = disabled;
  clearAnswers.disabled = disabled;
  newRecord.disabled = disabled;
}

function flattenQuestions(paper) {
  return (paper.sections || []).flatMap((section) =>
    getSectionQuestions(section).map((question) => ({ ...question, section_score: Number(section.score || 0) }))
  );
}

function getSectionQuestions(section = {}) {
  if (section.groups?.length) {
    return section.groups.flatMap((group) => group.questions || []);
  }
  return section.questions || [];
}

function collectSubmission() {
  return {
    paper_id: currentPaper.id,
    title: currentPaper.title,
    ...collectDraftPayload(),
    exported_at: new Date().toISOString(),
  };
}

function collectDraftPayload() {
  return {
    record_id: currentRecordId,
    answers: collectAnswers(),
    categories: collectCategories(),
    notes: collectNotes(),
    marks: collectMarks(),
    duration_seconds: Math.floor((Date.now() - sessionStartedAt) / 1000),
  };
}

function collectAnswers() {
  const answers = {};
  for (const question of flattenQuestions(currentPaper)) {
    const controls = [...document.querySelectorAll(`[data-answer="${cssEscape(question.id)}"]`)];
    if (!controls.length) continue;
    if (controls[0].type === "radio") {
      answers[question.id] = controls.find((el) => el.checked)?.value || "";
    } else if (controls[0].type === "checkbox") {
      answers[question.id] = controls.filter((el) => el.checked).map((el) => el.value);
    } else {
      answers[question.id] = controls[0].value.trim();
    }
  }
  return answers;
}

function collectCategories() {
  const categories = {};
  for (const question of flattenQuestions(currentPaper || {})) {
    const selected = [...document.querySelectorAll(`.question-tag[data-question="${cssEscape(question.id)}"].selected`)]
      .map((tag) => tag.dataset.category)
      .filter(Boolean);
    if (selected.length) categories[question.id] = selected;
  }
  return categories;
}

function collectNotes() {
  const notes = {};
  for (const question of flattenQuestions(currentPaper || {})) {
    const value = document.querySelector(`[data-note="${cssEscape(question.id)}"]`)?.value.trim() || "";
    if (value) notes[question.id] = value;
  }
  return notes;
}

function collectMarks() {
  return [...document.querySelectorAll('[data-mark][aria-pressed="true"]')]
    .map((control) => control.dataset.mark)
    .filter(Boolean);
}

function markDraftDirty() {
  if (!currentPaper) return;
  draftRevision += 1;
  saveLocalDraftBackup(collectDraftPayload());
}

function startAutoSave() {
  stopAutoSave();
  autoSaveTimer = window.setInterval(() => {
    if (draftRevision > savedDraftRevision) saveDraft(false);
  }, AUTO_SAVE_INTERVAL_MS);
}

function stopAutoSave() {
  if (autoSaveTimer !== null) window.clearInterval(autoSaveTimer);
  autoSaveTimer = null;
}

async function saveDraft(showStatus = false, submission = null) {
  if (!currentPaper) return false;
  const requestedPaperId = currentPaper.id;
  if (draftSavePromise) {
    if (showStatus) setStatus("正在保存作答和笔记，请稍等。");
    const activeResult = await draftSavePromise;
    if (!submission) return activeResult;
  }
  if (currentPaper?.id !== requestedPaperId) return false;
  const paperId = requestedPaperId;
  const savingSubmission = submission || collectDraftPayload();
  const savingRecordId = savingSubmission.record_id ?? currentRecordId;
  const savingRevision = draftRevision;
  draftSaveInProgress = true;
  const operation = (async () => {
    try {
      const response = await fetch(`/api/paper/${encodeURIComponent(paperId)}/submission`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...savingSubmission, record_id: savingRecordId }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || `保存失败（HTTP ${response.status}）`);
      if (currentPaper?.id === paperId && currentRecordId === savingRecordId) {
        currentRecordId = payload.record_id || currentRecordId;
        savedDraftRevision = Math.max(savedDraftRevision, savingRevision);
      }
      if (currentPaper?.id === paperId) {
        saveLocalDraftBackup(
          { ...savingSubmission, record_id: payload.record_id || savingRecordId },
          payload.draft?.updated_at,
        );
      }
      try {
        await loadSubmissionHistory();
      } catch {
        // The draft itself is already durable; history refresh is secondary.
      }
      const prefix = showStatus ? "作答和笔记已保存" : "已自动保存";
      setStatus(`${prefix}：${payload.file_name || currentPaper.title}`);
      return payload;
    } catch (error) {
      setStatus(`保存失败：${error.message}`);
      return false;
    }
  })();
  draftSavePromise = operation;
  try {
    return await operation;
  } finally {
    if (draftSavePromise === operation) draftSavePromise = null;
    draftSaveInProgress = false;
  }
}

function localDraftStorageKey(paperId) {
  return `${LOCAL_DRAFT_PREFIX}${paperId}`;
}

function saveLocalDraftBackup(submission, savedAt = null) {
  if (!currentPaper || !submission) return;
  try {
    localStorage.setItem(
      localDraftStorageKey(currentPaper.id),
      JSON.stringify({
        paper_id: currentPaper.id,
        record_id: submission.record_id || null,
        saved_at: savedAt || new Date().toISOString(),
        draft: {
          answers: submission.answers || {},
          categories: submission.categories || {},
          notes: submission.notes || {},
          marks: submission.marks || [],
          duration_seconds: Math.max(0, Number(submission.duration_seconds || 0)),
        },
      }),
    );
  } catch {
    // Server autosave remains available when browser storage is unavailable.
  }
}

function loadLocalDraftBackup() {
  if (!currentPaper) return null;
  try {
    const backup = JSON.parse(localStorage.getItem(localDraftStorageKey(currentPaper.id)) || "null");
    if (!backup || backup.paper_id !== currentPaper.id || !backup.draft) return null;
    return backup;
  } catch {
    return null;
  }
}

function removeLocalDraftBackup(recordId) {
  if (!currentPaper) return;
  try {
    const backup = loadLocalDraftBackup();
    if (!backup || !recordId || backup.record_id === recordId) {
      localStorage.removeItem(localDraftStorageKey(currentPaper.id));
    }
  } catch {
    // Ignore browser storage failures after the server record was deleted.
  }
}

function hasDraftContent(draft = {}) {
  const hasValues = (value) => Object.values(value || {}).some((item) => (
    Array.isArray(item) ? item.length > 0 : String(item ?? "").trim().length > 0
  ));
  return hasValues(draft.answers)
    || hasValues(draft.categories)
    || hasValues(draft.notes)
    || (draft.marks || []).length > 0;
}

function isLocalDraftNewer(backup, serverDraft = {}) {
  const localTime = Date.parse(backup?.saved_at || "");
  const serverTime = Date.parse(serverDraft.updated_at || "");
  return Number.isFinite(localTime) && (!Number.isFinite(serverTime) || localTime > serverTime);
}

function restoreLocalDraftBackup(backup, recordId = null) {
  if (!backup?.draft || !hasDraftContent(backup.draft)) return false;
  currentRecordId = recordId;
  restoreSavedDraft(backup.draft);
  draftRevision = 1;
  savedDraftRevision = 0;
  renderSubmissionHistory();
  return true;
}

function showCompletedGrade(grade) {
  currentGrade = grade;
  currentRecordId = grade.record_id || currentRecordId;
  savedDraftRevision = draftRevision;
  renderGrade(grade);
}

async function refreshGradeRelatedData() {
  await Promise.allSettled([loadSubmissionHistory(), loadWrongBook()]);
}

async function recoverCompletedGrade(recordId, knownAttemptIds) {
  if (!currentPaper || !recordId) return null;
  const query = new URLSearchParams({ record_id: recordId });
  for (let attemptNumber = 0; attemptNumber < 5; attemptNumber += 1) {
    try {
      const response = await fetch(`/api/paper/${encodeURIComponent(currentPaper.id)}/submission?${query}`);
      if (response.ok) {
        const savedRecord = await response.json();
        const completedAttempt = [...(savedRecord.attempts || [])]
          .reverse()
          .find((attempt) => attempt?.grade && !knownAttemptIds.has(attempt.id));
        if (completedAttempt) {
          return {
            ...completedAttempt.grade,
            record_id: savedRecord.record_id || recordId,
            attempt_id: completedAttempt.id,
          };
        }
      }
    } catch {
      // The server may be restarting; retry briefly without resubmitting the paper.
    }
    if (attemptNumber < 4) {
      await new Promise((resolve) => window.setTimeout(resolve, 1500));
    }
  }
  return null;
}

function restoreSavedDraft(draft = {}) {
  const answers = draft.answers || {};
  const categories = draft.categories || {};
  const notes = draft.notes || {};
  const marks = new Set(draft.marks || []);
  for (const question of flattenQuestions(currentPaper || {})) {
    const controls = [...document.querySelectorAll(`[data-answer="${cssEscape(question.id)}"]`)];
    const value = answers[question.id];
    if (controls.length && (controls[0].type === "radio" || controls[0].type === "checkbox")) {
      const values = Array.isArray(value) ? value : [value];
      controls.forEach((control) => {
        control.checked = values.includes(control.value);
      });
    } else if (controls[0]) {
      controls[0].value = value || "";
    }
    const selected = new Set(categories[question.id] || []);
    document.querySelectorAll(`.question-tag[data-question="${cssEscape(question.id)}"]`).forEach((tag) => {
      tag.classList.toggle("selected", selected.has(tag.dataset.category));
    });
    const note = document.querySelector(`[data-note="${cssEscape(question.id)}"]`);
    if (note) note.value = notes[question.id] || "";
    const mark = document.querySelector(`[data-mark="${cssEscape(question.id)}"]`);
    if (mark) mark.setAttribute("aria-pressed", String(marks.has(question.id)));
  }
  const savedSeconds = Number(draft.duration_seconds || 0);
  sessionStartedAt = Date.now() - Math.max(0, savedSeconds) * 1000;
  updateProgress();
}

async function loadSavedDraft() {
  if (!currentPaper) return;
  const localBackup = loadLocalDraftBackup();
  try {
    await loadSubmissionHistory();
    if (!submissionRecords.length) {
      currentRecordId = null;
      currentRecord.textContent = "未保存的新记录";
      renderSubmissionHistory();
      if (restoreLocalDraftBackup(localBackup)) {
        setStatus("已恢复浏览器本地备份；服务器暂时没有这份作答记录，将继续自动保存。");
      }
      return;
    }
    const latestRecord = submissionRecords[0];
    const backupRecord = localBackup?.record_id
      ? submissionRecords.find((record) => record.record_id === localBackup.record_id)
      : null;
    const recordToLoad = backupRecord
      && Date.parse(localBackup.saved_at || "") > Date.parse(latestRecord.updated_at || "")
      ? backupRecord
      : latestRecord;
    const loaded = await loadSubmissionRecord(recordToLoad.record_id);
    if (!loaded && restoreLocalDraftBackup(localBackup, localBackup?.record_id || null)) {
      setStatus("服务器记录暂时无法读取，已从浏览器本地备份恢复作答。");
    }
  } catch {
    const backupRecordId = localBackup?.record_id || null;
    if (restoreLocalDraftBackup(localBackup, backupRecordId)) {
      setStatus("服务器暂时不可用，已从浏览器本地备份恢复作答；页面恢复连接后会继续自动保存。");
    }
  }
}

async function loadSubmissionHistory() {
  if (!currentPaper) return;
  const response = await fetch(`/api/paper/${encodeURIComponent(currentPaper.id)}/submissions`);
  if (!response.ok) throw new Error("历史记录加载失败");
  const payload = await response.json();
  submissionRecords = payload.records || [];
  renderSubmissionHistory();
}

function renderSubmissionHistory() {
  recordHistory.innerHTML = "";
  updateCurrentRecordLabel();
  if (!submissionRecords.length) {
    const empty = document.createElement("p");
    empty.className = "record-history-empty";
    empty.textContent = "暂无历史记录。";
    recordHistory.appendChild(empty);
    return;
  }
  for (const record of submissionRecords) {
    const row = document.createElement("div");
    row.className = "record-history-row";
    const item = document.createElement("button");
    item.type = "button";
    item.className = "record-history-item";
    item.dataset.recordId = record.record_id;
    item.classList.toggle("active", record.record_id === currentRecordId);
    item.innerHTML = "<span></span><span></span>";
    item.querySelector("span:first-child").textContent = formatRecordTime(record.updated_at);
    item.querySelector("span:last-child").textContent = recordStatusText(record);
    item.addEventListener("click", () => switchSubmissionRecord(record.record_id));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "record-delete";
    remove.textContent = "删除";
    remove.addEventListener("click", () => deleteSubmissionRecord(record, remove));
    row.append(item, remove);
    recordHistory.appendChild(row);
  }
}

function updateCurrentRecordLabel() {
  const record = submissionRecords.find((item) => item.record_id === currentRecordId);
  currentRecord.textContent = record
    ? `${formatRecordTime(record.updated_at)} · ${recordStatusText(record)}`
    : "未保存的新记录";
}

function recordStatusText(record) {
  if (record.status === "submitted") {
    const score = record.last_score == null ? "已判卷" : `${formatNumber(record.last_score)} 分`;
    return `${score} · 提交 ${record.attempt_count || 0} 次`;
  }
  if (record.status === "in_progress") return `已答 ${record.answered_count || 0} 题`;
  return "未开始";
}

function formatRecordTime(value) {
  if (!value) return "时间未知";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "时间未知" : date.toLocaleString();
}

async function switchSubmissionRecord(recordId) {
  if (!currentPaper || recordId === currentRecordId || draftSaveInProgress) return;
  if (draftRevision > savedDraftRevision) {
    const saved = await saveDraft(false);
    if (!saved) return;
  }
  await loadSubmissionRecord(recordId);
}

async function deleteSubmissionRecord(record, button) {
  if (!currentPaper || draftSaveInProgress) return;
  const isCurrent = record.record_id === currentRecordId;
  const message = isCurrent
    ? "确定删除当前做题记录吗？当前答案和判卷结果都会被删除，且无法恢复。"
    : "确定删除这条历史做题记录吗？删除后无法恢复。";
  if (!window.confirm(message)) return;
  button.disabled = true;
  try {
    const response = await fetch(
      `/api/paper/${encodeURIComponent(currentPaper.id)}/submissions/${encodeURIComponent(record.record_id)}`,
      { method: "DELETE" },
    );
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "删除记录失败");
    removeLocalDraftBackup(record.record_id);
    if (isCurrent) {
      currentRecordId = null;
      currentGrade = null;
      hideGrade();
      clearGradeDetails();
      restoreSavedDraft({});
      draftRevision = 0;
      savedDraftRevision = 0;
    }
    await loadSubmissionHistory();
    if (isCurrent && submissionRecords.length) {
      await loadSubmissionRecord(submissionRecords[0].record_id);
    }
    setStatus(isCurrent && submissionRecords.length ? "当前记录已删除，已恢复最近一条记录。" : "做题记录已删除。");
  } catch (error) {
    button.disabled = false;
    setStatus(`删除记录失败：${error.message}`);
  }
}

async function loadSubmissionRecord(recordId) {
  if (!currentPaper) return;
  try {
    const query = new URLSearchParams({ record_id: recordId });
    const response = await fetch(`/api/paper/${encodeURIComponent(currentPaper.id)}/submission?${query}`);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "记录恢复失败");
    currentRecordId = payload.record_id;
    currentGrade = null;
    hideGrade();
    clearGradeDetails();
    const localBackup = loadLocalDraftBackup();
    const shouldRestoreLocal = localBackup?.record_id === payload.record_id
      && hasDraftContent(localBackup.draft)
      && isLocalDraftNewer(localBackup, payload.draft);
    restoreSavedDraft(shouldRestoreLocal ? localBackup.draft : (payload.draft || {}));
    const lastAttempt = payload.attempts?.at(-1);
    if (lastAttempt?.grade) {
      currentGrade = lastAttempt.grade;
      renderGrade(currentGrade);
    }
    draftRevision = shouldRestoreLocal ? 1 : 0;
    savedDraftRevision = 0;
    renderSubmissionHistory();
    if (shouldRestoreLocal) {
      setStatus(`已恢复较新的浏览器本地备份：${formatRecordTime(localBackup.saved_at)}；将继续自动保存。`);
    } else {
      setStatus(`已恢复：${payload.file_name || currentPaper.title} · ${formatRecordTime(payload.draft?.updated_at)}`);
    }
    return true;
  } catch (error) {
    setStatus(`恢复失败：${error.message}`);
    return false;
  }
}

async function createNewSubmissionRecord() {
  if (!currentPaper || draftSaveInProgress) return;
  newRecord.disabled = true;
  try {
    if (draftRevision > savedDraftRevision) {
      const saved = await saveDraft(false);
      if (!saved) return;
    }
    const response = await fetch(`/api/paper/${encodeURIComponent(currentPaper.id)}/submissions`, {
      method: "POST",
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "新建记录失败");
    await loadSubmissionHistory();
    await loadSubmissionRecord(payload.record_id);
    recordHistory.classList.remove("hidden");
    toggleRecordHistory.setAttribute("aria-expanded", "true");
    setStatus("已新建空白做题记录，可以重新作答。");
  } catch (error) {
    setStatus(`新建记录失败：${error.message}`);
  } finally {
    newRecord.disabled = false;
  }
}

async function loadWrongBook() {
  try {
    const response = await fetch("/api/paper/wrong-book");
    if (!response.ok) throw new Error("错题本加载失败");
    const payload = await response.json();
    renderWrongBook(payload.items || []);
  } catch (error) {
    wrongBookList.textContent = error.message;
  }
}

function renderWrongBook(items) {
  wrongBookList.innerHTML = "";
  if (!items.length) {
    wrongBookList.textContent = "还没有错题。完成一次判卷后，答错的题会自动进入这里。";
    return;
  }
  for (const item of items) {
    const card = document.createElement("article");
    card.className = "wrong-book-item";
    const head = document.createElement("div");
    head.className = "wrong-book-item-head";
    const title = document.createElement("strong");
    title.textContent = `${item.paper_title || "试卷"} · 第${item.number || "-"}题`;
    const status = document.createElement("span");
    status.className = `wrong-status ${["reviewed", "mastered"].includes(item.status) ? "reviewed" : ""}`;
    status.textContent = item.status === "mastered" ? "已掌握" : item.status === "reviewed" ? "已复习" : "待复习";
    head.append(title, status);
    card.appendChild(head);

    const stem = document.createElement("p");
    stem.className = "wrong-book-stem";
    stem.textContent = item.stem || "题干未保存";
    card.appendChild(stem);

    const tags = document.createElement("p");
    tags.className = "wrong-book-tags";
    tags.textContent = (item.categories || []).map((category) => {
      const match = questionCategories.find(([id]) => id === category);
      return match ? match[1] : category;
    }).join(" · ") || "未分类";
    card.appendChild(tags);

    const detail = document.createElement("p");
    detail.className = "wrong-book-detail";
    detail.textContent = `你的答案：${formatAnswer(item.student_answer) || "未作答"}；参考答案：${formatAnswer(item.correct_answer) || "未提供"}`;
    card.appendChild(detail);

    const reason = document.createElement("p");
    reason.className = "wrong-book-detail";
    reason.textContent = `解析：${item.explanation || item.reason || item.suggestion || "暂无解析。"}`;
    card.appendChild(reason);

    const review = document.createElement("button");
    review.type = "button";
    review.textContent = "标记已复习";
    review.disabled = ["reviewed", "mastered"].includes(item.status);
    review.addEventListener("click", async () => {
      review.disabled = true;
      await fetch(`/api/paper/wrong-book/${encodeURIComponent(item.id)}/review`, { method: "POST" });
      loadWrongBook();
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "wrong-delete";
    remove.textContent = "删除错题";
    remove.addEventListener("click", async () => {
      if (!window.confirm("确定删除这道错题吗？相关错题历史和笔记都会被删除，且无法恢复。")) return;
      remove.disabled = true;
      try {
        const response = await fetch(`/api/paper/wrong-book/${encodeURIComponent(item.id)}`, { method: "DELETE" });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || "删除错题失败");
        await loadWrongBook();
        setStatus("错题已删除。");
      } catch (error) {
        remove.disabled = false;
        setStatus(`删除错题失败：${error.message}`);
      }
    });
    card.append(review, remove);
    wrongBookList.appendChild(card);
  }
}

function hasAnswer(value) {
  if (Array.isArray(value)) return value.length > 0;
  return String(value || "").trim().length > 0;
}

function downloadJson(filename, data) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function typeLabel(type) {
  return {
    single_choice: "单选",
    multiple_choice: "多选",
    true_false: "判断",
    short_answer: "简答",
    essay: "写作",
    programming: "编程",
    fill_blank: "填空",
    unknown: "题目",
  }[type] || "题目";
}

function formatNumber(value) {
  const number = Number(value || 0);
  return Number.isInteger(number) ? String(number) : number.toFixed(1).replace(/\.0$/, "");
}

function formatAnswer(value) {
  if (Array.isArray(value)) return value.join(", ");
  return String(value ?? "");
}

function escapeAttr(value) {
  return String(value).replaceAll('"', "&quot;");
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

function cssEscape(value) {
  if (window.CSS?.escape) return CSS.escape(value);
  return String(value).replace(/["\\]/g, "\\$&");
}

async function loadFromUrl() {
  const match = location.pathname.match(/^\/exam\/([^/]+)$/);
  const shouldShowWrongBook = new URLSearchParams(location.search).get("wrong") === "1";
  if (!match) {
    await loadCollectionsHome();
    if (shouldShowWrongBook) showWrongBookPanel();
    return;
  }
  try {
    const response = await fetch(`/api/paper/${encodeURIComponent(match[1])}`);
    if (!response.ok) return;
    const payload = await response.json();
    currentPaperId = payload.id;
    if (payload.type === "paper_collection") {
      renderCollection(payload);
      setStatus(`已载入：${payload.title}`);
    } else {
      renderPaper(payload);
      setStatus(`已载入：${payload.title}`);
      await loadSavedDraft();
    }
    if (shouldShowWrongBook) showWrongBookPanel();
  } catch (error) {
    setStatus(`载入失败：${error.message}`);
  }
}

async function loadCollectionsHome() {
  setViewMode("overview");
  try {
    const response = await fetch("/api/paper/-/collections");
    if (!response.ok) return;
    const payload = await response.json();
    const collections = payload.collections || [];
    renderCollectionsHome(collections, payload.categories, payload.trash_count || 0);
    setStatus(`已载入 ${collections.length} 个已生成卷子集合。`);
  } catch {
    // Keep the upload-first empty state if history cannot be loaded.
  }
}

async function libraryRequest(path, method, body) {
  const response = await fetch(`/api/paper/-/${path}`, {
    method, headers: { "Content-Type": "application/json" },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || "保存失败，请重试。");
  return payload;
}

function libraryRenameButton(paper, onSaved) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "library-rename";
  button.textContent = "改名";
  button.setAttribute("aria-label", `给${paper.title || paper.id}改名`);
  button.addEventListener("click", async () => {
    const name = window.prompt("给卷子起个名字", paper.title || "");
    if (name === null) return;
    button.disabled = true;
    try {
      await libraryRequest(`names/${encodeURIComponent(paper.id)}`, "PATCH", { name });
      await onSaved();
      setStatus("名称已保存。");
    } catch (error) { setStatus(error.message); }
    finally { button.disabled = false; }
  });
  return button;
}

function libraryDeleteButton(paper) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "library-delete";
  button.textContent = "删除";
  button.setAttribute("aria-label", `删除${paper.title || paper.id}`);
  button.addEventListener("click", async () => {
    const detail = (paper.paper_count || paper.papers?.length || 0) > 1 ? "集合中的全部卷子" : "这份卷子";
    if (!window.confirm(`将“${paper.title || paper.id}”移入回收站？\n${detail}和作答记录保留15天，可随时恢复；到期后彻底删除。`)) return;
    button.disabled = true;
    try {
      await libraryRequest(`trash/${encodeURIComponent(paper.id)}`, "POST");
      history.replaceState(null, "", "/exam");
      await loadCollectionsHome();
      await refreshGenerationHistory();
      setStatus("已移入回收站，15天内可以恢复。");
    } catch (error) { button.disabled = false; setStatus(error.message); }
  });
  return button;
}

async function showLibraryTrash() {
  try {
    const response = await fetch("/api/paper/-/trash", { cache: "no-store" });
    if (!response.ok) throw new Error("回收站暂时无法打开，请重试。");
    const payload = await response.json();
    renderCollectionsHome([], undefined, payload.items.length);
    paperTitle.textContent = "回收站";
    paperMeta.textContent = "删除的卷子保留15天";
    paperDesc.textContent = "到期自动彻底删除。恢复后，原名称、分类和作答记录一并保留。";
    paperRoot.replaceChildren();
    const back = document.createElement("button");
    back.type = "button";
    back.className = "trash-back";
    back.textContent = "← 返回卷子";
    back.addEventListener("click", loadCollectionsHome);
    paperRoot.appendChild(back);
    for (const entry of payload.items) {
      const item = document.createElement("article");
      item.className = "collection-item trash-item";
      const info = document.createElement("div");
      const title = document.createElement("h3");
      title.textContent = entry.title;
      const detail = document.createElement("p");
      detail.textContent = `${entry.paper_count} 套试卷 · 剩余${entry.days_left}天 · 将于${new Date(entry.expires_at).toLocaleString("zh-CN", { hour12: false })}彻底删除`;
      info.append(title, detail);
      const restore = document.createElement("button");
      restore.type = "button";
      restore.textContent = "恢复卷子";
      restore.addEventListener("click", async () => {
        restore.disabled = true;
        try {
          await libraryRequest(`trash/${entry.id}/restore`, "POST");
          await showLibraryTrash();
          await refreshGenerationHistory();
          setStatus("卷子已恢复，返回卷子列表即可查看。");
        } catch (error) { restore.disabled = false; setStatus(error.message); }
      });
      item.append(info, restore);
      paperRoot.appendChild(item);
    }
    if (!payload.items.length) {
      const empty = document.createElement("p");
      empty.className = "collection-empty";
      empty.textContent = "回收站是空的。";
      paperRoot.appendChild(empty);
    }
  } catch (error) { setStatus(error.message); }
}

function renderCollectionsHome(collections, shelfNames, trashCount = 0) {
  const names = shelfNames || { mock: "原创模拟卷", past: "历年真题", practice: "专项练习", other: "其他" };
  const collectionOrder = {
    "shandong-diagnostic-20260908": 0,
    "8fc1d0d6a3ee4ccbaf1a973e20c93fde": 1,
    "shangji-simulated-manual-20260806": 3,
  };
  collections = [...collections].sort((a, b) => (collectionOrder[a.id] ?? 2) - (collectionOrder[b.id] ?? 2));
  showPaperQuality(null);
  stopAutoSave();
  setViewMode("overview");
  currentPaper = null;
  currentGrade = null;
  currentRecordId = null;
  submissionRecords = [];
  hideGrade();
  recordPanel.classList.add("hidden");
  paperTitle.textContent = "已生成卷子";
  paperDesc.textContent = "选择一个卷子集合或具体年份开始考试";
  paperMeta.textContent = "本地生成记录";
  questionCount.textContent = collections.reduce((sum, collection) => sum + Number(collection.question_count || 0), 0);
  totalScore.textContent = String(collections.reduce((sum, collection) => sum + Number(collection.paper_count || 0) * 100, 0));
  duration.textContent = "-";
  answeredCount.textContent = "0/0";
  questionCard.innerHTML = "";

  paperRoot.classList.remove("empty");
  paperRoot.innerHTML = "";

  const list = document.createElement("section");
  list.className = "collection-list";
  for (const collection of collections) {
    const item = document.createElement("article");
    item.className = "collection-item collection-item-wide";
    item.innerHTML = `
      <div>
        <h3></h3>
        <p></p>
        <div class="paper-links"></div>
      </div>
      <a class="collection-open"></a>
    `;
    item.querySelector("h3").textContent = collection.title || collection.id;
    item.querySelector("h3").appendChild(libraryRenameButton(collection, loadCollectionsHome));
    item.querySelector("h3").appendChild(libraryDeleteButton(collection));
    item.querySelector("p").textContent = `${collection.paper_count || 0} 套 · ${collection.question_count || 0} 题 · ${collection.source?.file_name || "PDF"}`;
    item.dataset.collectionId = collection.id;
    const links = item.querySelector(".paper-links");
    for (const paper of collection.papers || []) {
      const link = document.createElement("a");
      link.href = paper.paper_url;
      link.textContent = `${paper.title || paper.id} · ${paper.quality?.label || "尚未检查"}`;
      links.appendChild(link);
      if ((collection.papers || []).length > 1) {
        const row = document.createElement("div");
        row.className = "library-paper-row";
        row.append(link, libraryRenameButton(paper, loadCollectionsHome), libraryDeleteButton(paper));
        links.appendChild(row);
      }
    }
    const open = item.querySelector(".collection-open");
    open.href = collection.paper_url;
    open.textContent = "查看集合";
    const controls = document.createElement("div");
    controls.className = "collection-controls";
    const categoryLabel = document.createElement("label");
    categoryLabel.textContent = "分类 ";
    const select = document.createElement("select");
    select.setAttribute("aria-label", `${collection.title || collection.id}的分类`);
    categoryLabel.firstChild.textContent = `分类 · ${names[collection.category] || "其他"} `;
    select.add(new Option("按名称自动分类", "auto"));
    for (const [value, label] of Object.entries(names)) select.add(new Option(label, value));
    select.add(new Option("＋ 新建分类架…", "_new"));
    select.value = collection.category_manual ? collection.category : "auto";
    select.addEventListener("change", async () => {
      const previous = collection.category_manual ? collection.category : "auto";
      select.disabled = true;
      try {
        let chosen = select.value;
        if (chosen === "_new") {
          const name = window.prompt("新分类架叫什么？例如：考前冲刺、待做卷子");
          if (name === null) { select.value = previous; return; }
          const shelf = await libraryRequest("shelves", "POST", { name });
          chosen = shelf.id;
          await libraryRequest(`collections/${encodeURIComponent(collection.id)}/category`, "PATCH", { category: chosen });
          try { localStorage.setItem("exam-collection-category", chosen); } catch {}
          await loadCollectionsHome();
          setStatus(`已创建“${shelf.name}”，并将卷子放入。`);
          return;
        }
        const response = await fetch(`/api/paper/-/collections/${encodeURIComponent(collection.id)}/category`, {
          method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ category: select.value }),
        });
        if (!response.ok) throw new Error("分类保存失败，请重试。");
        Object.assign(collection, await response.json());
        categoryLabel.firstChild.textContent = `分类 · ${names[collection.category]} `;
        setStatus(`已归入“${names[collection.category]}”。`);
        applyCollectionFilter();
      } catch (error) { select.value = previous; setStatus(error.message); }
      finally { select.disabled = false; }
    });
    categoryLabel.appendChild(select);
    controls.append(open, categoryLabel);
    item.appendChild(controls);
    list.appendChild(item);
  }
  const toolbar = document.createElement("section");
  toolbar.className = "collection-toolbar";
  toolbar.setAttribute("aria-label", "试卷分类与搜索");
  const filters = document.createElement("div");
  filters.className = "collection-filters";
  filters.setAttribute("role", "group");
  filters.setAttribute("aria-label", "按分类筛选试卷");
  const categories = { all: "全部", ...names };
  let selected = "all";
  try { selected = localStorage.getItem("exam-collection-category") || "all"; } catch {}
  if (!categories[selected]) selected = "all";
  const search = document.createElement("input");
  search.type = "search";
  search.placeholder = "搜索卷名或年份";
  search.setAttribute("aria-label", "搜索卷名或年份");
  const summary = document.createElement("p");
  summary.className = "collection-filter-summary";
  summary.setAttribute("aria-live", "polite");
  const empty = document.createElement("p");
  empty.className = "collection-empty";
  empty.textContent = "没有符合条件的试卷，可切换“全部”或清空搜索。";
  const shelfActions = document.createElement("div");
  shelfActions.className = "shelf-actions";
  function shelfButton(label, action) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.addEventListener("click", async () => {
      button.disabled = true;
      try { await action(); } catch (error) { setStatus(error.message); }
      finally { button.disabled = false; }
    });
    shelfActions.appendChild(button);
    return button;
  }
  shelfButton("＋ 新建分类架", async () => {
    const name = window.prompt("新分类架叫什么？例如：考前冲刺、待做卷子");
    if (name === null) return;
    const shelf = await libraryRequest("shelves", "POST", { name });
    try { localStorage.setItem("exam-collection-category", shelf.id); } catch {}
    await loadCollectionsHome();
    setStatus(`已创建“${shelf.name}”。在卷子旁选择分类架即可放入。`);
  });
  shelfButton(`回收站${trashCount ? `（${trashCount}）` : ""}`, showLibraryTrash);
  const renameShelf = shelfButton("分类架改名", async () => {
    const name = window.prompt("修改分类架名称", names[selected]);
    if (name === null) return;
    await libraryRequest(`shelves/${encodeURIComponent(selected)}`, "PATCH", { name });
    await loadCollectionsHome();
  });
  const deleteShelf = shelfButton("删除分类架", async () => {
    if (!window.confirm(`删除“${names[selected]}”？卷子会保留，并恢复自动分类。`)) return;
    await libraryRequest(`shelves/${encodeURIComponent(selected)}`, "DELETE");
    try { localStorage.setItem("exam-collection-category", "all"); } catch {}
    await loadCollectionsHome();
  });
  for (const [key, label] of Object.entries(categories)) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.category = key;
    button.addEventListener("click", () => {
      selected = key;
      try { localStorage.setItem("exam-collection-category", key); } catch {}
      applyCollectionFilter();
    });
    filters.appendChild(button);
  }
  function applyCollectionFilter() {
    const term = search.value.trim().toLocaleLowerCase();
    const visible = collections.filter(c => (selected === "all" || c.category === selected) &&
      [c.title, c.source?.file_name, ...(c.papers || []).map(p => p.title)].join(" ").toLocaleLowerCase().includes(term));
    const ids = new Set(visible.map(c => c.id));
    for (const item of list.children) item.hidden = !ids.has(item.dataset.collectionId);
    for (const button of filters.children) {
      const key = button.dataset.category;
      const count = collections.filter(c => key === "all" || c.category === key).length;
      button.textContent = `${categories[key]} ${count}`;
      button.setAttribute("aria-pressed", String(selected === key));
    }
    summary.textContent = `${categories[selected]} · ${visible.length} 个集合 · ${visible.reduce((n, c) => n + Number(c.paper_count || 0), 0)} 套试卷`;
    questionCount.textContent = visible.reduce((n, c) => n + Number(c.question_count || 0), 0);
    totalScore.textContent = visible.reduce((n, c) => n + Number(c.paper_count || 0) * 100, 0);
    empty.hidden = visible.length > 0;
    renameShelf.hidden = selected === "all";
    deleteShelf.hidden = !selected.startsWith("shelf-");
  }
  search.addEventListener("input", applyCollectionFilter);
  toolbar.append(filters, search, shelfActions, summary);
  paperRoot.appendChild(toolbar);
  paperRoot.appendChild(list);
  paperRoot.appendChild(empty);
  applyCollectionFilter();

  exportJson.disabled = true;
  exportAnswers.disabled = true;
  saveAnswers.disabled = true;
  clearAnswers.disabled = true;
  submitPaper.disabled = true;
}

loadFromUrl().then(initExamGeneration);
