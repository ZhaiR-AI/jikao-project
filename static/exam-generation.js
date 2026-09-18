const generationStages = { render: "准备 PDF", ocr: "文字识别", split: "识别试卷范围", extract: "题目整理", validate: "完整性检查", save: "保存试卷" };
const generationLabels = { queued: "排队中", running: "正在处理", completed: "生成完成", review: "生成完成，待检查", incomplete: "生成不完整", failed: "生成失败", interrupted: "生成中断" };
let activeGenerationJob = null;
let generationPollTimer = null;
let versionCheckBusy = false;
let paperQualityState = null;
let examLoading = true;

function generationElement(tag, text, className) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (className) el.className = className;
  return el;
}

async function generationRequest(url, options = {}) {
  const response = await fetch(url, { cache: "no-store", ...options });
  const payload = await response.json();
  if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "请求未完成，请稍后重试。");
  return payload;
}

function generationButton(text, action) {
  const button = generationElement("button", text);
  button.type = "button";
  button.addEventListener("click", async () => {
    button.disabled = true;
    try { await action(); }
    catch (error) { setStatus(error.message); }
    finally { button.disabled = false; }
  });
  return button;
}

function rememberGenerationJob(id) {
  try { localStorage.setItem("exam-generation-job:v1", id); } catch { /* Server history remains available. */ }
}

async function startPaperGeneration(event) {
  event.preventDefault();
  if (!fileInput.files[0]) { setStatus("请先选择一份 PDF。"); return; }
  if (activeGenerationJob && ["queued", "running"].includes(activeGenerationJob.status)) return;
  generateBtn.disabled = true;
  const panel = document.querySelector("#generation-panel");
  panel.hidden = false;
  document.querySelector("#generation-title").textContent = fileInput.files[0].name;
  document.querySelector("#generation-state").textContent = "正在上传文件；上传完成后显示逐步处理进度。";
  document.querySelector("#generation-steps").replaceChildren();
  document.querySelector("#generation-actions").replaceChildren();
  try {
    if (!await ensureExamDraftSaved()) throw new Error("当前作答尚未保存，已保留在页面中，请保存成功后再上传。");
    const form = new FormData();
    form.append("file", fileInput.files[0]);
    const params = new URLSearchParams({ ocr_concurrency: "3" });
    if (maxPages.value.trim()) params.set("max_pages", maxPages.value.trim());
    const job = await generationRequest(`/api/paper/generation-jobs?${params}`, { method: "POST", body: form });
    watchGenerationJob(job);
  } catch (error) {
    document.querySelector("#generation-state").textContent = `上传未完成：${error.message}`;
    generateBtn.disabled = false;
  }
}

function watchGenerationJob(job) {
  window.clearTimeout(generationPollTimer);
  activeGenerationJob = job;
  rememberGenerationJob(job.id);
  renderGenerationJob(job);
  if (["running", "queued"].includes(job.status)) generationPollTimer = window.setTimeout(pollGenerationJob, 1500);
}

async function pollGenerationJob() {
  const id = activeGenerationJob?.id;
  if (!id) return;
  try {
    const job = await generationRequest(`/api/paper/generation-jobs/${encodeURIComponent(id)}`);
    if (activeGenerationJob?.id !== id) return;
    watchGenerationJob(job);
    if (!["running", "queued"].includes(job.status)) {
      await refreshGenerationHistory();
      if (!currentPaper || currentPaper.type === "paper_collection") await loadCollectionsHome();
      await checkExamVersion();
    }
  } catch (error) {
    if (activeGenerationJob?.id !== id) return;
    document.querySelector("#generation-state").textContent = `进度暂时无法读取：${error.message}。正在重新连接，请勿重复上传。`;
    generationPollTimer = window.setTimeout(pollGenerationJob, 4000);
  }
}

function renderGenerationJob(job) {
  document.querySelector("#generation-panel").hidden = false;
  document.querySelector("#generation-title").textContent = `${job.repair_of ? "修复试卷" : "生成试卷"}：${job.original_name}`;
  document.querySelector("#generation-state").textContent = `${generationLabels[job.status] || job.status}${job.error ? `：${job.error}` : ""}`;
  const steps = document.querySelector("#generation-steps");
  steps.replaceChildren();
  for (const [stage, label] of Object.entries(generationStages)) {
    const progress = job.progress?.[stage];
    const state = progress ? (progress.total !== undefined ? `${progress.done || 0} / ${progress.total}` : stage === job.stage ? (job.status === "running" ? "进行中" : "未完成") : "已完成") : job.repair_of && ["render", "ocr", "split"].includes(stage) ? "复用已保存结果" : "尚未开始";
    steps.appendChild(generationElement("li", `${label}：${state}${stage === "extract" && progress?.total === 0 ? "（标准结构直接整理）" : ""}`));
  }
  const actions = document.querySelector("#generation-actions");
  actions.replaceChildren();
  if (["failed", "interrupted"].includes(job.status)) {
    actions.appendChild(generationButton("重试未完成部分", async () => {
      watchGenerationJob(await generationRequest(`/api/paper/generation-jobs/${job.id}/retry`, { method: "POST" }));
    }));
  }
  for (const paper of job.result?.papers || []) {
    const card = generationElement("div", undefined, "generation-result");
    card.appendChild(generationElement("strong", paper.title));
    card.appendChild(generationElement("p", `${paper.quality.label} · ${paper.question_count} 个作答项`));
    const link = generationElement("a", paper.quality.status === "ready" ? "进入考试" : "预览并检查问题");
    link.href = paper.paper_url;
    card.appendChild(link);
    actions.appendChild(card);
  }
  generateBtn.disabled = ["running", "queued"].includes(job.status);
}

