const paperRoot = document.querySelector("#wrong-list");
const currentPaper = { id: "wrong-book" };
const practiceViews = new Map();
const practiceStorageKey = "wrong-book-practice:v1";
let practiceData = {};
let practiceSubmitting = false;
let practiceVisibleIds = [];
try {
  const saved = JSON.parse(localStorage.getItem(practiceStorageKey) || "{}");
  if (saved && typeof saved === "object" && !Array.isArray(saved)) practiceData = saved;
} catch { /* A fresh practice remains available without browser storage. */ }

function setStatus(message) { showMessage(message); }
function savePractice() {
  persistPracticeRecord();
}
function practiceEntry(item) {
  if (!practiceData[item.id] || typeof practiceData[item.id] !== "object") {
    practiceData[item.id] = { answer: "", doubt: false, revealed: false, previousAnswer: item.last_review_answer ?? item.student_answer ?? "" };
  }
  return practiceData[item.id];
}

function renderPracticeCard(item) {
  const saved = practiceEntry(item);
  const card = createElement("article", `wrong-card practice-card ${item.exam_type === "cloze" ? "practice-cloze-card" : ""}`);
  card.id = `practice-${item.id}`;
  card.dataset.entryId = item.id;
  const head = createElement("header", "practice-question-head");
  head.appendChild(createElement("strong", "", `第 ${item.number} 题`));
  const source = createElement("a", "practice-source", item.paper_title || "打开原卷");
  source.href = item.paper_id ? `/exam/${encodeURIComponent(item.paper_id)}` : "/exam";
  head.appendChild(source);
  const stem = createElement("div", "wrong-stem");
  const text = createElement("span", "question-stem", item.stem || "请作答");
  text.dataset.annotationKey = `${item.id}:stem`;
  const doubt = createElement("button", "practice-doubt", "[存疑]");
  doubt.type = "button";
  doubt.setAttribute("aria-pressed", String(Boolean(saved.doubt)));
  doubt.addEventListener("click", () => {
    saved.doubt = !saved.doubt;
    doubt.setAttribute("aria-pressed", String(saved.doubt));
    savePractice();
    updatePracticeNav();
  });
  stem.append(text, doubt);
  const control = createAnswerControl(item);
  const inputs = [...control.element.querySelectorAll("input")];
  const values = Array.isArray(saved.answer) ? saved.answer : [saved.answer];
  inputs.forEach((input) => { input.checked = values.includes(input.value); });
  const textarea = control.element.querySelector("textarea");
  if (textarea) textarea.value = typeof saved.answer === "string" ? saved.answer : "";
  const feedback = createElement("section", "practice-feedback");
  feedback.setAttribute("aria-label", `第 ${item.number} 题核对结果`);
  feedback.hidden = true;
  const feedbackText = createElement("div", "practice-feedback-text");
  const notes = renderNoteEditor(item);
  notes.open = true;
  feedback.append(feedbackText, notes);
  const check = createElement("button", "card-action practice-check", "核对答案");
  check.type = "button";
  check.setAttribute("aria-expanded", "false");
  const displayFeedback = () => {
    const result = saved.result;
    const judged = typeof result?.is_correct === "boolean";
    feedbackText.replaceChildren();
    if (result) {
      feedbackText.appendChild(createElement("strong", "practice-verdict", judged ? (result.is_correct ? "本次答对" : "本次答错") : (result.grading_status === "unanswered" ? "本次未作答" : "待判定")));
    }
    feedbackText.append(
      createElement("p", "", `参考答案：${formatAnswer(result?.correct_answer ?? item.correct_answer) || "未提供"}；本次答案：${formatAnswer(saved.answer) || "未作答"}`),
      createElement("p", "practice-previous", `上次答案：${formatAnswer(saved.previousAnswer) || "未作答"}`),
      createElement("p", "", `解析：${result?.reason || item.reason || item.explanation || "暂无解析。"}`),
      createElement("p", "", `建议：${result?.suggestion || item.suggestion || "结合题干和参考答案复盘。"}`),
    );
    feedback.hidden = !saved.revealed;
    check.setAttribute("aria-expanded", String(Boolean(saved.revealed)));
    check.textContent = saved.revealed ? "收起核对结果" : "核对答案";
    card.classList.toggle("practice-correct", judged && result.is_correct);
    card.classList.toggle("practice-incorrect", judged && !result.is_correct);
    const number = card.querySelector(".practice-cloze-number");
    if (number) number.textContent = `${item.number}（${formatAnswer(saved.answer)}）`;
  };
  const onAnswer = () => {
    if (saved.result) saved.previousAnswer = saved.result.student_answer;
    saved.answer = control.read();
    saved.result = null;
    savePractice();
    displayFeedback();
    updatePracticeNav();
  };
  control.element.addEventListener("input", onAnswer);
  check.addEventListener("click", () => {
    saved.revealed = !saved.revealed;
    savePractice();
    displayFeedback();
  });
  card.append(head, stem, control.element);
  if (item.exam_type === "cloze") {
    const row = createElement("div", "practice-cloze-row");
    const number = createElement("strong", "practice-cloze-number", `${item.number}（）`);
    row.append(number, control.element, doubt);
    card.appendChild(row);
    const tools = createElement("details", "practice-tools");
    tools.append(createElement("summary", "", "不会类型"), renderCategoryEditor(item));
    card.appendChild(tools);
  } else {
    card.appendChild(renderCategoryEditor(item));
  }
  card.append(check, feedback);
  const management = createElement("details", "practice-management");
  management.appendChild(createElement("summary", "", "管理此题"));
  const remove = createElement("button", "card-action danger", "删除错题");
  remove.type = "button";
  remove.addEventListener("click", () => deleteItem(item, remove));
  management.appendChild(remove);
  if (item.status !== "unreviewed") {
    const reopen = createElement("button", "card-action secondary", "重新加入待重做");
    reopen.type = "button";
    reopen.addEventListener("click", () => updateItem(item, { status: "unreviewed" }, "已重新加入待重做"));
    management.appendChild(reopen);
  }
  (card.querySelector(".practice-tools") || card).appendChild(management);
  practiceViews.set(item.id, { item, card, displayFeedback });
  displayFeedback();
  return card;
}

