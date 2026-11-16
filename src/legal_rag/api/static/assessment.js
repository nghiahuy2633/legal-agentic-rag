"use strict";

(() => {
  const byId = id => document.getElementById(id);
  const panel = byId("assessment-panel");
  const reportBox = byId("assessment-report");
  const download = byId("assessment-download");
  let prepared = null, currentReport = null, currentGroup = null, nextQuestion = null;
  let busy = false, isStale = false, started = false, needsPrepare = false;
  let groupAnswers = new Map();
  let verificationURL = null;
  let stage = "facts";
  let retryAction = null;
  const labels = {
    ...valueLabels, cao: "Cao", trung_binh: "Trung bình", thap: "Thấp",
    chua_phan_loai: "Chưa phân loại", van_ban: "Văn bản", am_thanh: "Âm thanh",
    hinh_anh: "Hình ảnh", video: "Video"
  };
  const statuses = {da: "Đã đáp ứng", chua: "Chưa đáp ứng", chua_ro: "Cần xác minh"};
  const groupLabels = {
    phan_loai_thong_bao: "phân loại và thông báo", minh_bach: "minh bạch", du_lieu: "dữ liệu",
    khu_vuc_cong: "khu vực công", quan_tri: "quản trị", su_co: "sự cố",
    quan_ly_rui_ro_cao: "quản lý rủi ro cao", danh_gia_phu_hop: "đánh giá sự phù hợp",
    nuoc_ngoai: "nhà cung cấp nước ngoài", chuyen_tiep: "chuyển tiếp"
  };
  const add = (tag, text, parent, className) => {
    const node = element(tag, text, parent);
    if (className) node.className = className;
    return node;
  };
  function button(parent, label, action, className = "quiet") {
    const node = add("button", label, parent, className); node.type = "button";
    node.addEventListener("click", action); return node;
  }
  function setBusy(value) {
    busy = value; assessmentBusy = value; updateChatControls();
    panel.setAttribute("aria-busy", String(value));
    panel.querySelectorAll("button, input, select, textarea").forEach(control => {
      control.disabled = value || (isStale && control.dataset.check === "true");
    });
    byId("group-submit").disabled = value || !currentGroup;
    byId("group-unknown").disabled = value || !currentGroup;
    byId("assessment-status").textContent = value ? "Đang đối chiếu thông tin. Có thể mất hơn một phút…" : "";
    download.hidden = value || !currentReport;
  }
  async function api(operation, payload) {
    const get = payload === undefined;
    const url = `/api/assess/${operation}` + (get ? `?session_id=${encodeURIComponent(sessionId)}` : "");
    const response = await aiFetch(url, get ? {} : {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({session_id: sessionId, ...payload})
    });
    const data = await response.json();
    if (!response.ok) {
      const detail = Array.isArray(data.detail) ? data.detail.map(e => e.msg).join(" ") : data.detail;
      const error = new Error(detail || "Không xử lý được đánh giá. Vui lòng thử lại.");
      error.status = response.status; throw error;
    }
    return data;
  }
  async function request(action) {
    if (busy || chatBusy) return;
    setBusy(true); byId("assessment-error").textContent = "";
    byId("retry-assessment").hidden = true;
    try { await action(); }
    catch (error) {
      if (error.status === 409) markStale(true);
      byId("assessment-error").textContent = error instanceof TypeError
        ? "Mất kết nối với máy chủ. Nội dung đã được giữ lại; vui lòng thử lại."
        : error.message;
      retryAction = action; byId("retry-assessment").hidden = false;
    } finally { setBusy(false); }
  }
  byId("retry-assessment").addEventListener("click", () => { if (retryAction) request(retryAction); });
  function markStale(value) {
    isStale = Boolean(value); byId("stale-notice").hidden = !isStale;
    const title = byId("stale-notice").querySelector("strong");
    if (title) title.textContent = "Sản phẩm đã có thông tin mới";
  }
  function openPanel(value) {
    panel.hidden = !value;
    byId("chat-panel").hidden = value;
    byId("workspace").classList.toggle("assessment-open", value);
    byId("open-assessment").setAttribute("aria-expanded", String(value));
    if (!value) byId("open-assessment").focus();
  }
  function jump(field) {
    const row = byId(`fact-${field}`); if (!row) return;
    openPanel(true);
    setStage("facts"); byId("facts-editor").open = true;
    for (let node = row.parentElement; node; node = node.parentElement) {
      if (node.tagName === "DETAILS") node.open = true;
    }
    row.scrollIntoView({block: "center"}); row.querySelector("input, select")?.focus({preventScroll: true});
  }
  function setStage(name) {
    stage = name;
    for (const step of ["facts", "groups", "report"]) byId(`${step}-stage`).hidden = step !== name;
    document.querySelectorAll?.("[data-step]").forEach(control => {
      if (control.dataset.step === name) control.setAttribute("aria-current", "step");
      else control.removeAttribute("aria-current");
    });
    if (!panel.hidden) panel.scrollIntoView({block: "start"});
  }
  for (const control of document.querySelectorAll?.("[data-step]") || []) {
    control.addEventListener("click", () => setStage(control.dataset.step));
  }
  byId("continue-groups").addEventListener("click", () => setStage("groups"));
  byId("view-report").addEventListener("click", () => setStage("report"));
  byId("finish-assessment").addEventListener("click", () => setStage("report"));
  async function loadState() {
    const data = await api("state"); started = true;
    showFacts(data); currentReport = data.report; markStale(data.stale);
    nextQuestion = await api("next"); showGroup(nextQuestion); showReport();
    if (isStale && !nextQuestion.group && prepared.groups.length) {
      showGroup({...prepared.groups[0], progress: nextQuestion.progress}, true);
    }
  }
  async function prepare() {
    const data = await api("start", {});
    started = true; needsPrepare = false; showFacts(data); markStale(data.stale);
    await loadState();
  }
  function updateFact(name, value) {
    request(async () => {
      const data = await api("facts", {facts: {[name]: value}});
      showFacts(data); markStale(data.stale);
      byId("assessment-error").textContent = (data.errors || []).join(" ");
      nextQuestion = await api("next"); showGroup(nextQuestion); showReport();
      byId(`fact-${name}`)?.querySelector("input, select")?.focus();
    });
  }
  function select(parent, choices, value, onChange, label) {
    const control = add("select", undefined, parent); control.setAttribute("aria-label", label);
    for (const [key, text] of choices) { const option = add("option", text, control); option.value = key; }
    control.value = value; control.addEventListener("change", () => onChange(control.value)); return control;
  }
  const FACT_VISIBILITY_RULES = {
    public_decision_use: facts => facts.is_public_sector !== false,
    requires_conformity_certification: facts => facts.risk_level == null || facts.risk_level === "cao",
    modified_by_deployer: facts => facts.roles == null || facts.roles.includes("ben_trien_khai"),
    content_types: facts => facts.generates_content !== false,
    simulates_real_person: facts => facts.generates_content !== false,
    public_distribution: facts => facts.generates_content !== false,
    content_may_mislead: facts => facts.generates_content !== false,
    uses_third_party_model: facts => facts.roles == null || facts.roles.includes("nha_cung_cap"),
    is_foreign_provider: facts => facts.roles == null || facts.roles.includes("nha_cung_cap"),
    uses_personal_data: () => false
  };

  function showFacts(data) {
    prepared = data;
    const summary = byId("product-summary"); summary.replaceChildren();
    for (const name of ["roles", "risk_level", "sectors", "generates_content"]) {
      if (!(name in data.facts)) continue;
      add("dt", data.labels[name] || name, summary);
      const value = data.facts[name];
      add("dd", value == null ? "Cần bổ sung" : Array.isArray(value)
        ? value.map(item => labels[item] || item).join(", ") || "Không có"
        : typeof value === "boolean" ? value ? "Có" : "Không" : labels[value] || value, summary);
    }
    const questions = byId("fact-questions"); questions.replaceChildren();
    if ((data.questions || []).length) {
      add("h3", "Cần làm rõ", questions);
      for (const question of (data.questions || [])) {
        const button = add("button", question.question, questions);
        button.type = "button"; button.className = "question-link";
        button.addEventListener("click", () => jump(question.field));
      }
    }
    const missing = ["roles", "risk_level"].filter(name => data.facts[name] == null);
    byId("facts-ready").textContent = data.ready ? "Đủ thông tin để đánh giá"
      : `Còn thiếu: ${missing.map(name => data.labels[name]).join(", ")}`;
    const table = byId("facts-table"); table.replaceChildren();
    const required = add("section", undefined, table);
    add("h3", "Bắt buộc", required);
    const extra = add("details", undefined, table);
    add("summary", "Thông tin thêm", extra);
    const all = add("details", undefined, table);
    add("summary", "Hiện tất cả", all);
    const asked = new Set((data.questions || []).map(question => question.field));
    for (const [name, spec] of Object.entries(data.fields)) {
      const relevant = asked.has(name) || (FACT_VISIBILITY_RULES[name]?.(data.facts) ?? true);
      const container = ["roles", "risk_level"].includes(name) ? required : relevant ? extra : all;
      const row = add("div", undefined, container); row.id = `fact-${name}`; row.className = "fact-row";
      const title = data.labels[name];
      add("strong", title, row);
      const controls = add("div", undefined, row);
      const value = data.facts[name];
      if (spec.type === "list") {
        const group = add("fieldset", undefined, controls);
        add("legend", `Chọn ${title}`, group);
        const inputs = [];
        for (const option of spec.values) {
          const label = add("label", undefined, group);
          const checkbox = add("input", undefined, label);
          checkbox.type = "checkbox"; checkbox.value = option; checkbox.checked = (value || []).includes(option);
          add("span", labels[option] || option, label);
          inputs.push(checkbox);
          checkbox.addEventListener("change", () => updateFact(name, inputs.filter(c => c.checked).map(c => c.value)));
        }
        add("small", value === null ? "Chưa biết" : value.length ? "Đã khai" : "Đã biết: không có", controls);
        const none = add("button", "Không có", controls); none.type = "button";
        none.addEventListener("click", () => updateFact(name, []));
        const unknown = add("button", "Chưa biết", controls); unknown.type = "button";
        unknown.addEventListener("click", () => updateFact(name, null));
      } else if (spec.type === "date") {
        const control = add("input", undefined, controls);
        control.type = "date"; control.value = value || ""; control.setAttribute("aria-label", title);
        control.addEventListener("change", () => updateFact(name, control.value || null));
      } else if (spec.type === "bool") {
        select(controls, [["", "Chưa biết"], ["true", "Có"], ["false", "Không"]],
          value == null ? "" : String(value), v => updateFact(name, v === "" ? null : v === "true"), title);
      } else {
        select(controls, [["", "Chưa biết"], ...spec.values.map(v => [v, labels[v] || v])],
          value || "", v => updateFact(name, v || null), title);
      }
      if (data.evidence[name]) add("small", `Bằng chứng: “${data.evidence[name]}”`, row);
    }
    if (busy) panel.querySelectorAll("button, input, select, textarea").forEach(control => { control.disabled = true; });
  }


  function groupName(group) {
    const spec = (prepared?.groups || []).find(item => item.group === group);
    return groupLabels[group] || spec?.obligations?.[0]?.obligation || "nhóm nghĩa vụ này";
  }
  function showGroup(data, editing = false) {
    currentGroup = data.group;
    const progress = data.progress || nextQuestion?.progress || {answered: 0, total: 0};
    byId("group-progress").textContent = `Đã hỏi ${progress.answered}/${progress.total} nhóm`;
    byId("group-meter").max = Math.max(progress.total, 1);
    byId("group-meter").value = progress.answered;
    const box = byId("group-question"); box.replaceChildren();
    byId("group-form").hidden = !data.group;
    byId("groups-complete").hidden = Boolean(data.group);
    byId("group-name").textContent = data.group ? groupName(data.group) : "";
    if (!data.group) {
      add("p", "Đã đi qua các nhóm hiện trạng. Bạn vẫn có thể sửa câu trả lời hoặc hỏi tiếp trong chat.", box);
    } else {
      add("p", String(data.question || "").split("\n")[0], box, "group-prompt");
      const conditions = [...new Set((currentReport?.obligations || [])
        .filter(row => row.group === data.group && row.applicability === "ap_dung_neu")
        .flatMap(row => row.conditions || []))];
      if (conditions.length) add("p", `Một số nghĩa vụ trong nhóm chỉ áp dụng nếu: ${conditions.join("; ")}`, box, "conditional-note");
      const details = add("details", undefined, box);
      add("summary", `Nghĩa vụ trong nhóm (${(data.obligations || []).length})`, details);
      for (const row of data.obligations || []) add("p", row.obligation, details);
    }
    byId("group-answer").value = editing ? groupAnswers.get(data.group)?.text || "" : "";
    const list = byId("group-list"); list.replaceChildren();
    byId("answered-groups").hidden = !(prepared?.groups || []).length;
    for (const group of prepared?.groups || []) {
      const answer = groupAnswers.get(group.group);
      const suffix = answer ? answer.unknown ? " · cần bổ sung" : " · đã trả lời" : "";
      button(list, groupName(group.group) + suffix, () => { setStage("groups"); showGroup({...group, progress}, true); byId("group-answer").focus(); });
    }
  }
  async function answerGroup(unknown) {
    const text = byId("group-answer").value;
    if (!currentGroup || (!unknown && !text.trim())) {
      byId("assessment-error").textContent = "Nhập hiện trạng hoặc chọn “Không biết / để sau”."; return;
    }
    const group = currentGroup;
    await request(async () => {
      if (needsPrepare) { await prepare(); throw new Error("Đã cập nhật dữ kiện từ hội thoại. Vui lòng kiểm tra rồi trả lời nhóm hiện tại."); }
      const data = await api("answer", {group, text: unknown ? "" : text, unknown});
      groupAnswers.set(group, {text: unknown ? "" : text, unknown}); currentReport = data.report; markStale(data.stale);
      nextQuestion = data.next; showGroup(nextQuestion); showReport();
      if (!nextQuestion.group) setStage("report");
    });
  }
  function citations(parent, entry) {
    for (const citation of entry.citations || []) add("p", citation.label, parent, "legal-citation");
  }
  function evidenceSource(criterion) {
    const source = criterion.evidence_source || criterion.source;
    if (source === "hoi_thoai") return "từ hội thoại";
    if (source === "nguoi_dung") return "theo bạn xác nhận";
    if (source?.startsWith("nhom:")) return `từ câu trả lời về ${groupName(source.slice(5))}`;
    return "";
  }
  function checkButtons(parent, rowId, criterionId) {
    const controls = add("div", undefined, parent, "check-actions");
    for (const [value, label] of [["da", "Có"], ["chua", "Chưa"], [null, "Bỏ xác nhận"]]) {
      const control = button(controls, label, () => request(async () => {
        const data = await api("check", {row_id: rowId, criterion_id: criterionId, value});
        currentReport = data.report; markStale(data.stale); showReport();
      }));
      control.dataset.check = "true"; control.disabled = isStale || needsPrepare;
    }
  }
  function askAbout(entry) {
    openPanel(false);
    setChatContext(entry); input.value = `Tôi cần làm gì để thực hiện nghĩa vụ “${entry.obligation}”?`;
    input.focus(); input.scrollIntoView({block: "center"});
  }
  function obligation(parent, entry) {
    const card = add("article", undefined, parent, "obligation");
    const title = add("div", undefined, card, "obligation-heading");
    add("h4", entry.obligation, title);
    add("span", statuses[entry.status] || "Cần xác minh", title, `badge ${entry.status}`);
    if (entry.conditions?.length) add("p", `Áp dụng nếu: ${entry.conditions.join("; ")}`, card, "conditional-note");
    if (entry.deadline) add("p", `Thời hạn: ${entry.deadline}`, card, "deadline");
    citations(card, entry);
    const details = add("details", undefined, card);
    add("summary", `Tiêu chí và bằng chứng (${entry.criteria.length})`, details);
    for (const criterion of entry.criteria) {
      const section = add("div", undefined, details, "criterion");
      add("p", criterion.text, section); add("span", statuses[criterion.status] || "Cần xác minh", section, `badge ${criterion.status}`);
      if (criterion.quote) add("blockquote", criterion.quote, section);
      const source = evidenceSource(criterion); if (source) add("small", source, section);
      if (criterion.status === "chua_ro" || criterion.source === "nguoi_dung") checkButtons(section, entry.id, criterion.id);
    }
    button(card, "Hỏi về nghĩa vụ này", () => askAbout(entry), "text-button");
  }
  function priority(entry) {
    if (entry.kind === "cam" || entry.status === "co_dau_hieu") return 0;
    const deadline = (entry.deadline || "").toLocaleLowerCase("vi");
    if (deadline.includes("trước khi đưa")) return 1;
    if (entry.group === "chuyen_tiep" && deadline) return 2;
    return 3;
  }
  function verificationRows(report) {
    return [...report.warnings.map(row => ({...row, kind: "cam"})), ...report.obligations.filter(row => row.status === "chua_ro")]
      .sort((a, b) => priority(a) - priority(b));
  }
  function verificationMarkdown(report) {
    const safe = text => String(text || "").replace(/[<>]/g, c => c === "<" ? "&lt;" : "&gt;").replace(/\r?\n/g, " ");
    const lines = ["# Danh sách cần xác minh", "", ...(isStale ? ["Lưu ý: bản đánh giá dùng dữ kiện cũ.", ""] : [])];
    for (const row of verificationRows(report)) {
      lines.push(`## ${safe(row.obligation)}`, "");
      if (row.conditions?.length) lines.push(`Áp dụng nếu: ${row.conditions.map(safe).join("; ")}`);
      if (row.deadline) lines.push(`Thời hạn: ${safe(row.deadline)}`);
      for (const criterion of row.criteria || []) {
        if (row.kind === "cam" || criterion.status === "chua_ro") lines.push(`- ${safe(criterion.text)}`);
      }
      for (const citation of row.citations || []) lines.push(`Căn cứ: ${safe(citation.label)}`);
      lines.push("");
    }
    if (!verificationRows(report).length) lines.push("Không có mục cần xác minh.", "");
    return lines.join("\n");
  }
  function showReport() {
    reportBox.replaceChildren();
    byId("worst-case-control").hidden = !currentReport;
    byId("verification-download").hidden = !currentReport;
    byId("view-report").hidden = !currentReport;
    download.hidden = !currentReport;
    if (!currentReport) { add("p", "Trả lời từng nhóm để hình thành bản đánh giá. Mục thiếu thông tin được ghi là “Cần xác minh”.", reportBox, "empty-state"); return; }
    const report = currentReport, s = report.summary;
    const worst = byId("worst-case").checked;
    for (const warning of report.warnings) {
      const box = add("div", undefined, reportBox, "assessment-warning");
      add("h4", "Dấu hiệu hành vi bị cấm cần xác minh", box); add("p", warning.obligation, box);
      for (const quote of warning.quotes || []) add("blockquote", quote, box);
      if (warning.conditions?.length) add("p", `Áp dụng nếu: ${warning.conditions.join("; ")}`, box);
      citations(box, warning);
    }
    const metrics = add("div", undefined, reportBox, "report-metrics");
    const known = report.obligations.filter(row => row.applicability === "ap_dung" && ["da", "chua"].includes(row.status)).length;
    const coverage = add("section", undefined, metrics);
    add("h4", "Độ đủ thông tin", coverage); add("strong", `${known}/${s.total}`, coverage, "metric-value");
    add("p", "nghĩa vụ đã có kết luận", coverage);
    const compliance = add("section", undefined, metrics);
    add("h4", "Mức độ tuân thủ", compliance);
    add("strong", `${s.da} đáp ứng`, compliance, "metric-value");
    add("p", `${s.chua} chưa đáp ứng trong ${known} nghĩa vụ có kết luận`, compliance);
    if (worst) add("p", `Kịch bản xấu nhất: ${s.chua + s.chua_ro} chưa đáp ứng trên ${s.total} nghĩa vụ áp dụng, gồm ${s.chua_ro} mục đang cần xác minh. Đây là giả định, không phải kết luận vi phạm.`, reportBox, "scenario-note");
    add("p", `${s.conditional_total} nghĩa vụ có điều kiện được trình bày riêng bên dưới.`, reportBox, "muted");
    for (const [status, symbol] of [["chua", "!"], ["chua_ro", "?"], ["da", "✓"]]) {
      const rows = report.obligations.filter(row => row.applicability === "ap_dung" && row.status === status)
        .sort((a, b) => status === "chua_ro" ? priority(a) - priority(b) : 0);
      const section = add("details", undefined, reportBox, `status-section ${status}`);
      section.open = status === "chua" && rows.length > 0;
      add("summary", `${symbol} ${statuses[status]} (${rows.length})`, section);
      if (!rows.length) add("p", "Không có nghĩa vụ trong nhóm này.", section, "muted");
      for (const row of rows) obligation(section, row);
    }
    const conditional = report.obligations.filter(row => row.applicability === "ap_dung_neu");
    if (conditional.length) {
      const section = add("details", undefined, reportBox, "status-section");
      add("summary", `Nghĩa vụ có điều kiện (${conditional.length})`, section);
      for (const row of conditional) obligation(section, row);
    }
    const tasks = report.todo.filter(task => task.type === "bo_sung_du_kien");
    if (tasks.length) {
      const box = add("section", undefined, reportBox); add("h4", "Dữ kiện cần bổ sung", box);
      for (const task of tasks) button(box, task.text, () => jump(task.field), "text-button");
    }
    if (report.info.length) {
      const box = add("details", undefined, reportBox, "status-section"); add("summary", "Thông tin và hạn chuyển tiếp", box);
      for (const info of report.info) {
        add("p", info.obligation, box);
        if (info.deadline) add("p", `Thời hạn: ${info.deadline}`, box);
        if (info.conditions?.length) add("p", `Áp dụng nếu: ${info.conditions.join("; ")}`, box);
        citations(box, info);
      }
    }
    add("p", report.meta.disclaimer, reportBox, "session-note");
    download.href = `/api/assess/report.md?session_id=${encodeURIComponent(sessionId)}`;
  }
  byId("open-assessment").addEventListener("click", () => {
    openPanel(true);
    setStage(stage);
    request(async () => { if (!started || needsPrepare) await prepare(); else await loadState(); });
    panel.scrollIntoView({block: "start"});
  });
  byId("close-assessment").addEventListener("click", () => openPanel(false));
  byId("refresh-assessment").addEventListener("click", () => { setStage("facts"); request(prepare); });
  byId("group-form").addEventListener("submit", event => { event.preventDefault(); answerGroup(false); });
  byId("group-unknown").addEventListener("click", () => answerGroup(true));
  byId("worst-case").addEventListener("change", showReport);
  byId("verification-download").addEventListener("click", () => {
    if (!currentReport) return;
    if (verificationURL) URL.revokeObjectURL(verificationURL);
    verificationURL = URL.createObjectURL(new Blob([verificationMarkdown(currentReport)], {type: "text/markdown;charset=utf-8"}));
    const link = add("a"); link.href = verificationURL; link.download = "can-xac-minh.md"; link.click();
  });
  uiEvents.addEventListener("chat-finished", () => {
    if (!started) return;
    needsPrepare = true;
    // Không tự gọi thêm LLM sau chat; cập nhật khi người dùng trở lại rà soát.
    byId("stale-notice").hidden = false;
    const title = byId("stale-notice").querySelector("strong");
    if (title) title.textContent = "Hội thoại đã có nội dung mới";
    showReport();
  });
  uiEvents.addEventListener("session-reset", () => {
    prepared = currentReport = currentGroup = nextQuestion = null;
    started = needsPrepare = false; groupAnswers = new Map(); markStale(false);
    setStage("facts"); byId("product-summary").replaceChildren(); byId("facts-editor").open = false;
    byId("facts-table").replaceChildren(); byId("fact-questions").replaceChildren();
    byId("facts-ready").textContent = "Chưa chuẩn bị";
    byId("group-question").replaceChildren(); byId("group-form").hidden = true;
    byId("group-answer").value = ""; byId("group-list").replaceChildren(); byId("answered-groups").hidden = true;
    byId("group-progress").textContent = ""; byId("group-meter").value = 0;
    byId("assessment-error").textContent = ""; byId("worst-case").checked = false;
    retryAction = null; byId("retry-assessment").hidden = true;
    if (verificationURL) { URL.revokeObjectURL(verificationURL); verificationURL = null; }
    download.removeAttribute("href"); showReport(); openPanel(false); setBusy(false);
  });
  // Chỉ khôi phục đánh giá đã có, không tự trích dữ kiện hoặc mở khung.
  request(async () => {
    try {
      const data = await api("state");
      if (data.report || Object.values(data.facts).some(value => value != null)) {
        started = true; showFacts(data); currentReport = data.report; markStale(data.stale);
        nextQuestion = await api("next"); showGroup(nextQuestion); showReport();
      }
    } catch (error) { if (error.status !== 404) throw error; }
  });
})();
