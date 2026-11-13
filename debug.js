// RG DS 한워드 — 디버그/헤드리스 테스트 브리지. ?debug=1 일 때만 로드.
//   console/onerror 수집 + 서버 명령 큐 폴링 실행(curl로 라이브 cog 원격 구동).
(function () {
  "use strict";
  function post(path, obj) {
    return fetch(path, { method:"POST", headers:{ "Content-Type":"application/json" }, body:JSON.stringify(obj) })
      .then(function (r) { return r.json(); }).catch(function () {});
  }
  // 1) 콘솔/에러 → 서버 로그 (cog 콘솔 못 보는 문제 해결)
  function send(level, args) {
    var msg = Array.prototype.map.call(args, function (a) {
      try { return typeof a === "object" ? JSON.stringify(a) : String(a); } catch (e) { return String(a); }
    }).join(" ");
    post("/api/debug/log", { level: level, msg: msg });
  }
  ["log","warn","error","info"].forEach(function (m) {
    var orig = console[m] ? console[m].bind(console) : function () {};
    console[m] = function () { orig.apply(null, arguments); send(m, arguments); };
  });
  window.addEventListener("error", function (e) { send("error", ["onerror:", e.message, "@"+e.filename+":"+e.lineno]); });
  window.addEventListener("unhandledrejection", function (e) { send("error", ["reject:", (e.reason && e.reason.message) || e.reason]); });

  // 2) 상태 스냅샷
  function snap() {
    var page = document.getElementById("page"), sel = window.getSelection(), dn = document.getElementById("docname");
    var q = function (c) { try { return document.queryCommandState(c); } catch (e) { return null; } };
    return {
      docname: dn ? dn.value : null,
      htmlLen: page ? page.innerHTML.length : 0,
      text: page ? page.innerText.slice(0, 200) : "",
      selText: sel ? String(sel).slice(0, 120) : "",
      bold: q("bold"), italic: q("italic"), underline: q("underline"),
      menus: document.querySelectorAll("#menubar .mb").length,
      toolbarBtns: document.querySelectorAll("#toolbar [data-act]").length,
      dialogsOpen: Array.prototype.filter.call(document.querySelectorAll(".modal"), function (m) { return !m.classList.contains("hidden"); }).map(function (m) { return m.id; }),
      status: (document.getElementById("status") || {}).textContent
    };
  }
  function ser(v) { try { return typeof v === "object" ? JSON.parse(JSON.stringify(v)) : v; } catch (e) { return String(v); } }

  // ── 마우스/포인터 실험 헬퍼(실제 이벤트 시퀀스 발행) ──
  function elAt(x, y) { return document.elementFromPoint(x, y) || document.body; }
  function ctr(el) { var r = el.getBoundingClientRect(); return { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2) }; }
  function pev(type, x, y, el, btn) {
    var down = /down|move/.test(type);
    el.dispatchEvent(new PointerEvent("pointer" + type, { bubbles:true, cancelable:true, composed:true, view:window,
      clientX:x, clientY:y, pointerId:1, pointerType:"touch", isPrimary:true, button:btn||0, buttons:down?(btn===2?2:1):0 }));
  }
  function mev(type, x, y, el, btn) {
    var down = /down|move/.test(type);
    el.dispatchEvent(new MouseEvent("mouse" + type, { bubbles:true, cancelable:true, composed:true, view:window,
      clientX:x, clientY:y, button:btn||0, buttons:down?(btn===2?2:1):0 }));
  }
  // 한 지점 탭(pointerdown→up→click) — pointerup 기반 UI 검증용
  function tapAt(x, y, btn) {
    var el = elAt(x, y); pev("down", x, y, el, btn); mev("down", x, y, el, btn);
    pev("up", x, y, el, btn); mev("up", x, y, el, btn);
    if (!btn) el.dispatchEvent(new MouseEvent("click", { bubbles:true, cancelable:true, composed:true, view:window, clientX:x, clientY:y }));
    return el;
  }
  // 드래그(pointerdown→move*→up) — 드래그 선택/창 검증용
  function dragXY(x1, y1, x2, y2, steps) {
    steps = steps || 8; var el = elAt(x1, y1);
    pev("down", x1, y1, el); mev("down", x1, y1, el);
    for (var i = 1; i <= steps; i++) { var x = Math.round(x1 + (x2 - x1) * i / steps), y = Math.round(y1 + (y2 - y1) * i / steps); var t = elAt(x, y); pev("move", x, y, t); mev("move", x, y, t); }
    var end = elAt(x2, y2); pev("up", x2, y2, end); mev("up", x2, y2, end);
    return { from:[x1, y1], to:[x2, y2], selText: String(window.getSelection()).slice(0, 120) };
  }
  // 키 시퀀스(keydown+keyup, 모디파이어) — 각 항목 "ctrl+shift+a" 형식 또는 단일 키
  function pressKey(spec) {
    var p = String(spec).split("+"), key = p.pop();
    var mod = { ctrl:p.indexOf("ctrl")>=0, alt:p.indexOf("alt")>=0, shift:p.indexOf("shift")>=0 };
    var o = { key:key, ctrlKey:mod.ctrl, altKey:mod.alt, shiftKey:mod.shift, bubbles:true, cancelable:true, composed:true };
    var tgt = (document.activeElement && document.activeElement !== document.body) ? document.activeElement : document;
    tgt.dispatchEvent(new KeyboardEvent("keydown", o));
    tgt.dispatchEvent(new KeyboardEvent("keyup", o));
    return key;
  }

  // 3) 명령 실행
  function run(cmd) {
    try {
      var op = cmd.op, arg = cmd.arg, page = document.getElementById("page");
      if (op === "snapshot") return { ok:true, html: page.innerHTML, state: snap() };
      if (op === "state")    return { ok:true, state: snap() };
      if (op === "eval")     return { ok:true, value: ser(Function('"use strict";return (' + cmd.js + ')')()) };
      if (op === "dispatch") { if (window.WP && window.WP.dispatch) { window.WP.dispatch(arg); return { ok:true, state: snap() }; } return { ok:false, err:"WP.dispatch 없음" }; }
      if (op === "type")     {
        page.focus();
        var s = window.getSelection();
        if (!s.rangeCount || !page.contains(s.anchorNode)) {   // 캐럿 없으면 문서 끝에 둠(결정성)
          var r = document.createRange(); r.selectNodeContents(page); r.collapse(false); s.removeAllRanges(); s.addRange(r);
        }
        document.execCommand("insertText", false, arg || ""); return { ok:true, state: snap() };
      }
      if (op === "setHTML")  { page.innerHTML = arg || "<p><br></p>"; return { ok:true }; }
      if (op === "click")    { var el = document.querySelector(arg); if (!el) return { ok:false, err:"no element "+arg }; var c = ctr(el); tapAt(c.x, c.y, cmd.button || 0); return { ok:true, at:c, state: snap() }; }
      if (op === "tap")      { var el2 = document.querySelector(arg); if (!el2) return { ok:false, err:"no element "+arg }; var c2 = ctr(el2); tapAt(c2.x, c2.y, cmd.button || 0); return { ok:true, at:c2, state: snap() }; }
      if (op === "rect")     { var el3 = document.querySelector(arg); if (!el3) return { ok:false, err:"no element "+arg }; var r = el3.getBoundingClientRect(); return { ok:true, rect:{ x:Math.round(r.left), y:Math.round(r.top), w:Math.round(r.width), h:Math.round(r.height), cx:Math.round(r.left+r.width/2), cy:Math.round(r.top+r.height/2) } }; }
      if (op === "at")       { var e4 = elAt(cmd.x, cmd.y); return { ok:true, tag:e4.tagName, id:e4.id, cls:e4.className, act:e4.getAttribute && e4.getAttribute("data-act"), text:(e4.textContent||"").slice(0,40) }; }
      if (op === "point")    { var s4 = cmd.sub || "tap"; if (s4 === "tap") tapAt(cmd.x, cmd.y, cmd.button||0); else { var t4 = elAt(cmd.x, cmd.y); pev(s4, cmd.x, cmd.y, t4, cmd.button||0); mev(s4, cmd.x, cmd.y, t4, cmd.button||0); } return { ok:true, state: snap() }; }
      if (op === "drag")     { var d = dragXY(cmd.x, cmd.y, cmd.x2, cmd.y2, cmd.steps); return { ok:true, drag:d, state: snap() }; }
      if (op === "rclick" || op === "contextmenu") { var t5 = elAt(cmd.x, cmd.y); t5.dispatchEvent(new MouseEvent("contextmenu", { bubbles:true, cancelable:true, composed:true, view:window, clientX:cmd.x, clientY:cmd.y, button:2 })); return { ok:true, state: snap() }; }
      if (op === "key")      { document.dispatchEvent(new KeyboardEvent("keydown", { key:cmd.key, ctrlKey:!!cmd.ctrl, altKey:!!cmd.alt, shiftKey:!!cmd.shift, bubbles:true, cancelable:true })); return { ok:true, state: snap() }; }
      if (op === "press")    { var ks = pressKey((cmd.combo) || ((cmd.ctrl?"ctrl+":"")+(cmd.alt?"alt+":"")+(cmd.shift?"shift+":"")+cmd.key)); return { ok:true, key:ks, state: snap() }; }
      if (op === "keyseq")   { (cmd.keys || []).forEach(function (k) { pressKey(k); }); return { ok:true, n:(cmd.keys||[]).length, state: snap() }; }
      return { ok:false, err:"unknown op " + op };
    } catch (e) { return { ok:false, err: String(e && e.stack || e) }; }
  }

  // 4) 폴링 루프(자가복구: setInterval 기반 + fetch 타임아웃으로 hang 시에도 안 멎음) + 상태 하트비트
  var busy = false;
  function tick() {
    if (busy) return;                               // 이전 요청 진행 중이면 건너뜀(중첩 방지)
    busy = true;
    var done = false, fin = function () { if (!done) { done = true; busy = false; } };
    var ac = (typeof AbortController !== "undefined") ? new AbortController() : null;
    var to = setTimeout(function () { try { if (ac) ac.abort(); } catch (e) {} fin(); }, 4000);   // hang 방지
    fetch("/api/debug/cmd", ac ? { signal: ac.signal } : undefined)
      .then(function (r) { return r.json(); })
      .then(function (cmd) { if (cmd && cmd.op) { var res = run(cmd); post("/api/debug/result", { id: cmd.id, result: res }); } })
      .catch(function () {})
      .then(function () { clearTimeout(to); fin(); });
  }
  setInterval(tick, 250);
  setInterval(function () { post("/api/debug/state", snap()); }, 2000);
  send("info", ["debug bridge up"]);
})();