async function refreshGenerationHistory() {
  const payload = await generationRequest("/api/paper/generation-jobs/recent");
  const root = document.querySelector("#generation-history");
  root.replaceChildren();
  for (const job of payload.jobs || []) {
    root.appendChild(generationButton(`${job.original_name} · ${generationLabels[job.status]} · ${new Date(job.created_at).toLocaleString()}`, () => watchGenerationJob(job)));
  }
  return payload.jobs || [];
}

async function showPaperQuality(paper) {
  const root = document.querySelector("#paper-quality");
  root.replaceChildren();
  root.hidden = true;
  paperQualityState = null;
  if (!paper || paper.type === "paper_collection") return;
  const paperId = paper.id;
  try {
    const quality = await generationRequest(`/api/paper/${encodeURIComponent(paperId)}/quality`);
    if (currentPaper?.id !== paperId || !Array.isArray(quality.issues)) return;
    paperQualityState = quality;
    root.hidden = false;
    root.dataset.quality = quality.status;
    root.appendChild(generationElement("strong", quality.label));
    root.appendChild(generationElement("p", quality.note));
    if (paper.repaired_from) {
      const original = generationElement("a", "查看原卷与原作答记录");
      original.href = `/exam/${encodeURIComponent(paper.repaired_from)}`;
      root.appendChild(original);
    }
    const details = generationElement("details");
    details.open = quality.status !== "ready";
    details.appendChild(generationElement("summary", `检查详情（${quality.issues.length} 项）`));
    for (const issue of quality.issues) {
      const row = generationElement("div", undefined, "quality-issue");
      row.appendChild(generationElement("span", `${issue.severity === "error" ? "需修复" : "待核对"}：${issue.message}`));
      row.appendChild(generationButton(issue.pages.length ? `查看原文第 ${issue.pages.join("、")} 页` : "查看原文", () => showExamSource(paperId, issue.pages)));
      details.appendChild(row);
    }
    root.appendChild(details);
    const actions = generationElement("div", undefined, "generation-actions");
    actions.appendChild(generationButton("查看问题与原文", () => showExamSource(paperId)));
    if (quality.issues.length) actions.appendChild(generationButton("重新整理异常部分", async () => {
      if (!await ensureExamDraftSaved()) throw new Error("当前作答尚未保存，保存成功后再修复。");
      watchGenerationJob(await generationRequest(`/api/paper/${encodeURIComponent(paperId)}/repair`, { method: "POST" }));
      document.querySelector("#generation-panel").scrollIntoView({ block: "start" });
    }));
    root.appendChild(actions);
  } catch (error) {
    if (currentPaper?.id !== paperId) return;
    root.hidden = false;
    root.appendChild(generationElement("p", `检查结果暂时无法读取：${error.message}`));
    root.appendChild(generationButton("重试检查", () => showPaperQuality(paper)));
  }
}

async function showExamSource(paperId, selectedPages = []) {
  const source = await generationRequest(`/api/paper/${encodeURIComponent(paperId)}/source`);
  const content = document.querySelector("#source-content");
  content.replaceChildren();
  if (source.pdf_url) {
    const link = generationElement("a", "打开原始 PDF");
    link.href = source.pdf_url + (selectedPages[0] ? `#page=${selectedPages[0]}` : "");
    link.target = "_blank";
    link.rel = "noopener";
    content.appendChild(link);
  }
  for (const page of source.pages || []) {
    if (selectedPages.length && !selectedPages.includes(page.page)) continue;
    content.append(generationElement("h3", `原文第 ${page.page} 页`), generationElement("pre", page.text));
  }
  if (!source.pages?.length) content.appendChild(generationElement("p", "没有保存的识别文字，请重新上传原始 PDF。"));
  document.querySelector("#source-dialog").showModal();
}

async function ensureExamDraftSaved() {
  if (!currentPaper || currentPaper.type === "paper_collection" || draftRevision <= savedDraftRevision) return true;
  saveLocalDraftBackup(collectDraftPayload());
  if (draftSavePromise) await draftSavePromise;
  while (draftRevision > savedDraftRevision) {
    if (!await saveDraft(true, collectDraftPayload())) return false;
  }
  return true;
}

