"use strict";
const assert = require("node:assert/strict");
const {test} = require("node:test");
const {setup, open, prepared, report, next, descendants, text} = require("./helpers/ui.cjs");

test("T43: chat là chính, mở đánh giá từ hội thoại và dùng chung phiên", async () => {
  const ui = await setup();
  assert.equal(ui.ids["assessment-panel"].hidden,true);
  assert.ok(ui.calls.every(call => call.url.includes("/state?")));
  await open(ui);
  assert.equal(ui.ids["assessment-panel"].hidden,false);
  assert.equal(ui.calls[1].url,"/api/assess/start");
  assert.equal(ui.calls[1].payload.session_id,ui.storage.get("legal-rag-session"));
  assert.ok(text(ui.ids["facts-table"]).includes("<img src=x>"));
  assert.ok(!descendants(ui.ids["facts-table"]).some(node => node.tag === "img"));
  assert.ok(text(ui.ids["facts-table"]).includes("Bắt buộc"));
  assert.equal(ui.ids["group-progress"].textContent,"Đã hỏi 0/3 nhóm");
  assert.ok(!ui.storage.has("legal-rag-assessment"));
});

test("T43: trả lời, bỏ qua nhóm và tách độ đủ thông tin khỏi tuân thủ", async () => {
  const ui=await setup(); await open(ui);
  ui.ids["group-answer"].value="Đã gắn nhãn AI";
  ui.responses.push({data:{report:report(),stale:false,next:next(1)}});
  await ui.fire(ui.ids["group-form"],"submit");
  assert.deepEqual(ui.calls.at(-1).payload,{session_id:"session-1",group:"minh_bach",text:"Đã gắn nhãn AI",unknown:false});
  assert.equal(ui.ids["group-progress"].textContent,"Đã hỏi 1/3 nhóm");
  const rendered=text(ui.ids["assessment-report"]);
  assert.ok(rendered.includes("Độ đủ thông tin") && rendered.includes("2/3"));
  assert.ok(rendered.includes("1 đáp ứng") && rendered.includes("1 chưa đáp ứng trong 2"));
  assert.ok(rendered.includes("Cần xác minh"));
  assert.ok(!descendants(ui.ids["assessment-report"]).some(node=>["script","img"].includes(node.tag)));
  ui.responses.push({data:{report:report(),stale:false,next:next(2)}});
  await ui.fire(ui.ids["group-unknown"]);
  assert.equal(ui.calls.at(-1).payload.unknown,true);
  assert.equal(ui.calls.at(-1).payload.text,"");
  assert.equal(ui.ids["group-progress"].textContent,"Đã hỏi 2/3 nhóm");
});

test("T43: kịch bản xấu nhất không gọi API, tải danh sách và hỏi tiếp có context", async () => {
  const ui=await setup(); await open(ui,{report:report()});
  const calls=ui.calls.length;
  ui.ids["worst-case"].checked=true; await ui.fire(ui.ids["worst-case"],"change");
  assert.equal(ui.calls.length,calls);
  assert.ok(text(ui.ids["assessment-report"]).includes("2 chưa đáp ứng trên 3"));
  assert.ok(text(ui.ids["assessment-report"]).includes("từ hội thoại"));
  await ui.fire(ui.ids["verification-download"]);
  assert.ok((await ui.downloads[0].text()).includes("Nghĩa vụ thử 3"));
  assert.ok(!(await ui.downloads[0].text()).includes("Nghĩa vụ thử 1"));
  const ask=descendants(ui.ids["assessment-report"]).find(n=>n.tag==="button" && n.textContent==="Hỏi về nghĩa vụ này");
  await ui.fire(ask);
  assert.ok(ui.ids.message.value.includes("Nghĩa vụ thử 2"));
  ui.responses.push({data:{reply:"Trả lời thử",profile:{},process:{},total_ms:1,llm_calls:0}},
    {data:prepared},{data:{...prepared,report:report()}},{data:next(2)});
  await ui.fire(ui.ids["chat-form"],"submit");
  const chat=ui.calls.find(call=>call.url==="/api/chat");
  assert.deepEqual(chat.payload.context,{obligation_id:"ob-1"});
  assert.equal(chat.payload.session_id,"session-1");
});

