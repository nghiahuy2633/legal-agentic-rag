"use strict";

const chat = document.getElementById("chat");
const input = document.getElementById("message");
const send = document.getElementById("send");
const newSession = document.getElementById("new-session");
const waiting = document.getElementById("waiting");
let sessionId = sessionStorage.getItem("legal-rag-session");
let chatBusy = false;
let assessmentBusy = false;
let connectionBusy = false;
let chatContext = null;
let connectionToken = sessionStorage.getItem("legal-rag-ai-token");
// Model chọn trong Kết nối AI; nhớ giữa các lần mở trang nếu trình duyệt cho phép.
function readModel() {
  try { return typeof localStorage === "undefined" ? null : localStorage.getItem("legal-rag-ai-model"); }
  catch { return null; }
}
function saveModel(model) {
  selectedModel = model || null;
  try { if (typeof localStorage !== "undefined") model ? localStorage.setItem("legal-rag-ai-model", model) : localStorage.removeItem("legal-rag-ai-model"); }
  catch { /* Không lưu được thì vẫn dùng trong trang hiện tại. */ }
}
let selectedModel = readModel();
const uiEvents = new EventTarget();
async function aiFetch(url, options = {}) {
  const response = await fetch(url, {...options, headers: {...options.headers,
    ...(connectionToken ? {"X-AI-Connection": connectionToken} : {}),
    ...(selectedModel ? {"X-AI-Model": selectedModel} : {})}});
  if (response.status === 401 && connectionToken) uiEvents.dispatchEvent(new Event("connection-expired"));
  return response;
}
function updateChatControls() {
  const locked = chatBusy || assessmentBusy || connectionBusy;
  send.disabled = locked;
  newSession.disabled = locked;
  input.readOnly = locked;
  const opener = document.getElementById("open-assessment");
  if (opener) opener.disabled = locked;
  const connection = document.getElementById("open-connection");
  if (connection) connection.disabled = locked;
}
function setChatContext(entry) {
  chatContext = entry ? {obligation_id: entry.id} : null;
  const box = document.getElementById("chat-context");
  if (box) box.hidden = !entry;
  const label = document.getElementById("chat-context-label");
  if (label) label.textContent = entry ? `Đang hỏi về: ${entry.obligation}` : "";
}
document.getElementById("clear-context")?.addEventListener("click", () => setChatContext(null));
function makeSession() {
  sessionId = crypto.randomUUID();
  sessionStorage.setItem("legal-rag-session", sessionId);
}
if (!sessionId) makeSession();

function escapeHTML(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[char]));
}

function inlineMarkdown(text) {
  // Escape luôn chạy trước mọi phép đổi định dạng, kể cả mã trích dẫn.
  return escapeHTML(text).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\[(E\d+(?:\.[a-zđ])?(?:\s*,\s*E\d+(?:\.[a-zđ])?)*)\]/gi,
      (_, codes) => codes.split(/\s*,\s*/).map(code =>
        `<button type="button" class="citation" data-citation="${code}">[${code}]</button>`).join(" "));
}

function inlineContent(text) {
  const source = text.match(/(?:^|\s)(https?:\/\/\S+)\s*$/);
  if (source) {
    try {
      const url = new URL(source[1]);
      if (["http:", "https:"].includes(url.protocol)) {
        return inlineMarkdown(text.slice(0, source.index)) +
          ` <a href="${escapeHTML(source[1])}" target="_blank" rel="noopener noreferrer">Nguồn</a>`;
      }
    } catch { /* URL không hợp lệ vẫn hiển thị như văn bản. */ }
  }
  return inlineMarkdown(text);
}

