const dateInput = document.querySelector("#study-date");
const planTitle = document.querySelector("#plan-title");
const planDate = document.querySelector("#plan-date");
const plannedMinutes = document.querySelector("#planned-minutes");
const actualMinutes = document.querySelector("#actual-minutes");
const completedCount = document.querySelector("#completed-count");
const planProgress = document.querySelector("#plan-progress");
const planStatus = document.querySelector("#plan-status");
const taskList = document.querySelector("#task-list");
const emptyTasks = document.querySelector("#empty-tasks");
const togglePause = document.querySelector("#toggle-pause");
const planJson = document.querySelector("#plan-json");
const importPlan = document.querySelector("#import-plan");
const importStatus = document.querySelector("#import-status");
const feedbackForm = document.querySelector("#feedback-form");
const feedbackStatus = document.querySelector("#feedback-status");
const reportText = document.querySelector("#report-text");
const copyReport = document.querySelector("#copy-report");
const globalStatus = document.querySelector("#global-status");
const wrongTotal = document.querySelector("#wrong-total");
const wrongSummary = document.querySelector("#wrong-summary");

let currentPlan = null;
let timerHandle = null;

const categoryLabels = {
  grammar: "语法",
  vocabulary: "单词",
  phrase: "词组",
  translation: "翻译",
};

function localDate() {
  const now = new Date();
  const offset = now.getTimezoneOffset();
  return new Date(now.getTime() - offset * 60 * 1000).toISOString().slice(0, 10);
}

function setStatus(element, message, error = false) {
  element.textContent = message;
  element.classList.toggle("error", error);
}

function formatMinutes(seconds) {
  const minutes = Math.floor(Number(seconds || 0) / 60);
  return `${minutes} 分钟`;
}

function taskSeconds(task) {
  let seconds = Number(task.elapsed_seconds || task.actual_seconds || 0);
  if (task.status === "active" && task.active_started_at) {
    const start = Date.parse(task.active_started_at);
    if (!Number.isNaN(start)) seconds += Math.max(0, Math.floor((Date.now() - start) / 1000));
  }
  return seconds;
}

function planSeconds() {
  return (currentPlan?.tasks || []).reduce((total, task) => total + taskSeconds(task), 0);
}

async function request(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || "请求失败");
  return payload;
}

async function loadDay() {
  try {
    currentPlan = await request(`/api/study/day?date=${encodeURIComponent(dateInput.value)}`);
    renderPlan();
    populateFeedback(currentPlan.report || {});
    await loadWrongSummary();
    setStatus(globalStatus, "");
  } catch (error) {
    setStatus(globalStatus, error.message, true);
  }
}

function renderPlan() {
  if (!currentPlan) return;
  const tasks = currentPlan.tasks || [];
  const planned = Number(currentPlan.effective_minutes || currentPlan.planned_minutes || 0);
  const actual = planSeconds();
  const completed = Number(currentPlan.completed_count || tasks.filter((task) => task.status === "completed").length);
  const progress = planned > 0 ? Math.min(100, Math.round((actual / 60 / planned) * 100)) : 0;

  planTitle.textContent = currentPlan.title || "今天的学习计划";
  planDate.textContent = currentPlan.date;
  plannedMinutes.textContent = planned;
  actualMinutes.textContent = Math.floor(actual / 60);
  completedCount.textContent = `${completed}/${tasks.length}`;
  planProgress.textContent = `${progress}%`;
  planStatus.textContent = currentPlan.paused ? "今日已暂停" : tasks.length ? "执行中" : "等待计划";
  planStatus.classList.toggle("paused", Boolean(currentPlan.paused));
  togglePause.textContent = currentPlan.paused ? "恢复今天" : "暂停今天";

  taskList.innerHTML = "";
  emptyTasks.hidden = tasks.length > 0;
  for (const task of tasks) taskList.appendChild(renderTask(task));
  reportText.value = currentPlan.report_text || "";
}

