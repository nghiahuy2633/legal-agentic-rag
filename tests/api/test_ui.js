"use strict";
const assert=require("node:assert/strict");
const {test}=require("node:test");
const {readFileSync}=require("node:fs");
const vm=require("node:vm");
const {setup,open,prepared,report,next,descendants,text}=require("./helpers/ui.cjs");
const connectionSource=readFileSync(require("node:path").join(__dirname,"../../src/legal_rag/api/static/connection.js"),"utf8");
const system={available:true,provider:"provider.invalid",model:"test-model",mode:"system",connected:false,reconnect_required:false};

test("T44: mỗi bước là một màn hình, hỏi nghĩa vụ trở lại hội thoại",async()=>{
 const ui=await setup(); await open(ui,{report:report()});
 assert.equal(ui.ids["chat-panel"].hidden,true);
 await ui.fire(ui.ids["continue-groups"]);
 assert.equal(ui.ids["facts-stage"].hidden,true);assert.equal(ui.ids["groups-stage"].hidden,false);assert.equal(ui.ids["report-stage"].hidden,true);
 await ui.fire(ui.ids["view-report"]);assert.equal(ui.ids["report-stage"].hidden,false);
 await ui.fire(descendants(ui.ids["assessment-report"]).find(n=>n.tag==="button"&&n.textContent==="Hỏi về nghĩa vụ này"));
 assert.equal(ui.ids["chat-panel"].hidden,false);assert.equal(ui.ids["assessment-panel"].hidden,true);assert.equal(ui.ids["chat-context"].hidden,false);
});

test("T44: chat không tự gọi thêm LLM để trích dữ kiện",async()=>{
 const ui=await setup();await open(ui,{report:report()});const before=ui.calls.length;
 ui.ids.message.value="Tôi muốn hỏi thêm về một nghĩa vụ";
 ui.responses.push({data:{reply:"Trả lời thử",profile:{},process:{},total_ms:1,llm_calls:0}});
 await ui.fire(ui.ids["chat-form"],"submit");
 assert.equal(ui.calls.length,before+1);assert.equal(ui.calls.at(-1).url,"/api/chat");
 assert.equal(ui.ids["stale-notice"].hidden,false);
 assert.ok(descendants(ui.ids["assessment-report"]).filter(n=>n.dataset.check).every(n=>n.disabled));
});

test("T44: khóa cá nhân chỉ được gửi khi kết nối, lưu mã kết nối và xóa khi ngắt",async()=>{
 const ui=await setup();vm.runInContext(connectionSource,ui.context);
 ui.responses.push({data:system});await ui.fire(ui.ids["open-connection"]);
 assert.equal(ui.ids["connection-dialog"].open,true);
 ui.ids["mode-personal"].checked=true;ui.ids["mode-system"].checked=false;await ui.fire(ui.ids["mode-personal"],"change");
 assert.equal(ui.ids["personal-fields"].hidden,false);
 ui.ids["api-key"].value="personal-fixture-key";
 ui.responses.push({data:{...system,mode:"personal",connected:true,connection_token:"opaque-token"}});
 await ui.fire(ui.ids["connection-form"],"submit");
 assert.equal(ui.calls.at(-1).payload.api_key,"personal-fixture-key");
 assert.equal(ui.ids["api-key"].value,"");assert.equal(ui.storage.get("legal-rag-ai-token"),"opaque-token");
 assert.ok(![...ui.storage.values()].includes("personal-fixture-key"));
 ui.responses.push({data:system});await ui.fire(ui.ids["disconnect-ai"]);
 assert.equal(ui.calls.at(-1).headers["X-AI-Connection"],"opaque-token");
 assert.equal(ui.storage.has("legal-rag-ai-token"),false);assert.equal(ui.ids["connection-label"].textContent,"Kết nối AI");
});

test("T44: lỗi khóa không làm mất câu hỏi, đóng hộp xóa khóa đã nhập",async()=>{
 const ui=await setup();vm.runInContext(connectionSource,ui.context);
 ui.responses.push({data:system});await ui.fire(ui.ids["open-connection"]);
 ui.ids.message.value="Giữ câu hỏi của tôi";
 ui.ids["mode-personal"].checked=true;ui.ids["mode-system"].checked=false;ui.ids["api-key"].value="invalid-fixture-key";
 ui.responses.push({ok:false,status:401,data:{detail:"Khóa không hợp lệ."}});await ui.fire(ui.ids["connection-form"],"submit");
 assert.equal(ui.ids["connection-error"].textContent,"Khóa không hợp lệ.");assert.equal(ui.ids.message.value,"Giữ câu hỏi của tôi");
 assert.equal(ui.ids.send.disabled,false);assert.equal(ui.storage.has("legal-rag-ai-token"),false);
 await ui.fire(ui.ids["close-connection"]);assert.equal(ui.ids["api-key"].value,"");assert.equal(ui.ids["api-key"].type,"password");
});