function markdownLines(lines) {
  let result = "", list = null;
  function closeList() { if (list) result += `</li></${list}>`; list = null; }
  for (const line of lines) {
    const item = line.match(/^\s*(?:([-*])|(\d+)[.)])\s+(.+)$/);
    if (item) {
      const kind = item[1] ? "ul" : "ol";
      if (list !== kind) { closeList(); result += `<${kind}>`; list = kind; }
      else result += "</li>";
      result += `<li${kind === "ol" ? ` value="${Number(item[2])}"` : ""}>${inlineContent(item[3])}`;
    } else if (list === "ol" && /^\s+Trạng thái:/.test(line)) {
      result += `<p>${inlineContent(line.trim())}</p>`;
    } else if (!line.trim()) {
      // Dòng trống không chia một danh sách đang có thành nhiều danh sách.
      continue;
    } else {
      closeList();
      result += line.startsWith("### ") ? `<h3>${inlineContent(line.slice(4))}</h3>`
        : line.startsWith("## ") ? `<h2>${inlineContent(line.slice(3))}</h2>`
        : `<p>${inlineContent(line)}</p>`;
    }
  }
  closeList();
  return result;
}

function markdown(text) {
  const lines = String(text ?? "").split(/\r?\n/);
  let result = "", plain = [];
  const isClosing = line => /^Đây là hướng dẫn sơ bộ,\s+không phải\s+tư vấn pháp lý\.\s*$/.test(line);
  function flush() { result += markdownLines(plain); plain = []; }
  for (let index = 0; index < lines.length; index++) {
    const legal = lines[index].trimEnd() === "## Căn cứ pháp lý";
    const criteria = lines[index].startsWith("Căn cứ cần xem xét");
    if (!legal && !criteria) { plain.push(lines[index]); continue; }
    flush();
    const section = legal ? [] : [lines[index]];
    while (index + 1 < lines.length && !lines[index + 1].startsWith("## ") && !isClosing(lines[index + 1])) {
      section.push(lines[++index]);
    }
    const summary = legal ? `Căn cứ pháp lý (${section.filter(line => line.trim()).length})`
      : "Xem nguyên văn tiêu chí xác định và tiêu chí loại trừ";
    result += `<details><summary>${summary}</summary>${markdownLines(section)}</details>`;
  }
  flush();
  return result;
}

function element(tag, text, parent) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (parent) parent.append(node);
  return node;
}

const profileLabels = {
  role: "Vai trò", sector: "Lĩnh vực", is_public_sector: "Thuộc khu vực công",
  generates_content: "Có tạo nội dung", product_description: "Mô tả sản phẩm"
};
const valueLabels = {
  nha_phat_trien: "Nhà phát triển", nha_cung_cap: "Nhà cung cấp", ben_trien_khai: "Bên triển khai",
  nguoi_su_dung: "Người sử dụng", giao_duc: "Giáo dục", y_te: "Y tế",
  tai_chinh_ngan_hang: "Tài chính, ngân hàng", dan_toc_ton_giao: "Dân tộc, tôn giáo",
  to_tung: "Tố tụng", giao_thong_van_tai: "Giao thông vận tải", thuong_mai: "Thương mại",
  quang_cao: "Quảng cáo", an_sinh_xa_hoi: "An sinh xã hội", lam_dep: "Làm đẹp", lao_dong: "Lao động", khac: "Khác"
};
function showProfile(profile = {}) {
  const box = document.getElementById("profile");
  box.replaceChildren();
  for (const [key, label] of Object.entries(profileLabels)) {
    element("dt", label, box);
    const value = profile[key];
    element("dd", value == null || value === "" ? "Chưa rõ" : typeof value === "boolean"
      ? (value ? "Có" : "Không") : (valueLabels[value] || value), box);
  }
}
showProfile();

function messageBox(kind, text) {
  const welcome = document.getElementById("welcome");
  if (welcome) welcome.hidden = true;
  const article = element("article", undefined, chat);
  article.className = kind;
  element("h2", kind === "user" ? "Bạn" : kind === "error" ? "Thông báo lỗi" : "Hướng dẫn sơ bộ", article);
  if (text !== undefined) element("p", text, article);
  return article;
}