function renderPracticeNav(items) {
  practiceVisibleIds = items.map((item) => item.id);
  const root = document.querySelector("#practice-question-card");
  root.replaceChildren();
  document.querySelector("#practice-nav-title").textContent = `${examTypeLabels[state.examType]}答题卡`;
  const groups = new Map();
  for (const item of items) {
    const key = item.paper_id || item.paper_title || "未命名试卷";
    if (!groups.has(key)) {
      const group = createElement("div", "practice-nav-group");
      group.appendChild(createElement("h4", "", item.paper_title || "未命名试卷"));
      const grid = createElement("div", "practice-nav-grid");
      group.appendChild(grid);
      root.appendChild(group);
      groups.set(key, grid);
    }
    const button = createElement("button", "practice-number", item.number);
    button.type = "button";
    button.dataset.entryId = item.id;
    button.setAttribute("aria-label", `${item.paper_title || ""} 第 ${item.number} 题`);
    button.addEventListener("click", () => document.getElementById(`practice-${item.id}`)?.scrollIntoView({ behavior: "smooth", block: "start" }));
    groups.get(key).appendChild(button);
  }
  document.querySelector("#submit-practice").disabled = !items.length || practiceSubmitting;
  updatePracticeNav();
}

function updatePracticeNav() {
  const items = practiceVisibleIds.map((id) => practiceData[id] || {});
  document.querySelector("#practice-progress").textContent = `${items.filter((entry) => hasAnswer(entry.answer)).length}/${items.length} 已答`;
  document.querySelectorAll(".practice-number").forEach((button) => {
    const entry = practiceData[button.dataset.entryId] || {};
    button.classList.toggle("answered", hasAnswer(entry.answer));
    button.classList.toggle("doubtful", Boolean(entry.doubt));
    button.classList.toggle("correct", entry.result?.is_correct === true);
    button.classList.toggle("incorrect", entry.result?.is_correct === false);
  });
  const submitted = items.filter((entry) => entry.result);
  document.querySelector("#practice-summary").textContent = submitted.length
    ? `本组 ${items.length} 题 · 已判对 ${submitted.filter((entry) => entry.result.is_correct === true).length} 题 · 已判错 ${submitted.filter((entry) => entry.result.is_correct === false).length} 题 · 未判定 ${items.filter((entry) => typeof entry.result?.is_correct !== "boolean").length} 题`
    : "完成当前筛选出的错题后，提交本组答案查看对错与解析。";
  renderPracticeRecordPanel();
}

document.querySelector("#submit-practice").addEventListener("click", async () => {
  if (practiceSubmitting || practiceRecordBusy || !activePracticeRecord || !practiceVisibleIds.length) return;
  const items = practiceVisibleIds.map((id) => practiceViews.get(id).item);
  if (!items.some((item) => hasAnswer(practiceEntry(item).answer))) {
    showMessage("请先完成至少一道题。", true);
    return;
  }
  const unanswered = items.filter((item) => !hasAnswer(practiceEntry(item).answer));
  const doubts = items.filter((item) => practiceEntry(item).doubt);
  if ((unanswered.length || doubts.length) && !window.confirm(`本组还有 ${unanswered.length} 道题未答、${doubts.length} 道题存疑。${doubts.length ? `\n存疑题：${doubts.map((item) => `${item.paper_title} 第${item.number}题`).join("；")}` : ""}\n是否仍然提交？`)) return;
  practiceSubmitting = true;
  const controls = [...document.querySelectorAll("button, input, textarea")];
  const disabledStates = controls.map((el) => el.disabled);
  controls.forEach((el) => { el.disabled = true; });
  document.querySelector("#practice-summary").textContent = "正在提交本组作答，汉译英和作文判卷可能需要稍等……";
  try {
    await flushPracticeRecord();
    const payload = await request("/api/paper/wrong-book/submit", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ record_id: activePracticeRecord?.record_id, entries: items.map((item) => ({ entry_id: item.id, answer: practiceEntry(item).answer })) }),
    });
    for (const result of payload.results || []) {
      const entry = practiceData[result.entry_id];
      if (!entry) continue;
      entry.result = result;
      entry.previousAnswer = result.previous_answer ?? entry.previousAnswer;
      entry.revealed = true;
      practiceViews.get(result.entry_id)?.displayFeedback();
    }
    (payload.items || []).forEach(replaceItem);
    if (payload.record) activePracticeRecord = { ...payload.record, draft: practiceData };
    savePractice();
    renderSummary();
    updatePracticeNav();
    showMessage("本组作答已提交，对错与解析已显示在每道题下方。");
  } catch (error) {
    document.querySelector("#practice-summary").textContent = `提交失败：${error.message}。作答已保留，可重试。`;
    showMessage(error.message, true);
  } finally {
    practiceSubmitting = false;
    controls.forEach((el, index) => { if (el.isConnected) el.disabled = disabledStates[index]; });
    renderPracticeRecordPanel();
  }
});
