const listRoot = document.querySelector("#wrong-list");
const emptyState = document.querySelector("#wrong-empty");
const visibleCount = document.querySelector("#visible-count");
const resultCaption = document.querySelector("#result-caption");
const searchInput = document.querySelector("#wrong-search");
const refreshButton = document.querySelector("#refresh-list");
const statusMessage = document.querySelector("#wrong-status");
const resultsTitle = document.querySelector("#results-title");

const categoryLabels = {
  grammar: "语法",
  vocabulary: "单词",
  phrase: "词组",
  translation: "翻译",
};

const statusLabels = {
  unreviewed: "待重做",
  reviewed: "已复习",
  mastered: "已掌握",
};

const examTypeLabels = {
  choice: "选择",
  translation: "汉译英",
  cloze: "完型",
  reading: "阅读",
  writing: "作文",
};

const state = {
  items: [],
  contexts: {},
  examType: "choice",
  status: "all",
  category: "all",
  query: "",
};

let messageTimer = null;

document.querySelectorAll("[data-status]").forEach((button) => {
  button.addEventListener("click", () => setStatusFilter(button.dataset.status));
});

document.querySelectorAll("[data-exam-type]").forEach((button) => {
  button.addEventListener("click", () => setExamTypeFilter(button.dataset.examType));
});

document.querySelectorAll("[data-category]").forEach((button) => {
  button.addEventListener("click", () => setCategoryFilter(button.dataset.category));
});

searchInput.addEventListener("input", () => {
  state.query = searchInput.value.trim().toLocaleLowerCase();
  renderList();
});

refreshButton.addEventListener("click", loadWrongBook);

function createElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

async function request(url, options = {}) {
  const response = await fetch(url, options);
  let payload = {};
  try {
    payload = await response.json();
  } catch {
    payload = {};
  }
  if (!response.ok) {
    throw new Error(payload.detail || "请求失败");
  }
  return payload;
}

function normalizeItem(item) {
  const status = Object.hasOwn(statusLabels, item.status) ? item.status : "unreviewed";
  const examType = Object.hasOwn(examTypeLabels, item.exam_type)
    ? item.exam_type
    : inferExamType(item);
  return {
    ...item,
    status,
    exam_type: examType,
    context_key: String(item.context_key || ""),
    categories: Array.isArray(item.categories) ? item.categories : [],
    options: Array.isArray(item.options) ? item.options : [],
    key_phrases: Array.isArray(item.key_phrases) ? item.key_phrases : [],
    wrong_count: item.wrong_count === undefined ? 1 : Number(item.wrong_count || 0),
    review_count: Number(item.review_count || 0),
    correct_review_count: Number(item.correct_review_count || 0),
  };
}

function inferExamType(item) {
  const title = String(item.section_title || "").toLocaleLowerCase();
  const type = String(item.question_type || "");
  if (title.includes("cloze") || title.includes("完形") || title.includes("完型")) return "cloze";
  if (title.includes("reading") || title.includes("阅读")) return "reading";
  if (["essay", "writing", "composition"].includes(type) || title.includes("writing") || title.includes("作文")) {
    return "writing";
  }
  if (type === "translation" || (type === "short_answer" && (title.includes("translation") || title.includes("翻译")))) {
    return "translation";
  }
  return "choice";
}

async function loadWrongBook() {
  return runPracticeRecordTransition(async () => {
  refreshButton.disabled = true;
  resultCaption.textContent = "正在读取错题记录";
  try {
    await flushPracticeRecord();
    const payload = await request("/api/paper/wrong-book");
    state.items = (payload.items || []).map(normalizeItem);
    state.contexts = payload.contexts && typeof payload.contexts === "object" ? payload.contexts : {};
    await loadPracticeRecordsForType();
    renderSummary();
    renderList();
  } catch (error) {
    resultCaption.textContent = "错题记录加载失败";
    showMessage(error.message, true);
  } finally {
    refreshButton.disabled = false;
  }
  });
}