function showEvidence(box, items, marker) {
  box.replaceChildren();
  const [id, point] = marker.split(".");
  const item = items.find(row => row.id.toUpperCase() === id.toUpperCase());
  if (!item) { element("p", `Không có căn cứ cho mã [${marker}].`, box); return; }
  element("h3", `Căn cứ ${id.replace(/^E/i, "")} · ${item.document_number || item.document_title || "Văn bản nguồn"}`, box);
  element("p", [item.document_title, item.article && `Điều ${item.article}`,
    item.clause && `Khoản ${item.clause}`, point && `Điểm ${point}`, item.article_title].filter(Boolean).join(" · "), box);
  const text = String(item.text || "");
  const excerpt = text.length > 650 ? text.slice(0, 650).replace(/\s+\S*$/, "") + "…" : text;
  const quote = element("blockquote", excerpt || "Chưa có nguyên văn trong dữ liệu trả về.", box);
  quote.className = "source-excerpt";
  if (text.length > 650) {
    const full = element("details", undefined, box);
    element("summary", "Đọc toàn bộ nguyên văn", full); element("pre", text, full);
  }
  for (const [key, label] of [["scope_note", "Phạm vi"], ["conformity_note", "Loại đánh giá"],
    ["referenced_from", "Dẫn chiếu từ"], ["external_refs", "Dẫn chiếu ngoài dữ liệu"]]) {
    if (item[key]) element("p", `${label}: ${Array.isArray(item[key]) ? item[key].join("; ") : item[key]}`, box);
  }
  if (item.source_url) {
    try {
      const url = new URL(item.source_url);
      if (["http:", "https:"].includes(url.protocol)) {
        const link = element("a", "Mở nguồn nguyên văn", box);
        link.href = url.href; link.target = "_blank"; link.rel = "noopener noreferrer";
      }
    } catch { /* Không tạo liên kết từ URL không hợp lệ. */ }
  }
}

let evidenceCopyText = "";
function openEvidence(items, marker, trigger) {
  const dialog = document.getElementById("evidence-dialog");
  if (!dialog) return;
  const box = document.getElementById("evidence-content");
  showEvidence(box, items, marker);
  const item = items.find(row => row.id.toUpperCase() === marker.split(".")[0].toUpperCase());
  evidenceCopyText = String(item?.text || "");
  document.getElementById("copy-status").textContent = "";
  document.getElementById("copy-evidence").disabled = !evidenceCopyText;
  if (!dialog.open) dialog.showModal();
}
document.getElementById("close-evidence")?.addEventListener("click", () => document.getElementById("evidence-dialog").close());
document.getElementById("copy-evidence")?.addEventListener("click", async () => {
  const status = document.getElementById("copy-status");
  try { await navigator.clipboard.writeText(evidenceCopyText); status.textContent = "Đã sao chép nguyên văn"; }
  catch { status.textContent = "Chưa sao chép được. Bạn có thể chọn và sao chép văn bản bên trên."; }
});