function renderTask(task) {
  const card = document.createElement("article");
  card.className = `task-card status-${task.status}`;
  const head = document.createElement("div");
  head.className = "task-head";
  const title = document.createElement("div");
  title.className = "task-title-wrap";
  const titleText = document.createElement("h3");
  titleText.textContent = task.title;
  const type = document.createElement("span");
  type.className = "task-type";
  type.textContent = task.type || "其他";
  title.append(titleText, type);
  const status = document.createElement("span");
  status.className = "task-status";
  status.textContent = taskStatusLabel(task.status);
  head.append(title, status);
  card.appendChild(head);

  const meta = document.createElement("div");
  meta.className = "task-meta";
  meta.innerHTML = `<span>计划 ${Number(task.planned_minutes || 0)} 分钟</span><span class="task-actual">实际 ${formatMinutes(taskSeconds(task))}</span><span>${task.priority || "normal"}</span>`;
  card.appendChild(meta);

  if (task.acceptance) {
    const acceptance = document.createElement("p");
    acceptance.className = "task-acceptance";
    acceptance.textContent = `完成标准：${task.acceptance}`;
    card.appendChild(acceptance);
  }
  if (task.carried_from) {
    const carried = document.createElement("p");
    carried.className = "task-note";
    carried.textContent = `来自 ${task.carried_from} 的顺延任务`;
    card.appendChild(carried);
  }

  const actions = document.createElement("div");
  actions.className = "task-actions";
  if (task.status === "active") actions.appendChild(taskButton("暂停", "pause", task.id, "button-secondary"));
  else if (task.status !== "completed" && task.status !== "skipped") actions.appendChild(taskButton("开始", "start", task.id, ""));
  if (task.status !== "completed" && task.status !== "skipped") {
    actions.appendChild(taskButton("完成", "complete", task.id, "button-secondary"));
    actions.appendChild(taskButton("顺延明天", "carryover", task.id, "button-quiet"));
  } else if (task.status === "completed" || task.status === "skipped") {
    actions.appendChild(taskButton("重置", "reset", task.id, "button-quiet"));
  }
  card.appendChild(actions);
  return card;
}

function taskButton(label, action, taskId, className) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className;
  button.textContent = label;
  button.addEventListener("click", () => taskAction(taskId, action));
  return button;
}

function taskStatusLabel(status) {
  return {
    pending: "未开始",
    active: "进行中",
    paused: "已暂停",
    completed: "已完成",
    skipped: "已跳过",
    deferred: "已顺延",
  }[status] || "未开始";
}

async function taskAction(taskId, action) {
  try {
    currentPlan = await request(`/api/study/day/${encodeURIComponent(dateInput.value)}/tasks/${encodeURIComponent(taskId)}/action`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    });
    renderPlan();
    setStatus(globalStatus, action === "carryover" ? "任务已顺延到明天。" : "任务状态已保存。");
  } catch (error) {
    setStatus(globalStatus, error.message, true);
  }
}

async function importDailyPlan() {
  try {
    const plan = JSON.parse(planJson.value);
    if (!Array.isArray(plan.tasks)) throw new Error("计划必须包含 tasks 数组");
    const payload = {
      date: plan.date || dateInput.value,
      effective_minutes: Number(plan.effective_minutes || 0),
      title: plan.title || "",
      paused: Boolean(plan.paused),
      source: "assistant",
      tasks: plan.tasks,
    };
    dateInput.value = payload.date;
    currentPlan = await request("/api/study/plan", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    renderPlan();
    populateFeedback(currentPlan.report || {});
    setStatus(importStatus, "计划已导入。", false);
    setStatus(globalStatus, "今日计划已更新。", false);
  } catch (error) {
    setStatus(importStatus, error.message, true);
  }
}

async function toggleDayPause() {
  try {
    currentPlan = await request(`/api/study/day/${encodeURIComponent(dateInput.value)}/state`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paused: !currentPlan.paused }),
    });
    renderPlan();
    setStatus(globalStatus, currentPlan.paused ? "今天的计划已暂停。" : "今天的计划已恢复。", false);
  } catch (error) {
    setStatus(globalStatus, error.message, true);
  }
}

