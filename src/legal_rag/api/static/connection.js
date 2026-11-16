"use strict";

(() => {
  const byId = id => document.getElementById(id);
  const dialog = byId("connection-dialog");
  let connectionSession = sessionId;
  let state = null;
  // Ghi chú ngắn cho model đã đo trên bộ kiểm tra; model khác chỉ hiện tên.
  const MODEL_NOTES = {
    "gemini-3.6-flash": "đầy đủ hơn",
    "gemini-3.5-flash-lite": "nhanh, rẻ hơn",
  };
  function renderModels(data) {
    const models = data.models || [];
    const select = byId("model-select");
    if (selectedModel && !models.includes(selectedModel)) saveModel(null);
    const many = models.length > 1;
    select.hidden = !many; byId("model-help").hidden = !many;
    byId("connection-model").hidden = many;
    if (!many) return;
    select.replaceChildren(...models.map(name => {
      const option = document.createElement("option");
      option.value = name;
      const note = [name === data.model ? "mặc định" : null, MODEL_NOTES[name]].filter(Boolean).join(", ");
      option.textContent = note ? `${name} (${note})` : name;
      return option;
    }));
    select.value = selectedModel || data.model;
  }
  function mode() {
    const personal = byId("mode-personal").checked;
    byId("personal-fields").hidden = !personal;
    byId("api-key").required = personal;
    byId("save-connection").textContent = personal ? "Kiểm tra & kết nối" : "Dùng kết nối hệ thống";
  }
  function render(data) {
    state = data;
    const providerName = data.provider === "generativelanguage.googleapis.com" ? "Google Gemini" : data.provider;
    byId("connection-provider").textContent = providerName || "Chưa cấu hình trên máy chủ";
    byId("connection-model").textContent = data.model || "Chưa cấu hình";
    renderModels(data);
    byId("mode-personal").disabled = !data.available;
    const needsKey = data.system_available === false && data.available;
    byId("mode-system").disabled = data.system_available === false;
    byId("mode-personal").checked = data.mode === "personal" || needsKey;
    byId("mode-system").checked = data.mode !== "personal" && !needsKey;
    byId("disconnect-ai").hidden = !data.connected && !connectionToken;
    byId("connection-label").textContent = data.connected ? "Khóa cá nhân" : data.reconnect_required ? "Kết nối cần kiểm tra" : "Kết nối AI";
    byId("open-connection").classList.toggle("personal-connected", data.connected);
    byId("connection-status").textContent = data.connected ? "Đang dùng khóa cá nhân cho chat và đánh giá."
      : data.reconnect_required ? "Kết nối đã thay đổi. Nhập lại khóa hoặc tạo phiên mới."
      : needsKey ? "Nhập khóa cá nhân để bắt đầu. Máy chủ chưa có khóa mặc định."
      : "Đang dùng kết nối hệ thống.";
    mode();
  }
  async function request(url, options) {
    const response = await aiFetch(url, options);
    const data = await response.json();
    if (!response.ok) {
      const detail = Array.isArray(data.detail) ? data.detail.map(item => item.msg).join(" ") : data.detail;
      throw new Error(detail || "Chưa xử lý được kết nối. Vui lòng thử lại.");
    }
    return data;
  }
  async function action(fn) {
    if (connectionBusy || chatBusy || assessmentBusy) return;
    connectionBusy = true; updateChatControls();
    byId("connection-error").textContent = "";
    const controls = ["save-connection", "disconnect-ai", "mode-system", "mode-personal", "api-key", "toggle-key", "model-select"];
    controls.forEach(id => { byId(id).disabled = true; });
    try { await fn(); }
    catch (error) {
      byId("connection-error").textContent = error instanceof TypeError ? "Không kết nối được máy chủ. Kiểm tra mạng và thử lại." : error.message;
      byId("connection-status").textContent = state?.connected ? "Kết nối cá nhân trước đó vẫn được giữ." : "Chưa thiết lập kết nối cá nhân.";
    }
    finally {
      connectionBusy = false; updateChatControls();
      controls.forEach(id => { byId(id).disabled = false; });
      if (state && !state.available) byId("mode-personal").disabled = true;
      if (state?.system_available === false) byId("mode-system").disabled = true;
    }
  }
  function forgetToken() {
    connectionToken = null; sessionStorage.removeItem("legal-rag-ai-token");
  }
  async function disconnect() {
    const data = await request(`/api/connection?session_id=${encodeURIComponent(sessionId)}`, {method: "DELETE"});
    forgetToken(); render(data); byId("api-key").value = "";
  }
  byId("open-connection").addEventListener("click", () => {
    if (chatBusy || assessmentBusy || connectionBusy) return;
    dialog.showModal();
    action(async () => render(await request(`/api/connection?session_id=${encodeURIComponent(sessionId)}`)));
  });
  byId("close-connection").addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => {
    byId("api-key").value = ""; byId("api-key").type = "password";
    byId("toggle-key").textContent = "Hiện"; byId("toggle-key").setAttribute("aria-pressed", "false");
  });
  for (const id of ["mode-system", "mode-personal"]) byId(id).addEventListener("change", mode);
  byId("model-select").addEventListener("change", () => {
    const model = byId("model-select").value;
    saveModel(model === state?.model ? null : model);
    byId("connection-status").textContent = `Đã chọn model ${model} cho các câu hỏi tiếp theo.`;
  });
  byId("toggle-key").addEventListener("click", () => {
    const show = byId("api-key").type === "password";
    byId("api-key").type = show ? "text" : "password";
    byId("toggle-key").textContent = show ? "Ẩn" : "Hiện";
    byId("toggle-key").setAttribute("aria-pressed", String(show));
  });
  byId("connection-form").addEventListener("submit", event => {
    event.preventDefault();
    action(async () => {
      if (byId("mode-system").checked) {
        if (connectionToken || state?.reconnect_required) await disconnect();
        byId("connection-status").textContent = "Đang dùng kết nối hệ thống.";
        return;
      }
      const key = byId("api-key").value.trim();
      if (key.length < 8 || /\s/.test(key)) throw new Error("Nhập khóa API hợp lệ, không chứa khoảng trắng.");
      byId("connection-status").textContent = "Đang kiểm tra khóa với nhà cung cấp…";
      const data = await request("/api/connection", {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({session_id: sessionId, api_key: key})});
      connectionToken = data.connection_token;
      sessionStorage.setItem("legal-rag-ai-token", connectionToken);
      byId("api-key").value = ""; render(data);
    });
  });
  byId("disconnect-ai").addEventListener("click", () => action(disconnect));
  uiEvents.addEventListener("connection-expired", () => {
    byId("connection-label").textContent = "Kết nối cần kiểm tra";
    byId("open-connection").classList.toggle("personal-connected", false);
    byId("connection-error").textContent = "Khóa cá nhân đã hết hạn hoặc bị thay đổi. Kết nối lại hoặc chọn kết nối hệ thống.";
  });
  uiEvents.addEventListener("session-reset", () => {
    const oldToken = connectionToken, oldSession = connectionSession;
    forgetToken(); connectionSession = sessionId; state = null;
    byId("connection-label").textContent = "Kết nối AI";
    byId("open-connection").classList.toggle("personal-connected", false);
    byId("api-key").value = "";
    if (oldToken) fetch(`/api/connection?session_id=${encodeURIComponent(oldSession)}`, {
      method: "DELETE", headers: {"X-AI-Connection": oldToken}
    }).catch(() => { /* Máy chủ vẫn tự hết hạn nếu không ngắt được do mất mạng. */ });
  });
  if (connectionToken) byId("connection-label").textContent = "Khóa cá nhân";
})();