const nodeLabels = {
  check_input: "Kiểm tra đầu vào", analyze: "Phân tích tình huống", check_scope: "Kiểm tra phạm vi",
  update_profile: "Cập nhật hồ sơ", plan_queries: "Truy vấn đã lập", retrieve: "Truy xuất căn cứ",
  grade_evidence: "Chấm bằng chứng", rewrite_query: "Viết lại truy vấn", generate: "Sinh câu trả lời",
  verify_citations: "Kiểm chứng trích dẫn", repair_answer: "Sửa câu trả lời", recheck: "Kiểm tra lại",
  ask_followup: "Hỏi bổ sung", respond: "Trả lời", check_high_risk: "Đối chiếu Danh mục",
  map_obligations: "Nghĩa vụ đã chọn và số dòng chưa soát"
};
const fieldLabels = {
  sub_queries: "Truy vấn", status: "Trạng thái", missing: "Nội dung còn thiếu", rewrite: "Truy vấn viết lại",
  grade_ok: "Kết quả chấm hợp lệ", grade_error: "Lỗi chấm", rewrite_count: "Số lần viết lại",
  verify_ok: "Kiểm chứng hợp lệ", issues: "Vấn đề kiểm chứng", verify_error: "Lỗi kiểm chứng",
  repair_error: "Lỗi sửa", verification: "Kiểm chứng và sửa", field: "Trường hỏi bổ sung",
  high_risk: "Kết quả đối chiếu Danh mục", high_risk_error: "Lỗi đối chiếu", assess_ok: "Đối chiếu hợp lệ",
  map_obligations: "Ánh xạ nghĩa vụ", unreviewed_count: "Số dòng chưa soát", rejected_count: "Số dòng bị loại",
  risk_level: "Mức rủi ro", selected: "Các mục đã chọn", check: "Kiểm tra trích dẫn"
};
function dataBlock(parent, title, data) {
  element("h3", title, parent);
  element("pre", typeof data === "string" ? data : JSON.stringify(data, null, 2), parent);
}
function rankings(parent, title, rows) { dataBlock(parent, title + " (top 5)", (rows || []).slice(0, 5)); }
function showProcess(article, data) {
  const details = element("details", undefined, article);
  element("summary", "Quá trình xử lý", details);
  element("p", `Tổng thời gian: ${Number(data.total_ms).toFixed(0)} ms · Số lượt LLM: ${data.llm_calls}`, details);
  const process = data.process || {};
  for (const node of process.nodes || []) {
    const section = element("section", undefined, details);
    element("h3", `${nodeLabels[node.node] || node.node} · ${Number(node.ms || 0).toFixed(0)} ms · ${node.llm_calls || 0} lượt LLM`, section);
    for (const [key, label] of Object.entries(fieldLabels)) {
      if (node[key] !== undefined) dataBlock(section, label, node[key]);
    }
    if (node.last_detail) {
      const detail = node.last_detail;
      dataBlock(section, "Truy vấn tìm kiếm", detail.queries);
      for (const retrieval of detail.retrieval || []) {
        dataBlock(section, "Truy vấn", retrieval.query);
        rankings(section, "BM25", retrieval.bm25);
        for (const [name, rows] of Object.entries(retrieval.dense || {})) rankings(section, name, rows);
      }
      rankings(section, "Sau fusion", detail.rrf);
      rankings(section, "Sau rerank", detail.rerank);
      rankings(section, "Tra cứu chính xác", detail.exact);
    }
  }
  dataBlock(details, "Ngữ cảnh đưa vào LLM kèm nguồn", process.evidence || []);
  dataBlock(details, "Kết quả kiểm tra trích dẫn", process.check || {});
}