function populateFeedback(report) {
  const value = (id, reportKey, fallback = "") => {
    const element = document.querySelector(`#${id}`);
    if (element) element.value = report[reportKey] ?? fallback;
  };
  value("feedback-planned", "planned_minutes", currentPlan?.effective_minutes || 0);
  value("feedback-actual", "actual_minutes", Math.floor(planSeconds() / 60));
  value("vocabulary-reviewed", "vocabulary_reviewed", 0);
  value("vocabulary-correct", "vocabulary_correct", 0);
  value("phrase-reviewed", "phrase_reviewed", 0);
  value("phrase-correct", "phrase_correct", 0);
  value("questions-completed", "questions_completed", 0);
  value("questions-correct", "questions_correct", 0);
  value("asked-questions", "asked_questions", "");
  value("unknown-items", "unknown_items", "");
  value("weak-points", "weak_points", "");
  value("next-available-minutes", "next_available_minutes", 0);
  value("mood", "mood", "");
  value("feedback-notes", "notes", "");
}

function numberValue(id) {
  return Number(document.querySelector(`#${id}`)?.value || 0);
}

function textValue(id) {
  return document.querySelector(`#${id}`)?.value.trim() || "";
}

async function saveFeedback(event) {
  event.preventDefault();
  try {
    currentPlan = await request(`/api/study/day/${encodeURIComponent(dateInput.value)}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        planned_minutes: numberValue("feedback-planned"),
        actual_minutes: numberValue("feedback-actual"),
        vocabulary_reviewed: numberValue("vocabulary-reviewed"),
        vocabulary_correct: numberValue("vocabulary-correct"),
        phrase_reviewed: numberValue("phrase-reviewed"),
        phrase_correct: numberValue("phrase-correct"),
        questions_completed: numberValue("questions-completed"),
        questions_correct: numberValue("questions-correct"),
        asked_questions: textValue("asked-questions"),
        unknown_items: textValue("unknown-items"),
        weak_points: textValue("weak-points"),
        mood: textValue("mood"),
        next_available_minutes: numberValue("next-available-minutes"),
        notes: textValue("feedback-notes"),
      }),
    });
    renderPlan();
    setStatus(feedbackStatus, "今日反馈已保存。", false);
    setStatus(globalStatus, "日报已生成，可以复制给聊天助手。", false);
  } catch (error) {
    setStatus(feedbackStatus, error.message, true);
  }
}

async function copyDailyReport() {
  const text = reportText.value.trim();
  if (!text) {
    setStatus(globalStatus, "请先保存今日反馈。", true);
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    setStatus(globalStatus, "日报已复制。", false);
  } catch {
    reportText.focus();
    reportText.select();
    setStatus(globalStatus, "请手动复制已选中的日报。", false);
  }
}

async function loadWrongSummary() {
  try {
    const payload = await request("/api/paper/wrong-book");
    const items = payload.items || [];
    wrongTotal.textContent = `${items.length}题`;
    wrongSummary.innerHTML = "";
    for (const [category, label] of Object.entries(categoryLabels)) {
      const count = items.filter((item) => (item.categories || []).includes(category)).length;
      const row = document.createElement("div");
      row.className = "wrong-summary-row";
      row.innerHTML = `<span>${label}</span><strong>${count}</strong>`;
      wrongSummary.appendChild(row);
    }
    const pending = items.filter((item) => !["reviewed", "mastered"].includes(item.status)).length;
    const pendingText = document.createElement("p");
    pendingText.className = "muted wrong-pending";
    pendingText.textContent = `待复习 ${pending} 题`;
    wrongSummary.appendChild(pendingText);
  } catch (error) {
    wrongSummary.textContent = error.message;
  }
}

dateInput.value = localDate();
dateInput.addEventListener("change", loadDay);
importPlan.addEventListener("click", importDailyPlan);
togglePause.addEventListener("click", toggleDayPause);
feedbackForm.addEventListener("submit", saveFeedback);
copyReport.addEventListener("click", copyDailyReport);
timerHandle = window.setInterval(() => {
  if (!currentPlan?.tasks?.some((task) => task.status === "active")) return;
  renderPlan();
}, 1000);

loadDay();
