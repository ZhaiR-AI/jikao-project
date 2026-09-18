// The old single draft is preserved and imported once for each question type.
const legacyPracticeData = structuredClone(practiceData);
const practiceRecordStorageKey = "wrong-book-records:v1";
let practiceRecordBackups = { active: {}, records: {} };
let activePracticeRecord = null;
let practiceRecordList = [];
let practiceRecordBusy = false;
let practiceRecordRevision = 0;
let practiceRecordSavedRevision = 0;
let practiceRecordSaveTimer = null;
let practiceRecordSavePromise = null;
let practiceRecordSaveError = false;
try {
  const saved = JSON.parse(localStorage.getItem(practiceRecordStorageKey) || "null");
  if (saved?.active && saved?.records) practiceRecordBackups = saved;
} catch { /* Server records can still be restored if the local backup is unavailable. */ }

function writePracticeRecordBackup(dirty) {
  if (activePracticeRecord) {
    practiceRecordBackups.active[activePracticeRecord.exam_type] = activePracticeRecord.record_id;
    practiceRecordBackups.records[activePracticeRecord.record_id] = { draft: practiceData, dirty };
  }
  try { localStorage.setItem(practiceRecordStorageKey, JSON.stringify(practiceRecordBackups)); }
  catch { document.querySelector("#practice-record-save-state").textContent = "本地备份不可用，请等待服务器保存。"; }
}

function persistPracticeRecord() {
  if (!activePracticeRecord) return;
  activePracticeRecord.draft = practiceData;
  practiceRecordRevision += 1;
  writePracticeRecordBackup(true);
  window.clearTimeout(practiceRecordSaveTimer);
  practiceRecordSaveTimer = window.setTimeout(() => flushPracticeRecord().catch(() => {}), 800);
  renderPracticeRecordPanel();
}

async function flushPracticeRecord() {
  window.clearTimeout(practiceRecordSaveTimer);
  if (practiceRecordSavePromise) await practiceRecordSavePromise;
  while (activePracticeRecord && practiceRecordRevision > practiceRecordSavedRevision) {
    const recordId = activePracticeRecord.record_id;
    const revision = practiceRecordRevision;
    const draft = structuredClone(practiceData);
    practiceRecordSavePromise = request(`/api/paper/wrong-book/records/${encodeURIComponent(recordId)}`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ draft }),
    });
    try {
      const saved = await practiceRecordSavePromise;
      if (activePracticeRecord.record_id === recordId) {
        activePracticeRecord = { ...saved, draft: practiceData };
        practiceRecordSavedRevision = revision;
        practiceRecordSaveError = false;
        practiceRecordList = practiceRecordList.map((record) => record.record_id === recordId ? saved : record);
        writePracticeRecordBackup(practiceRecordRevision > revision);
      }
    } catch (error) {
      practiceRecordSaveError = true;
      document.querySelector("#practice-record-save-state").textContent = "服务器保存失败，本地备份已保留；请稍后重试。";
      throw error;
    } finally {
      practiceRecordSavePromise = null;
    }
  }
  renderPracticeRecordPanel();
}

function activatePracticeRecord(record) {
  practiceRecordBackups.initialized ??= {};
  practiceRecordBackups.initialized[record.exam_type] = true;
  practiceRecordSaveError = false;
  activePracticeRecord = record;
  const backup = practiceRecordBackups.records[record.record_id];
  practiceData = structuredClone(backup?.dirty ? backup.draft : record.draft || {});
  activePracticeRecord.draft = practiceData;
  practiceRecordRevision = backup?.dirty ? 1 : 0;
  practiceRecordSavedRevision = 0;
  writePracticeRecordBackup(Boolean(backup?.dirty));
  if (backup?.dirty) practiceRecordSaveTimer = window.setTimeout(() => flushPracticeRecord().catch(() => {}), 800);
}

