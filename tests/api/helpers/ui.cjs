"use strict";
const {readFileSync} = require("node:fs");
const {join} = require("node:path");
const vm = require("node:vm");
class Element {
  constructor(tag) {
    this.tag = tag; this.tagName = tag.toUpperCase(); this.children = []; this.handlers = {}; this.attrs = {};
    this.value = ""; this.disabled = false; this.textContent = ""; this.dataset = {}; this.hidden = false;
    const classes = new Set(); this.classList = {toggle: (key, value) => value ? classes.add(key) : classes.delete(key), contains: key => classes.has(key)};
  }
  append(node) { node.parentElement = this; this.children.push(node); }
  replaceChildren(...nodes) { this.children = []; nodes.forEach(node => this.append(node)); }
  setAttribute(key, value) { this.attrs[key] = value; }
  hasAttribute(key) { return key === "href" ? Boolean(this.href) : key in this.attrs; }
  removeAttribute(key) { delete this.attrs[key]; if (key === "href") delete this.href; }
  addEventListener(name, fn) { (this.handlers[name] ||= []).push(fn); }
  querySelectorAll(selector) { return this.children.flatMap(node => [...(selector.split(/,\s*/).includes(node.tag) ? [node] : []), ...node.querySelectorAll(selector)]); }
  querySelector(selector) { return this.querySelectorAll(selector)[0]; }
  focus() { this.focused = true; }
  scrollIntoView() { this.scrolled = true; }
  showModal() { this.open = true; }
  close() { this.open = false; (this.handlers.close || []).forEach(fn => fn()); }
  click() { (this.handlers.click || []).forEach(fn => fn({preventDefault(){}})); }
}
function descendants(node) { return [node, ...node.children.flatMap(descendants)]; }
function text(node) { return descendants(node).map(n => n.textContent).join("\n"); }
async function setup(restored) {
  const html = readFileSync(join(__dirname, "../../../src/legal_rag/api/static/index.html"), "utf8");
  const ids = Object.fromEntries([...html.matchAll(/id="([^"]+)"/g)].map(match => [match[1], new Element("div")]));
  ids["assessment-panel"].hidden = true;
  ids["mode-system"].checked = true; ids["api-key"].type = "password";
  const panel = ids["assessment-panel"];
  for (const id of ["facts-table", "fact-questions", "group-list", "assessment-report"]) panel.append(ids[id]);
  const storage = new Map(); let sequence = 0;
  const calls = [], responses = [], downloads = [];
  const url = class extends URL {};
  url.createObjectURL = blob => { downloads.push(blob); return "blob:test"; }; url.revokeObjectURL = () => {};
  const context = vm.createContext({
    document: {getElementById: id => ids[id] || descendants(panel).find(n => n.id === id), createElement: tag => new Element(tag), querySelectorAll: () => []},
    sessionStorage: {getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key)},
    crypto: {randomUUID: () => `session-${++sequence}`}, URL: url, Date, Blob, EventTarget, Event, setInterval, clearInterval,
    DOMParser: class { parseFromString(html) { const node = new Element("fragment"); node.renderedHTML = html; return {body: {childNodes: [node]}}; } },
    fetch: async (url, options = {}) => {
      const payload = options.body ? JSON.parse(options.body) : undefined; calls.push({url, payload, headers: options.headers});
      const response = responses.shift() || {ok:false,status:404,data:{detail:"Phiên không tồn tại"}};
      if (response instanceof Error) throw response;
      return {ok: response.ok !== false, status: response.status || 200, json: async () => response.data};
    }, TypeError, Error
  });
  if (restored) responses.push(...restored);
  vm.runInContext(readFileSync(join(__dirname, "../../../src/legal_rag/api/static/app.js"), "utf8"), context);
  vm.runInContext(readFileSync(join(__dirname, "../../../src/legal_rag/api/static/assessment.js"), "utf8"), context);
  async function settle() { for(let i=0;i<6;i++) await new Promise(resolve => setImmediate(resolve)); }
  async function fire(node, name = "click") { for(const fn of node.handlers[name] || []) fn({preventDefault(){}}); await settle(); }
  await settle();
  return {ids, calls, responses, context, storage, downloads, fire, settle};
}
const groups = ["minh_bach", "su_co", "chuyen_tiep"].map((group,i) => ({group, question:`Câu hỏi nhóm ${i+1}?`, obligations:[{id:`ob-${i}`,obligation:`Nghĩa vụ thử ${i+1}`}]}));
const prepared = {
  facts: {roles:["nha_cung_cap"],risk_level:"thap",interacts_with_humans:true},
  fields: {roles:{type:"list",values:["nha_cung_cap"]},risk_level:{type:"str",values:["thap","cao"]},interacts_with_humans:{type:"bool"}},
  labels: {roles:"Vai trò",risk_level:"Mức rủi ro",interacts_with_humans:"Tương tác với con người"},
  evidence:{roles:"Tôi là nhà cung cấp <img src=x>"},questions:[],ready:true,changes:[],errors:[],groups,stale:false
};
function next(index = 0) { return {...(groups[index] || {group:null,question:null,obligations:[]}),progress:{answered:Math.min(index,3),total:3}}; }
function report() {
  const rows = ["da","chua","chua_ro"].map((status,i) => ({id:`ob-${i}`,group:groups[i].group,obligation:`Nghĩa vụ thử ${i+1}`,applicability:"ap_dung",conditions:[],deadline:i===2?"trước khi đưa vào sử dụng":"",status,citations:[{label:"Căn cứ thử <script>"}],criteria:[{id:"c1",text:"Tiêu chí thử",status,quote:i===0?"Đã thực hiện <img>":"",source:"llm",evidence_source:i===0?"hoi_thoai":null}]}));
  return {summary:{total:3,da:1,chua:1,chua_ro:1,conditional_total:0},obligations:rows,warnings:[],todo:[],info:[],meta:{disclaimer:"Dữ liệu giả để kiểm thử, không phải kết luận pháp lý."}};
}
async function open(ui, state = {}) {
  ui.responses.push({data:prepared},{data:{...prepared,report:null,...state}},{data:next()});
  await ui.fire(ui.ids["open-assessment"]);
}
module.exports = {Element, descendants, text, setup, prepared, groups, next, report, open};