function showAnswer(data) {
  const article = messageBox("assistant");
  const reply = element("div", undefined, article);
  reply.className = "reply";
  // Markdown đã escape ở trên; parser giữ nguyên cách hiển thị của tab hỏi đáp.
  const parsed = new DOMParser().parseFromString(markdown(data.reply), "text/html");
  reply.replaceChildren(...parsed.body.childNodes);
  const modernEvidence = document.getElementById("evidence-dialog");
  for (const control of reply.querySelectorAll?.("button[data-citation]") || []) {
    const marker = control.dataset.citation;
    const item = (data.evidence || []).find(row => row.id.toUpperCase() === marker.split(".")[0].toUpperCase());
    if (item) {
      const label = item.document_number || item.document_title || "Căn cứ";
      control.textContent = `${marker.replace(/^E/i, "")} · ${label.length > 30 ? label.slice(0, 30) + "…" : label}`;
      control.title = [item.document_title, item.article && `Điều ${item.article}`, item.clause && `Khoản ${item.clause}`].filter(Boolean).join(", ");
    }
  }
  if (modernEvidence) {
    const sources = element("div", undefined, article); sources.className = "answer-sources";
    const cited = new Set((String(data.reply).match(/E\d+/gi) || []).map(id => id.toUpperCase()));
    for (const item of (data.evidence || []).filter(row => cited.has(row.id.toUpperCase()))) {
      const button = element("button", [item.id.replace(/^E/i, ""), item.document_number || item.document_title || "Căn cứ", item.article && `Điều ${item.article}`].filter(Boolean).join(" · "), sources);
      button.type = "button"; button.className = "source-chip";
      button.addEventListener("click", () => openEvidence(data.evidence || [], item.id, button));
    }
    reply.addEventListener("click", event => {
      const button = event.target.closest("button[data-citation]");
      if (button) openEvidence(data.evidence || [], button.dataset.citation, button);
    });
    const diagnostics = element("details", undefined, article); diagnostics.className = "answer-diagnostics";
    element("summary", "Chi tiết câu trả lời", diagnostics); showProcess(diagnostics, data);
    showProfile(data.profile); return;
  }
  const evidenceDetails = element("details", undefined, article);
  element("summary", "Căn cứ của câu trả lời này", evidenceDetails);
  const evidenceBox = element("div", undefined, evidenceDetails);
  evidenceBox.className = "evidence";
  element("p", "Bấm mã trích dẫn để xem nguyên văn căn cứ.", evidenceBox);
  // Closure giữ đúng tập E của tin nhắn, không dùng tập căn cứ của lượt sau.
  reply.addEventListener("click", event => {
    const button = event.target.closest("button[data-citation]");
    if (!button) return;
    evidenceDetails.open = true;
    showEvidence(evidenceBox, data.evidence || [], button.dataset.citation);
    evidenceDetails.scrollIntoView({block: "nearest"});
  });
  if ((data.citations || []).length) dataBlock(evidenceDetails, "Danh sách trích dẫn", data.citations);
  showProcess(article, data);
  showProfile(data.profile);
}

newSession.addEventListener("click", () => {
  if (chatBusy || assessmentBusy || connectionBusy) return;
  makeSession(); chat.replaceChildren(); input.value = ""; showProfile(); input.focus();
  setChatContext(null);
  const welcome = document.getElementById("welcome");
  if (welcome) welcome.hidden = false;
  const hint = document.getElementById("assessment-hint");
  if (hint) hint.hidden = true;
  uiEvents.dispatchEvent(new Event("session-reset"));
});
document.querySelectorAll?.("[data-prompt]").forEach(button => button.addEventListener("click", () => {
  input.value = button.dataset.prompt; input.focus();
}));
document.getElementById("chat-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (send.disabled) return;
  const message = input.value;
  if (!message.trim()) return;
  messageBox("user", message);
  chatBusy = true; updateChatControls();
  const started = Date.now();
  function progress() { waiting.textContent = `Đang xử lý… ${Math.floor((Date.now() - started) / 1000)} giây. Câu trả lời có thể mất hơn một phút.`; }
  progress();
  const timer = setInterval(progress, 1000);
  try {
    const response = await aiFetch("/api/chat", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({session_id: sessionId, message, ...(chatContext ? {context: chatContext} : {})})});
    if (!response.ok) {
      let error = response.status === 422 ? "Dữ liệu không hợp lệ. Kiểm tra mã phiên và độ dài tin nhắn (tối đa 20000 ký tự)."
        : "Không xử lý được yêu cầu. Vui lòng thử lại.";
      try { const body = await response.json(); if (Array.isArray(body.detail)) error = body.detail.map(item => item.msg).join(" "); else if (typeof body.detail === "string") error = body.detail; } catch { /* Giữ thông báo mặc định. */ }
      messageBox("error", error);
    } else {
      const data = await response.json();
      showAnswer(data);
      if (!data.error) { input.value = ""; setChatContext(null); }
      const hint = document.getElementById("assessment-hint");
      if (hint && data.profile?.product_description) hint.hidden = false;
    }
  } catch {
    messageBox("error", "Mất kết nối với máy chủ. Nội dung đã được giữ lại; vui lòng thử gửi lại.");
  } finally {
    clearInterval(timer); waiting.textContent = "";
    chatBusy = false; updateChatControls(); input.focus();
    uiEvents.dispatchEvent(new Event("chat-finished"));
    chat.lastElementChild?.scrollIntoView({block: "nearest"});
  }
});