function setStatusFilter(status) {
  state.status = status || "all";
  document.querySelectorAll("[data-status]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.status === state.status));
  });
  renderList();
}

async function setExamTypeFilter(examType) {
  return runPracticeRecordTransition(async () => {
  await flushPracticeRecord();
  const previousType = state.examType;
  const previousRecords = practiceRecordList;
  state.examType = Object.hasOwn(examTypeLabels, examType) ? examType : "choice";
  try { await loadPracticeRecordsForType(); }
  catch (error) { state.examType = previousType; practiceRecordList = previousRecords; throw error; }
  state.category = "all";
  document.querySelectorAll("[data-exam-type]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.examType === state.examType));
  });
  document.querySelectorAll("[data-category]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.category === "all"));
  });
  renderSummary();
  renderList();
  });
}

function setCategoryFilter(category) {
  state.category = category || "all";
  document.querySelectorAll("[data-category]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.category === state.category));
  });
  renderList();
}

function renderSummary() {
  for (const examType of Object.keys(examTypeLabels)) {
    const count = state.items.filter((item) => item.exam_type === examType).length;
    const counter = document.querySelector(`#type-count-${examType}`);
    if (counter) counter.textContent = count;
  }
}

function filteredItems(ignoreRecord = false) {
  const items = state.items.filter((item) => {
    if (item.exam_type !== state.examType) return false;
    if (!ignoreRecord && activePracticeRecord?.exam_type === state.examType && !activePracticeRecord.entry_ids.includes(item.id)) return false;
    if (state.status !== "all" && item.status !== state.status) return false;
    if (state.category === "noted" && !String(item.note || "").trim()) return false;
    if (state.category !== "all" && state.category !== "noted" && !item.categories.includes(state.category)) return false;
    if (!state.query) return true;
    const context = state.contexts[item.context_key] || {};
    const searchText = [
      item.paper_title,
      item.section_title,
      item.number,
      item.stem,
      item.reason,
      item.suggestion,
      item.note,
      context.directions,
      context.passage,
      ...(context.questions || []).map((question) => question.stem),
    ].join(" ").toLocaleLowerCase();
    return searchText.includes(state.query);
  });
  const papers = [...new Set(items.map((item) => item.paper_id || item.paper_title || ""))];
  const paperOrder = new Map(papers.map((key, index) => [key, index]));
  return items.sort((a, b) =>
    paperOrder.get(a.paper_id || a.paper_title || "") - paperOrder.get(b.paper_id || b.paper_title || "")
    || String(a.number).localeCompare(String(b.number), "zh-CN", { numeric: true }),
  );
}

function renderList() {
  const items = filteredItems();
  const typeItems = state.items.filter((item) => item.exam_type === state.examType);
  practiceViews.clear();
  listRoot.innerHTML = "";
  emptyState.hidden = items.length > 0;
  visibleCount.textContent = `${items.length} 题`;
  resultsTitle.textContent = `${examTypeLabels[state.examType]}错题`;
  resultCaption.textContent = state.items.length
    ? `${examTypeLabels[state.examType]}共 ${typeItems.length} 道错题，当前显示 ${items.length} 道`
    : "还没有错题记录";
  if (state.examType === "cloze" || state.examType === "reading") {
    renderContextGroups(items);
  } else {
    for (const item of items) listRoot.appendChild(renderCard(item));
  }
  renderPracticeNav(items);
  setupTextAnnotations();
}

