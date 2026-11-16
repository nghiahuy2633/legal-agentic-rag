"use strict";

// Kiểm tra logic JS bằng DOM giả, không mở trình duyệt hoặc gọi mạng.
const assert = require("node:assert/strict");
const {readFileSync} = require("node:fs");
const {join} = require("node:path");
const vm = require("node:vm");
const {test} = require("node:test");
const source = readFileSync(join(__dirname, "../../src/legal_rag/api/static/app.js"), "utf8");

class Element {
  constructor(tag) {
    this.tag = tag; this.children = []; this.handlers = {}; this.value = "";
    this.disabled = false; this.innerHTML = ""; this.textContent = "";
  }
  append(node) { this.children.push(node); }
  replaceChildren(...nodes) { this.children = nodes; this.innerHTML = nodes.map(node => node.renderedHTML || "").join(""); }
  addEventListener(name, handler) { this.handlers[name] = handler; }
  focus() {}
  scrollIntoView() {}
}

function runtime() {
  const ids = Object.fromEntries(["chat", "message", "send", "new-session", "waiting", "profile", "chat-form"]
    .map(id => [id, new Element(id)]));
  const storage = new Map();
  let serial = 0, timers = 0;
  const context = vm.createContext({
    document: {getElementById: id => ids[id], createElement: tag => new Element(tag)},
    sessionStorage: {getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value)},
    crypto: {randomUUID: () => `session-${++serial}`}, URL, Date, EventTarget, Event,
    DOMParser: class {
      parseFromString(html) { const node = new Element("fragment"); node.renderedHTML = html; return {body: {childNodes: [node]}}; }
    },
    setInterval: () => { timers++; return timers; }, clearInterval: () => { timers--; },
    fetch: () => { throw Error("Chưa đặt phản hồi giả"); }
  });
  vm.runInContext(source + "\nglobalThis.api = {markdown, showAnswer, showEvidence};", context);
  return {context, ids, storage, timers: () => timers};
}

function allText(node) { return [node.textContent, ...node.children.map(allText)].join("\n"); }
function answer(text, evidence) {
  return {reply: text, evidence, profile: {}, process: {nodes: [], evidence: [], check: {}},
    llm_calls: 1, total_ms: 12};
}

test("T26: tiêu đề cấp ba escape và trạng thái nằm trong mục số", () => {
  const {context} = runtime();
  assert.equal(context.api.markdown("### A<b>"), "<h3>A&lt;b&gt;</h3>");
  const output = context.api.markdown("1. Một\n\n   Trạng thái: <chưa rõ>\n\n2. Hai");
  assert.equal(output, '<ol><li value="1">Một<p>Trạng thái: &lt;chưa rõ&gt;</p></li><li value="2">Hai</li></ol>');
});

test("T26: thu gọn theo mốc, giữ tiêu đề khác và câu kết bên ngoài", () => {
  const {context} = runtime();
  const closing = "Đây là hướng dẫn sơ bộ, không phải tư vấn pháp lý.";
  const output = context.api.markdown("## Đối chiếu\n### Lĩnh vực y tế\nCăn cứ cần xem xét:\nĐiều kiện <b>\n## Nghĩa vụ cần xem xét\nNghĩa vụ\n## Căn cứ pháp lý\n\n[E1.đ] Căn cứ một\n[E2] Căn cứ hai\n\n" + closing);
  assert.equal((output.match(/<details>/g) || []).length, 2);
  assert.ok(!/<details[^>]*\bopen\b/.test(output));
  assert.ok(output.includes('<summary>Xem nguyên văn tiêu chí xác định và tiêu chí loại trừ</summary><p>Căn cứ cần xem xét:</p><p>Điều kiện &lt;b&gt;</p></details><h2>Nghĩa vụ cần xem xét</h2>'));
  assert.ok(output.includes('<summary>Căn cứ pháp lý (2)</summary>'));
  assert.ok(output.includes('data-citation="E1.đ"'));
  assert.ok(output.endsWith(`</details><p>${closing}</p>`));
  const next = context.api.markdown("## Căn cứ pháp lý\n[E1] Một\n## Mục khác\nCòn mở");
  assert.ok(next.includes('</details><h2>Mục khác</h2><p>Còn mở</p>'));
  assert.ok(context.api.markdown(`Căn cứ cần xem xét\nNguyên văn\n${closing}`).endsWith(`</details><p>${closing}</p>`));
});

test("T26: nguồn cuối dòng chỉ liên kết HTTP(S), escape riêng href", () => {
  const {context} = runtime();
  const output = context.api.markdown('[E1] A<b> https://a.vn/x?y=1&z=2');
  assert.ok(output.includes('A&lt;b&gt; <a href="https://a.vn/x?y=1&amp;z=2" target="_blank" rel="noopener noreferrer">Nguồn</a>'));
  assert.ok(context.api.markdown('Nguồn http://a.vn/x').includes('href="http://a.vn/x"'));
  for (const url of ['javascript:alert(1)', 'data:text/html,<b>', 'ftp://a.vn/x', 'https://']) {
    assert.ok(!context.api.markdown(`Căn cứ ${url}`).includes('<a '));
  }
  const hostile = context.api.markdown('Căn cứ https://a.vn/"onclick="x**<b>');
  assert.ok(hostile.includes('&quot;onclick=&quot;x**&lt;b&gt;'));
  assert.ok(!hostile.includes('<b>') && !hostile.includes('<strong>'));
  assert.ok(!context.api.markdown('https://a.vn/x còn chữ').includes('<a '));
});