test("T43: sửa dữ kiện giữ bản cũ, khóa tự kiểm khi stale, xử lý 409", async () => {
  const ui=await setup(); await open(ui,{report:report()});
  const select=descendants(ui.ids["facts-table"]).find(n=>n.id==="fact-risk_level").querySelector("select");
  select.value="cao";
  ui.responses.push({data:{...prepared,stale:true}},{data:next()});
  await ui.fire(select,"change");
  assert.equal(ui.ids["stale-notice"].hidden,false);
  assert.ok(text(ui.ids["assessment-report"]).includes("2/3"));
  assert.ok(descendants(ui.ids["assessment-report"]).filter(n=>n.dataset.check).every(n=>n.disabled));
  ui.responses.push({data:prepared},{data:{...prepared,stale:false,report:report()}},{data:next()});
  await ui.fire(ui.ids["refresh-assessment"]);
  const check=descendants(ui.ids["assessment-report"]).find(n=>n.dataset.check && n.textContent==="Có");
  ui.responses.push({ok:false,status:409,data:{detail:"Dữ kiện đã đổi. Vui lòng đánh giá lại."}});
  await ui.fire(check);
  assert.equal(ui.ids["stale-notice"].hidden,false);
  assert.ok(ui.ids["assessment-error"].textContent.includes("Dữ kiện đã đổi"));
});

test("T43: lỗi giữ câu trả lời, phiên mới xóa cả chat và đánh giá", async () => {
  const ui=await setup(); await open(ui,{report:report()});
  ui.ids["group-answer"].value="Giữ câu trả lời";
  ui.responses.push({ok:false,status:503,data:{detail:"Dịch vụ tạm thời không khả dụng."}});
  await ui.fire(ui.ids["group-form"],"submit");
  assert.equal(ui.ids["group-answer"].value,"Giữ câu trả lời");
  assert.equal(ui.ids["new-session"].disabled,false);
  const old=ui.storage.get("legal-rag-session"); await ui.fire(ui.ids["new-session"]);
  assert.notEqual(ui.storage.get("legal-rag-session"),old);
  assert.equal(ui.ids["group-answer"].value,"");
  assert.equal(ui.ids["facts-table"].children.length,0);
  assert.equal(ui.ids["assessment-download"].hidden,true);
  assert.equal(ui.ids["assessment-panel"].hidden,true);
});

test("T40/T43: trường liên quan và điều hướng mở trường ẩn", async () => {
  const ui=await setup();
  const data={...prepared,facts:{...prepared.facts,roles:["ben_trien_khai"],generates_content:false,is_public_sector:false},fields:{...prepared.fields},labels:{...prepared.labels},questions:[{field:"content_may_mislead",question:"Có gây nhầm lẫn?"}]};
  for(const name of ["content_may_mislead","uses_personal_data","modified_by_deployer","public_decision_use"]){data.facts[name]=null;data.fields[name]={type:"bool"};data.labels[name]=name;}
  ui.responses.push({data},{data:{...data,report:null}},{data:next()}); await ui.fire(ui.ids["open-assessment"]);
  const [required,extra,all]=ui.ids["facts-table"].children;
  assert.ok(descendants(required).some(n=>n.id==="fact-roles"));
  assert.ok(descendants(extra).some(n=>n.id==="fact-content_may_mislead"));
  assert.ok(descendants(extra).some(n=>n.id==="fact-modified_by_deployer"));
  assert.ok(descendants(all).some(n=>n.id==="fact-uses_personal_data"));
  const r=report();r.todo=[{type:"bo_sung_du_kien",field:"uses_personal_data",text:"Bổ sung dữ kiện"}];
  ui.responses.push({data:{report:r,stale:false,next:next(1)}});ui.ids["group-answer"].value="Trả lời thử";await ui.fire(ui.ids["group-form"],"submit");
  await ui.fire(descendants(ui.ids["assessment-report"]).find(n=>n.tag==="button" && n.textContent==="Bổ sung dữ kiện"));
  assert.equal(all.open,true);
});

test("T43: khôi phục báo cáo sau tải lại nhưng không tự mở đánh giá", async () => {
  const ui=await setup([{data:{...prepared,report:report(),stale:false}},{data:next(2)}]);
  assert.equal(ui.ids["assessment-panel"].hidden,true);
  assert.ok(text(ui.ids["assessment-report"]).includes("2/3"));
  assert.equal(ui.ids["group-progress"].textContent,"Đã hỏi 2/3 nhóm");
});