async function loadPracticeRecordsForType() {
  const type = state.examType;
  const payload = await request(`/api/paper/wrong-book/records?exam_type=${encodeURIComponent(type)}`);
  practiceRecordList = payload.records || [];
  const preferred = practiceRecordBackups.active[type];
  const selected = practiceRecordList.find((record) => record.record_id === preferred) || practiceRecordList[0];
  if (selected) {
    activatePracticeRecord(await request(`/api/paper/wrong-book/records/${encodeURIComponent(selected.record_id)}`));
  } else {
    const ids = state.items.filter((item) => item.exam_type === type).map((item) => item.id);
    if (!ids.length || practiceRecordBackups.initialized?.[type]) {
      activePracticeRecord = null;
      practiceData = {};
      practiceRecordRevision = practiceRecordSavedRevision = 0;
      practiceRecordSaveError = false;
      return;
    }
    const draft = Object.fromEntries(ids.filter((id) => legacyPracticeData[id]).map((id) => [id, legacyPracticeData[id]]));
    const record = await request("/api/paper/wrong-book/records", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ exam_type: type, entry_ids: ids, draft }),
    });
    practiceRecordList = [record];
    activatePracticeRecord(record);
  }
}

async function runPracticeRecordTransition(action) {
  if (practiceRecordBusy || practiceSubmitting) return;
  practiceRecordBusy = true;
  const controls = [...document.querySelectorAll("button, input, textarea")];
  const disabled = controls.map((control) => control.disabled);
  controls.forEach((control) => { control.disabled = true; });
  try { await action(); }
  catch (error) { showMessage(`记录操作未完成：${error.message}。当前作答仍保留。`, true); }
  finally {
    practiceRecordBusy = false;
    controls.forEach((control, index) => { if (control.isConnected) control.disabled = disabled[index]; });
    renderPracticeRecordPanel();
  }
}