function renderContextGroups(items) {
  const groups = new Map();
  for (const item of items) {
    const key = item.context_key && state.contexts[item.context_key]
      ? item.context_key
      : `missing:${item.id}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(item);
  }
  for (const [key, groupItems] of groups) {
    const context = state.contexts[key];
    if (!context) {
      groupItems.forEach((item) => listRoot.appendChild(renderCard(item)));
      continue;
    }
    const group = createElement("section", `context-group ${state.examType === "cloze" ? "practice-cloze-group" : ""}`);
    group.appendChild(renderContextPanel(groupItems, context, true));
    const groupList = createElement("div", "context-group-items");
    groupItems.forEach((item) => groupList.appendChild(renderCard(item, { contextShown: true })));
    group.appendChild(groupList);
    if (state.examType === "cloze") {
      const scroller = createElement("div", "practice-cloze-scroll");
      scroller.tabIndex = 0;
      scroller.setAttribute("aria-label", "完形文章与题目，可左右滚动");
      scroller.appendChild(group);
      listRoot.appendChild(scroller);
    } else {
      listRoot.appendChild(group);
    }
  }
}

function renderCard(item) {
  return renderPracticeCard(item);
}

function renderContextPanel(items, context, standalone = false) {
  const panel = createElement("section", `context-panel ${standalone ? "standalone" : ""}`);
  const head = createElement("header", "context-head");
  const contextLabel = state.examType === "cloze" ? "完型原文" : "阅读原文";
  head.append(
    createElement("strong", "", context.title ? `${contextLabel} · ${context.title}` : contextLabel),
    createElement("span", "", `共 ${(context.questions || []).length} 题 · 当前 ${items.length} 道错题`),
  );
  panel.appendChild(head);
  if (context.directions) panel.appendChild(createElement("p", "context-directions", context.directions));
  if (context.passage) {
    const passage = createElement("article", "context-passage section-passage", context.passage);
    passage.dataset.annotationKey = `context:${items[0].context_key}`;
    panel.appendChild(passage);
  }

  return panel;
}

function isTranslationItem(item) {
  const title = String(item.section_title || "").toLocaleLowerCase();
  return item.question_type === "translation" || (
    item.question_type === "short_answer" && (title.includes("translation") || title.includes("翻译"))
  );
}

function renderTranslationDetails(item) {
  if (!isTranslationItem(item)) return null;
  if (!item.key_phrases.length && !item.reason && !item.suggestion) return null;
  const details = createElement("div", "translation-details");
  if (item.key_phrases.length) {
    details.appendChild(createElement("strong", "", "固定搭配 / 重点词组"));
    details.appendChild(createElement("p", "", item.key_phrases.join("；")));
  }
  const feedback = [item.reason, item.suggestion].filter(Boolean).join("\n");
  if (feedback) {
    details.appendChild(createElement("strong", "", "判卷备注"));
    details.appendChild(createElement("p", "", feedback));
  }
  return details;
}

function normalizeOption(option, index) {
  const fallbackId = String.fromCharCode(65 + index);
  if (option && typeof option === "object") {
    return { id: String(option.id || fallbackId), text: String(option.text || "") };
  }
  const text = String(option || "");
  const match = text.match(/^([A-Z])\s*[.、]\s*(.*)$/s);
  return match ? { id: match[1], text: match[2] } : { id: fallbackId, text };
}

function renderCategoryEditor(item) {
  const editor = createElement("div", "category-editor");
  editor.appendChild(createElement("span", "", "不会类型"));
  for (const [category, label] of Object.entries(categoryLabels)) {
    const selected = item.categories.includes(category);
    const button = createElement("button", `category-chip ${selected ? "selected" : ""}`, label);
    button.type = "button";
    button.setAttribute("aria-pressed", String(selected));
    button.addEventListener("click", async () => {
      const categories = selected
        ? item.categories.filter((value) => value !== category)
        : [...item.categories, category];
      await updateItem(item, { categories }, "不会类型已保存");
    });
    editor.appendChild(button);
  }
  return editor;
}

function createAnswerControl(item) {
  const choiceTypes = new Set(["single_choice", "multiple_choice", "true_false"]);
  if (item.options.length && (choiceTypes.has(item.question_type) || Array.isArray(item.correct_answer))) {
    const wrap = createElement("div", "review-answer");
    wrap.appendChild(createElement("span", "", "本次答案"));
    const choices = createElement("div", "review-choices");
    const multiple = item.question_type === "multiple_choice" || Array.isArray(item.correct_answer);
    item.options.forEach((option, index) => {
      const normalized = normalizeOption(option, index);
      const label = createElement("label", "review-choice option");
      const input = document.createElement("input");
      input.type = multiple ? "checkbox" : "radio";
      input.name = `review-${item.id}`;
      input.value = normalized.id;
      label.append(input, createElement("span", "", `${normalized.id}. ${normalized.text}`));
      label.querySelector("span").dataset.annotationKey = `${item.id}:option:${normalized.id}`;
      choices.appendChild(label);
    });
    wrap.appendChild(choices);
    return {
      element: wrap,
      read: () => {
        const checked = [...choices.querySelectorAll("input:checked")].map((input) => input.value);
        return multiple ? checked : (checked[0] || "");
      },
      focus: () => choices.querySelector("input")?.focus(),
    };
  }

  const label = createElement("label", "review-answer");
  label.appendChild(createElement("span", "", "本次答案"));
  const textarea = document.createElement("textarea");
  textarea.placeholder = "填写答案";
  label.appendChild(textarea);
  return {
    element: label,
    read: () => textarea.value.trim(),
    focus: () => textarea.focus(),
  };
}

function renderNoteEditor(item) {
  const details = createElement("details", "note-details");
  const summary = createElement("summary", "", item.note ? "订正笔记（已保存）" : "订正笔记");
  details.appendChild(summary);
  const editor = createElement("div", "note-editor");
  const label = createElement("label", "", "错因、知识点或下次提醒");
  const textarea = document.createElement("textarea");
  textarea.value = practiceEntry(item).note ?? item.note ?? "";
  textarea.addEventListener("input", () => { practiceEntry(item).note = textarea.value; savePractice(); });
  const actions = createElement("div", "note-actions");
  const save = createElement("button", "note-action", "保存笔记");
  save.type = "button";
  const status = createElement("span");
  save.addEventListener("click", async () => {
    save.disabled = true;
    status.textContent = "";
    try {
      const updated = await request(`/api/paper/wrong-book/${encodeURIComponent(item.id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note: textarea.value }),
      });
      replaceItem(updated);
      delete practiceEntry(item).note;
      item.note = updated.note;
      savePractice();
      status.textContent = "已保存";
      summary.textContent = updated.note ? "订正笔记（已保存）" : "订正笔记";
    } catch (error) {
      showMessage(error.message, true);
    } finally {
      save.disabled = false;
    }
  });
  actions.append(save, status);
  editor.append(label, textarea, actions);
  details.appendChild(editor);
  return details;
}