async function checkExamVersion() {
  if (versionCheckBusy || examLoading) return;
  versionCheckBusy = true;
  try {
    if (currentPaper && currentPaper.type !== "paper_collection") {
      const stored = await generationRequest(`/api/paper/${encodeURIComponent(currentPaper.id)}`);
      if (stored.superseded_by && stored.superseded_by !== currentPaper.id) {
        const notice = document.querySelector("#version-notice");
        notice.hidden = false;
        notice.replaceChildren(generationElement("p", "这份旧卷已被修正，旧作答记录会保留。请进入修正后的完整试卷。"));
        notice.appendChild(generationButton("保存当前作答并打开修正版", async () => {
          if (submitPaper.disabled || newRecord.disabled) throw new Error("请等待当前操作完成。");
          if (!await ensureExamDraftSaved()) throw new Error("当前作答尚未保存，请保存后再切换。");
          location.assign(`/exam/${encodeURIComponent(stored.superseded_by)}`);
        }));
        return;
      }
    }
    const version = document.querySelector('meta[name="exam-version"]')?.content;
    const latest = await generationRequest("/api/paper/ui/version");
    if (!latest.version || latest.version === version) return;
    const operationBusy = currentPaper && currentPaper.type !== "paper_collection" && (submitPaper.disabled || newRecord.disabled);
    const hadUnsaved = draftRevision > savedDraftRevision;
    let saved = true;
    if (hadUnsaved && !operationBusy) saved = Boolean(await saveDraft(false, collectDraftPayload()));
    const notice = document.querySelector("#version-notice");
    notice.hidden = false;
    notice.replaceChildren(generationElement("p", saved ? "考试页面已更新，作答会保留。可加载新版界面。" : "考试页面已更新，但当前作答保存失败。答案已保留在本页，保存成功后再更新。"));
    notice.appendChild(generationButton("保存并更新页面", async () => {
      if (currentPaper && (submitPaper.disabled || newRecord.disabled)) throw new Error("当前操作仍在进行，请完成后再更新页面。");
      setExamEditingDisabled(true);
      try {
        if (!await ensureExamDraftSaved()) throw new Error("保存失败，当前答案已保留，暂不刷新页面。请稍后重试。");
        location.reload();
      } finally { setExamEditingDisabled(false); }
    }));
    const generating = activeGenerationJob && ["queued", "running"].includes(activeGenerationJob.status);
    if (!generating && !operationBusy && !hadUnsaved && draftRevision <= savedDraftRevision && !draftSaveInProgress) location.reload();
  } catch { /* Retry on focus/interval; never discard a draft because a version lookup failed. */ }
  finally { versionCheckBusy = false; }
}

function checkRenderedExamNavigation() {
  if (!currentPaper || currentPaper.type === "paper_collection") return;
  const ids = flattenQuestions(currentPaper).map(q => String(q.id));
  const buttons = [...questionCard.querySelectorAll("[data-goto]")];
  if (new Set(ids).size !== ids.length || buttons.length !== ids.length || buttons.some(b => !document.getElementById(`question-${b.dataset.goto}`))) {
    const root = document.querySelector("#paper-quality");
    root.hidden = false;
    root.appendChild(generationElement("p", "题目与答题卡定位不一致，请查看检查详情并重新整理后作答。"));
    submitPaper.disabled = true;
  }
}

async function initExamGeneration() {
  examLoading = false;
  document.querySelector("#source-close").addEventListener("click", () => document.querySelector("#source-dialog").close());
  try {
    const jobs = await refreshGenerationHistory();
    let preferred;
    try { preferred = localStorage.getItem("exam-generation-job:v1"); } catch { /* History works without local storage. */ }
    const selected = jobs.find(j => j.id === preferred) || jobs.find(j => ["running", "queued", "failed", "interrupted"].includes(j.status));
    if (selected) watchGenerationJob(selected);
    else if (jobs.length) document.querySelector("#generation-panel").hidden = false;
  } catch { /* Generation form remains usable when the history request fails. */ }
  await checkExamVersion();
  window.addEventListener("focus", checkExamVersion);
  window.setInterval(checkExamVersion, 60000);
  document.addEventListener("click", async (event) => {
    const link = event.target.closest('a[href^="/exam/"]');
    if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.button || link.target === "_blank") return;
    event.preventDefault();
    if (currentPaper && (submitPaper.disabled || newRecord.disabled)) { setStatus("当前操作仍在进行，请稍后进入其他卷子。"); return; }
    if (!await ensureExamDraftSaved()) { setStatus("保存失败，已保留当前页面，请重试保存后再切换卷子。"); return; }
    location.assign(link.href);
  });
}