function resetPracticeRecordFilters() {
  state.status = "all";
  state.category = "all";
  state.query = "";
  searchInput.value = "";
  document.querySelectorAll("[data-status]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.status === "all")));
  document.querySelectorAll("[data-category]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.category === "all")));
}

function practiceRecordDescription(record) {
  const draft = record.record_id === activePracticeRecord?.record_id ? practiceData : record.draft;
  const entries = draft ? Object.values(draft) : null;
  const answered = entries ? entries.filter((entry) => hasAnswer(entry.answer)).length : record.answered_count || 0;
  const correct = entries ? entries.filter((entry) => entry.result?.is_correct === true).length : record.correct_count || 0;
  const wrong = entries ? entries.filter((entry) => entry.result?.is_correct === false).length : record.wrong_count || 0;
  return `${new Date(record.created_at).toLocaleString("zh-CN", { hour12: false })} · 已答 ${answered}/${record.entry_ids.length} 题${correct + wrong ? ` · 对 ${correct} / 错 ${wrong}` : ""}`;
}

function renderPracticeRecordPanel() {
  const label = document.querySelector("#practice-current-record");
  label.textContent = activePracticeRecord ? `${examTypeLabels[activePracticeRecord.exam_type]} · ${practiceRecordDescription(activePracticeRecord)}` : "当前类型暂无做题记录";
  document.querySelector("#practice-new-record").disabled = practiceRecordBusy || practiceSubmitting || !filteredItems(true).length;
  document.querySelector("#practice-history-toggle").disabled = practiceRecordBusy || practiceSubmitting || !practiceRecordList.length;
  if (!activePracticeRecord) {
    document.querySelector("#practice-record-save-state").textContent = "点击“新建记录”开始答题。";
    document.querySelectorAll("#wrong-list input, #wrong-list textarea, #wrong-list button").forEach((control) => { control.disabled = true; });
  }
  document.querySelector("#submit-practice").disabled = !activePracticeRecord || practiceRecordBusy || practiceSubmitting || !practiceVisibleIds.length;
  if (activePracticeRecord && !practiceRecordSaveError) {
    document.querySelector("#practice-record-save-state").textContent = practiceRecordRevision > practiceRecordSavedRevision ? "正在自动保存…" : "已保存";
  }
  const root = document.querySelector("#practice-record-history");
  root.replaceChildren();
  const records = [...practiceRecordList];
  if (activePracticeRecord && !records.some((record) => record.record_id === activePracticeRecord.record_id)) records.unshift(activePracticeRecord);
  for (const record of records) {
    const row = createElement("div", "practice-history-row");
    const button = createElement("button", "practice-history-entry", practiceRecordDescription(record));
    button.type = "button";
    button.dataset.recordId = record.record_id;
    button.classList.toggle("active", record.record_id === activePracticeRecord?.record_id);
    button.disabled = practiceRecordBusy || practiceSubmitting;
    button.addEventListener("click", () => runPracticeRecordTransition(async () => {
      await flushPracticeRecord();
      const selected = await request(`/api/paper/wrong-book/records/${encodeURIComponent(record.record_id)}`);
      activatePracticeRecord(selected);
      resetPracticeRecordFilters();
      renderList();
      showMessage("已切换做题记录，可以继续作答或查看本轮结果。");
    }));
    const remove = createElement("button", "card-action danger practice-record-delete", "删除记录");
    remove.type = "button";
    remove.dataset.deleteRecordId = record.record_id;
    remove.setAttribute("aria-label", `删除记录：${practiceRecordDescription(record)}`);
    remove.disabled = practiceRecordBusy || practiceSubmitting;
    remove.addEventListener("click", () => {
      if (!window.confirm(`确定删除这条做题记录吗？\n${practiceRecordDescription(record)}\n该记录的作答和判定将被删除，已保存的题目、笔记和分类会保留。`)) return;
      runPracticeRecordTransition(async () => {
        await flushPracticeRecord();
        const deletingActive = record.record_id === activePracticeRecord?.record_id;
        const remaining = practiceRecordList.filter((entry) => entry.record_id !== record.record_id);
        // Resolve the next record before deleting, so a failed read leaves this record intact.
        const next = deletingActive && remaining.length
          ? await request(`/api/paper/wrong-book/records/${encodeURIComponent(remaining[0].record_id)}`) : null;
        await request(`/api/paper/wrong-book/records/${encodeURIComponent(record.record_id)}`, { method: "DELETE" });
        practiceRecordList = remaining;
        delete practiceRecordBackups.records[record.record_id];
        if (deletingActive) {
          window.clearTimeout(practiceRecordSaveTimer);
          delete practiceRecordBackups.active[record.exam_type];
          activePracticeRecord = null;
          practiceData = {};
          practiceRecordRevision = practiceRecordSavedRevision = 0;
          practiceRecordSaveError = false;
          if (next) activatePracticeRecord(next);
          resetPracticeRecordFilters();
          renderList();
        }
        writePracticeRecordBackup(practiceRecordRevision > practiceRecordSavedRevision);
        showMessage(activePracticeRecord ? "做题记录已删除。" : "做题记录已删除，点击“新建记录”可重新答题。");
      });
    });
    row.append(button, remove);
    root.appendChild(row);
  }
}

document.querySelector("#practice-history-toggle").addEventListener("click", () => {
  const history = document.querySelector("#practice-record-history");
  history.hidden = !history.hidden;
  document.querySelector("#practice-history-toggle").setAttribute("aria-expanded", String(!history.hidden));
});

document.querySelector("#practice-new-record").addEventListener("click", () => runPracticeRecordTransition(async () => {
  await flushPracticeRecord();
  const ids = filteredItems(true).map((item) => item.id);
  const draft = {};
  for (const id of ids) {
    const item = state.items.find((item) => item.id === id);
    const previous = practiceData[id] || {};
    draft[id] = { answer: "", doubt: false, revealed: false,
      previousAnswer: hasAnswer(previous.answer) ? previous.answer : previous.previousAnswer ?? item?.last_review_answer ?? item?.student_answer ?? "" };
    if (previous.note !== undefined) draft[id].note = previous.note;
  }
  const record = await request("/api/paper/wrong-book/records", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ exam_type: state.examType, entry_ids: ids, draft }),
  });
  practiceRecordList.unshift(record);
  activatePracticeRecord(record);
  resetPracticeRecordFilters();
  renderList();
  showMessage("已新建空白做题记录，可以重新答题；上一轮已保存在历史记录中。");
}));

window.addEventListener("pagehide", () => {
  writePracticeRecordBackup(practiceRecordRevision > practiceRecordSavedRevision);
});