async function updateItem(item, changes, message) {
  try {
    const updated = await request(`/api/paper/wrong-book/${encodeURIComponent(item.id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(changes),
    });
    replaceItem(updated);
    renderSummary();
    renderList();
    showMessage(message);
  } catch (error) {
    showMessage(error.message, true);
  }
}

async function deleteItem(item, button) {
  if (!window.confirm("确定删除这道错题吗？相关错题历史和笔记都会被删除，且无法恢复。")) return;
  button.disabled = true;
  try {
    await request(`/api/paper/wrong-book/${encodeURIComponent(item.id)}`, { method: "DELETE" });
    state.items = state.items.filter((entry) => entry.id !== item.id);
    renderSummary();
    renderList();
    showMessage("错题已删除");
  } catch (error) {
    button.disabled = false;
    showMessage(error.message, true);
  }
}

function replaceItem(updated) {
  const index = state.items.findIndex((item) => item.id === updated.id);
  if (index >= 0) state.items[index] = normalizeItem({ ...state.items[index], ...updated });
}

function hasAnswer(value) {
  if (Array.isArray(value)) return value.length > 0;
  return String(value ?? "").trim().length > 0;
}

function formatAnswer(value) {
  if (Array.isArray(value)) return value.join(", ");
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value ?? "");
}

function formatDate(value) {
  if (!value) return "时间未知";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未知";
  return date.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
}

function showMessage(message, isError = false) {
  window.clearTimeout(messageTimer);
  statusMessage.textContent = message;
  statusMessage.classList.toggle("error", isError);
  statusMessage.classList.add("visible");
  messageTimer = window.setTimeout(() => statusMessage.classList.remove("visible"), 2600);
}

loadWrongBook();