test("Markdown escape nội dung trước định dạng và tạo nút mã E gộp", () => {
  const {context} = runtime();
  const output = context.api.markdown('## <img src=x onerror=alert(1)>\n**đậm**\n* mục\n- mục khác\n1. số\n[E1, E3.b]\n[E2.đ]\nLưu ý: một số nội dung…');
  assert.ok(output.includes("&lt;img"));
  assert.ok(!output.includes("<img"));
  assert.ok(output.includes("<strong>đậm</strong>"));
  assert.ok(output.includes("<ul>") && output.includes("<ol>"));
  for (const marker of ["E1", "E3.b", "E2.đ"]) assert.ok(output.includes(`data-citation="${marker}"`));
  assert.ok(output.includes("Lưu ý: một số nội dung…"));
  assert.ok(context.api.markdown('<script>"&\'</script>').includes("&lt;script&gt;&quot;&amp;&#39;&lt;/script&gt;"));
});

test("Mã E mở đúng căn cứ của từng tin nhắn và chặn URL thực thi", () => {
  const {context, ids} = runtime();
  const firstAnswer = answer("Đáp\n## Căn cứ pháp lý\n[E1.đ] Một\nĐây là hướng dẫn sơ bộ, không phải tư vấn pháp lý.",
    [{id: "E1", text: "đ) Nguyên văn lượt một", source_url: "javascript:alert(1)"}]);
  const original = JSON.stringify(firstAnswer);
  context.api.showAnswer(firstAnswer);
  assert.equal(JSON.stringify(firstAnswer), original);
  context.api.showAnswer(answer("Đáp [E1]", [{id: "E1", text: "Nguyên văn lượt hai", source_url: "https://example.invalid/nguon"}]));
  const [first, second] = ids.chat.children;
  assert.ok(first.children[1].innerHTML.includes('<details><summary>Căn cứ pháp lý (1)</summary><p><button type="button" class="citation" data-citation="E1.đ"'));
  first.children[1].handlers.click({target: {closest: () => ({dataset: {citation: "E1.đ"}})}});
  assert.equal(first.children[2].open, true);
  second.children[1].handlers.click({target: {closest: () => ({dataset: {citation: "E1"}})}});
  const firstBox = first.children[2].children[1];
  const secondBox = second.children[2].children[1];
  assert.ok(allText(firstBox).includes("Nguyên văn lượt một"));
  assert.ok(!allText(firstBox).includes("Nguyên văn lượt hai"));
  assert.ok(allText(firstBox).includes("Điểm đ"));
  assert.ok(allText(secondBox).includes("Nguyên văn lượt hai"));
  assert.ok(!firstBox.children.some(node => node.tag === "a"));
  const link = secondBox.children.find(node => node.tag === "a");
  assert.equal(link.rel, "noopener noreferrer");
  assert.equal(link.target, "_blank");
});

test("422, 500, mất kết nối giữ đầu vào và khôi phục nút gửi", async () => {
  for (const kind of [422, 500, "network"]) {
    const {context, ids, timers} = runtime();
    ids.message.value = "Nội dung cần giữ lại";
    context.fetch = async () => {
      assert.equal(ids.send.disabled, true);
      assert.ok(ids.waiting.textContent.startsWith("Đang xử lý…"));
      if (kind === "network") throw Error("PRIVATE");
      return {ok: false, status: kind, json: async () => ({detail: [{msg: "Tin nhắn không hợp lệ."}]})};
    };
    await ids["chat-form"].handlers.submit({preventDefault() {}});
    assert.equal(ids.message.value, "Nội dung cần giữ lại");
    assert.equal(ids.send.disabled, false);
    assert.equal(ids["new-session"].disabled, false);
    assert.equal(ids.message.readOnly, false);
    assert.equal(timers(), 0);
    assert.equal(ids.chat.children.at(-1).className, "error");
    assert.ok(!allText(ids.chat).includes("PRIVATE"));
  }
});

test("Phiên mới đổi mã, xóa chat và hồ sơ; thành công mới xóa ô nhập", async () => {
  const {context, ids, storage} = runtime();
  const oldSession = storage.get("legal-rag-session");
  ids.message.value = "Mô tả AI";
  context.fetch = async (url, options) => {
    assert.equal(url, "/api/chat");
    assert.equal(JSON.parse(options.body).session_id, oldSession);
    return {ok: true, json: async () => answer("Đáp", [])};
  };
  await ids["chat-form"].handlers.submit({preventDefault() {}});
  assert.equal(ids.message.value, "");
  assert.equal(ids.chat.children.length, 2);
  ids["new-session"].handlers.click();
  assert.notEqual(storage.get("legal-rag-session"), oldSession);
  assert.equal(ids.chat.children.length, 0);
  assert.equal(ids.profile.children.filter(node => node.textContent === "Chưa rõ").length, 5);
});

test("T30: lỗi hạn mức ngày qua HTTP 200 giữ câu nhập để gửi lại", async () => {
  const {context, ids, timers} = runtime();
  const message = "AI của tôi có rủi ro cao không?";
  const quota = "Dịch vụ AI đã hết lượt trong ngày, vui lòng thử lại sau khoảng 6 giờ.";
  ids.message.value = message;
  context.fetch = async () => ({ok: true, json: async () => ({...answer(quota, []), route: "error", error: quota})});
  await ids["chat-form"].handlers.submit({preventDefault() {}});
  assert.equal(ids.message.value, message);
  assert.ok(ids.chat.children[1].children[1].innerHTML.includes(quota));
  assert.equal(ids.send.disabled, false);
  assert.equal(ids.message.readOnly, false);
  assert.equal(timers(), 0);
});