test("T44: phiên mới ngắt kết nối của phiên trước",async()=>{
 const ui=await setup();vm.runInContext(connectionSource,ui.context);
 ui.responses.push({data:system});await ui.fire(ui.ids["open-connection"]);
 ui.ids["mode-personal"].checked=true;ui.ids["mode-system"].checked=false;ui.ids["api-key"].value="personal-fixture-key";
 ui.responses.push({data:{...system,mode:"personal",connected:true,connection_token:"opaque-token"}});await ui.fire(ui.ids["connection-form"],"submit");
 ui.responses.push({data:system});await ui.fire(ui.ids["new-session"]);
 assert.equal(ui.calls.at(-1).url,"/api/connection?session_id=session-1");assert.equal(ui.calls.at(-1).headers["X-AI-Connection"],"opaque-token");
 assert.equal(ui.storage.has("legal-rag-ai-token"),false);
});

test("T44: ngăn căn cứ hiển thị văn bản an toàn, mở nguyên văn và sao chép",async()=>{
 const ui=await setup();let copied="";
 ui.context.navigator={clipboard:{writeText:async value=>{copied=value;}}};
 ui.context.fixture=[{id:"E1",document_number:"Văn bản thử",article:"3",clause:"2",text:"Nội dung <script> ".repeat(70),source_url:"javascript:alert(1)"}];
 vm.runInContext("openEvidence(fixture,'E1')",ui.context);
 assert.equal(ui.ids["evidence-dialog"].open,true);
 assert.ok(text(ui.ids["evidence-content"]).includes("Điều 3"));
 assert.ok(descendants(ui.ids["evidence-content"]).some(n=>n.tag==="details"));
 assert.ok(!descendants(ui.ids["evidence-content"]).some(n=>n.tag==="a"||n.tag==="script"));
 await ui.fire(ui.ids["copy-evidence"]);assert.equal(copied,ui.context.fixture[0].text);
 await ui.fire(ui.ids["close-evidence"]);assert.equal(ui.ids["evidence-dialog"].open,false);
});

test("T44: máy chủ chưa có khóa mặc định hướng người dùng sang khóa cá nhân",async()=>{
 const ui=await setup();vm.runInContext(connectionSource,ui.context);
 ui.responses.push({data:{...system,system_available:false}});await ui.fire(ui.ids["open-connection"]);
 assert.equal(ui.ids["mode-system"].disabled,true);assert.equal(ui.ids["mode-personal"].checked,true);
 assert.equal(ui.ids["personal-fields"].hidden,false);assert.equal(ui.ids["save-connection"].textContent,"Kiểm tra & kết nối");
 assert.ok(ui.ids["connection-status"].textContent.includes("chưa có khóa mặc định"));
});

test("Chọn model: chỉ hiện khi có nhiều model, gửi header cho thao tác sau, chọn lại mặc định thì bỏ header",async()=>{
 const ui=await setup();vm.runInContext(connectionSource,ui.context);
 ui.responses.push({data:system});await ui.fire(ui.ids["open-connection"]);
 assert.equal(ui.ids["model-select"].hidden,true);assert.equal(ui.ids["connection-model"].hidden,false);
 const many={...system,models:["test-model","other-model"]};
 ui.responses.push({data:many});await ui.fire(ui.ids["open-connection"]);
 assert.equal(ui.ids["model-select"].hidden,false);assert.equal(ui.ids["connection-model"].hidden,true);
 assert.deepEqual(ui.ids["model-select"].children.map(n=>n.value),["test-model","other-model"]);
 assert.equal(ui.ids["model-select"].value,"test-model");
 ui.ids["model-select"].value="other-model";await ui.fire(ui.ids["model-select"],"change");
 ui.ids.message.value="Câu hỏi thử";ui.responses.push({data:{reply:"Trả lời thử",profile:{},process:{},total_ms:1,llm_calls:0}});
 await ui.fire(ui.ids["chat-form"],"submit");
 assert.equal(ui.calls.at(-1).url,"/api/chat");assert.equal(ui.calls.at(-1).headers["X-AI-Model"],"other-model");
 ui.ids["model-select"].value="test-model";await ui.fire(ui.ids["model-select"],"change");
 ui.ids.message.value="Câu hỏi thứ hai";ui.responses.push({data:{reply:"Trả lời thử",profile:{},process:{},total_ms:1,llm_calls:0}});
 await ui.fire(ui.ids["chat-form"],"submit");
 assert.equal(ui.calls.at(-1).headers["X-AI-Model"],undefined);
});
