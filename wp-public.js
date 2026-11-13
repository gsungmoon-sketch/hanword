// 한워드 — 공개(멀티유저) 모드. 서버측 공유 저장 대신 브라우저 업로드(load)/다운로드(save).
//   window.WP_PUBLIC=true 일 때만 동작(서버가 공개모드에서 주입). 파일 메뉴 동작을 교체.
(function () {
  "use strict";
  if (!window.WP_PUBLIC || window.WP_IFRAME) return;   // 임베드(?embed=1)는 공개모드 파일 UI·안내문·이탈경고 없음(wp-embed.js)
  var WP = window.WP, page = WP.page, docname = WP.docname,
      status = WP.status, toast = WP.toast, clean = WP.clean;

  function curName() { return ((docname.value || "문서").trim() || "문서").replace(/[\\/:*?"<>|]/g, ""); }
  function curHTML() { return WP.cleanedHTML ? WP.cleanedHTML() : page.innerHTML; }

  // ── 자기완결 HTML 문서로 내보내기: 일반 브라우저에서도 페이지 레이아웃(A4 폭·여백·표 테두리·배치·폰트) 보존 ──
  //   body 자체를 A4 페이지로 스타일 → 재업로드 시 sanitizeHtml이 head/style 제거 후 body.innerHTML만 취해 왕복 클린(래퍼 누적 0).
  //   editor.css 문서 규칙(:35,:94,:105-118,:125-129) 미러. cleanedHTML은 #page 내용이므로 #page 셀렉터 대신 요소 셀렉터 사용.
  var EXPORT_CSS =
    '*{box-sizing:border-box}' +
    'html{background:#e8e8e8;margin:0;padding:0}' +
    'body{width:210mm;max-width:100%;margin:20px auto;padding:24mm 20mm;background:#fff;color:#111;' +
    'box-shadow:0 1px 8px rgba(0,0,0,.3);position:relative;' +
    'font-family:"NotoKR","Noto Sans KR","NanumGothic",sans-serif;font-size:11pt;line-height:1.6;word-break:break-word}' +
    '@media(max-width:800px){body{width:auto;margin:0;padding:16px}}' +
    'h1{font-size:20pt;font-weight:700;margin:.4em 0 .3em}h2{font-size:16pt;font-weight:700;margin:.4em 0 .3em}h3{font-size:13pt;font-weight:700;margin:.4em 0 .3em}' +
    'p{margin:.25em 0}ul,ol{margin:.25em 0;padding-left:1.6em}img{max-width:100%}' +
    'table{border-collapse:collapse;margin:.4em 0}td,th{border:1px solid #555;padding:4px 8px;min-width:40px}' +
    '.objline{text-align:left;margin:.35em 0}.objline>table{display:inline-block;vertical-align:top;margin:0}' +
    '[data-place=fixed]{position:absolute;z-index:5;margin:0}' +
    '[data-place=float]{float:left;margin:2px 14px 8px 0}[data-place=float][data-fside=right]{float:right;margin:2px 0 8px 14px}';
  function fontFaceCSS() {   // 로드된 editor.css의 @font-face를 그대로 추출해 /font/ → 절대경로(타호스트·오프라인 대비)로. editor.css와 자동 동기화.
    var out = [], origin = location.origin;
    try {
      for (var i = 0; i < document.styleSheets.length; i++) {
        var rules; try { rules = document.styleSheets[i].cssRules; } catch (e) { continue; }   // 교차출처 시트는 건너뜀
        var fontBase = origin + "/"; try { fontBase = new URL(".", document.styleSheets[i].href || location.href).href; } catch (e) {}   // 하위 경로(/editor/) 배포 대응
        if (!rules) continue;
        for (var j = 0; j < rules.length; j++) {
          var r = rules[j];
          if (r.type === 5) out.push(r.cssText.replace(/url\(\s*(['"]?)\/?font\//g, "url($1" + fontBase + "font/"));   // 5 = CSSFontFaceRule (상대 font/ = 시트 기준)
        }
      }
    } catch (e) {}
    return out.join("\n");
  }
  function fullHtmlDoc(body, title) {
    return '<!DOCTYPE html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n' +
           '<meta name="viewport" content="width=device-width, initial-scale=1">\n' +
           '<title>' + WP.esc(title) + '</title>\n<style>\n' + fontFaceCSS() + '\n' + EXPORT_CSS + '\n</style>\n</head>\n' +
           '<body>' + body + '</body></html>';   // body 안·</body> 뒤 개행 금지(2026-07-19 P13): 파서가 body 꼬리 텍스트로 재부모화 → 역사 무결성(바이트 동일) 비교를 깨뜨림
  }

  function download(blob, fname) {            // 브라우저 다운로드 트리거
    var url = URL.createObjectURL(blob), a = document.createElement("a");
    a.href = url; a.download = fname; document.body.appendChild(a); a.click();
    setTimeout(function () { URL.revokeObjectURL(url); a.remove(); }, 1500);
  }
  function postFor(path, body) {              // 변환 요청 → 응답을 Blob(파일)로
    return fetch(path, { method: "POST", headers: { "Content-Type": "application/json" },
                         body: JSON.stringify(body) }).then(function (r) {
      if (!r.ok) return r.json().then(function (j) { throw new Error((j && j.err) || ("HTTP " + r.status)); });
      return r.blob();
    });
  }

  // ── 로컬 초안(IndexedDB): 크래시·모바일 탭 회수·새로고침 실수로 인한 편집 손실 방지 ──
  //    core의 markDirty 디바운스(1.5s)·visibilitychange·beforeunload가 save()→WP.draftPut을 호출.
  var _db = null;
  function idb() {
    return new Promise(function (res, rej) {
      if (_db) return res(_db);
      var rq = indexedDB.open("hanword", 2);   // v2(2026-07-19): wpHist 스토어 추가(P13 암호화 역사)
      rq.onupgradeneeded = function () {
        var db = rq.result;
        if (!db.objectStoreNames.contains("draft")) db.createObjectStore("draft");
        if (!db.objectStoreNames.contains("wpHist")) db.createObjectStore("wpHist");
      };
      rq.onsuccess = function () { _db = rq.result; res(_db); };
      rq.onerror = function () { rej(rq.error); };
    });
  }
  function hhmm(t) { var d = new Date(t); return ("0" + d.getHours()).slice(-2) + ":" + ("0" + d.getMinutes()).slice(-2); }
  var _lastDraft = "", _lastPutTs = 0, _deferTimer = null, _announced = false;
  var PUT_MIN = 30000;   // 쓰기 하한 30s — 디바운스(1.5s) 뒤 추가 억제. 숨김/닫기 flush는 하한 무시
  function draftPut(force) {
    try {
      if (!force && Date.now() - _lastPutTs < PUT_MIN) {   // 하한 내 편집분은 하한 만료 시점에 후행 저장 예약(방치 손실 방지)
        clearTimeout(_deferTimer);
        _deferTimer = setTimeout(function () { draftPut(); }, PUT_MIN - (Date.now() - _lastPutTs) + 100);
        return Promise.resolve();
      }
      var html = curHTML(), key = docname.value + " " + html.length + " " + html.slice(-64);
      if (key === _lastDraft) return Promise.resolve();   // 내용 변화 없으면 IDB 쓰기 생략
      _lastDraft = key; _lastPutTs = Date.now(); clearTimeout(_deferTimer);
      var rec = { name: docname.value, html: html, ts: _lastPutTs };
      histPersistPub(rec.name);   // P13-A: 암호 설정 시 역사 암호문도 같은 시점에 보관(미설정=no-op)
      return idb().then(function (db) {
        return new Promise(function (res) {
          var tx = db.transaction("draft", "readwrite");
          tx.objectStore("draft").put(rec, "current");
          tx.oncomplete = function () {   // 상태줄은 첫 보관 때 한 번만(잦은 갱신 소음 방지)
            if (!_announced) { _announced = true; status("초안 자동 보관 중 · 영구 보존은 내려받기"); }
            res();
          };
          tx.onerror = res;
        });
      }).catch(function () {});
    } catch (e) { return Promise.resolve(); }
  }
  // 탭 전환·닫기 직전엔 하한 무시하고 즉시 보관(모바일 탭 회수 대비 핵심 타이밍)
  document.addEventListener("visibilitychange", function () { if (document.hidden) draftPut(true); });
  window.addEventListener("beforeunload", function () { draftPut(true); });
  function draftGetKey(key) {
    return idb().then(function (db) {
      return new Promise(function (res) {
        var rq = db.transaction("draft").objectStore("draft").get(key);
        rq.onsuccess = function () { res(rq.result || null); };
        rq.onerror = function () { res(null); };
      });
    }).catch(function () { return null; });
  }
  function draftOp(fn) {   // readwrite 트랜잭션 헬퍼
    return idb().then(function (db) {
      return new Promise(function (res) {
        var tx = db.transaction("draft", "readwrite");
        fn(tx.objectStore("draft"));
        tx.oncomplete = res; tx.onerror = res;
      });
    }).catch(function () {});
  }
  function draftClear() {   // 다운로드/삭제 시: 복구 사본까지 모두 제거(+하한 리셋: 이후 첫 편집은 즉시 보관)
    _lastDraft = ""; _lastPutTs = 0; clearTimeout(_deferTimer);
    return draftOp(function (st) { st.delete("current"); st.delete("prev"); });
  }
  WP.draftPut = draftPut;   // core save()가 공개모드에서 호출
  function draftBanner(d) {
    var bar = document.createElement("div"); bar.id = "draftbar";
    bar.innerHTML = '<span>저장하지 않은 초안 — "' + WP.esc(d.name || "제목 없음") + '" (' + hhmm(d.ts) + ')</span>' +
      '<button class="ok" data-d="restore">복구</button><button data-d="del">삭제</button><button class="x" data-d="x">✕</button>';
    document.body.appendChild(bar);
    bar.addEventListener("pointerup", function (e) {
      var b = e.target.closest("[data-d]"); if (!b) return;
      var a = b.getAttribute("data-d");
      if (a === "restore") { setDoc(d.name, sanitizeHtml(d.html)); WP.markDirty(); toast("초안 복구됨 — 내려받아야 영구 보존됩니다"); histRestorePub(d.name, null); }
      else if (a === "del") { draftClear(); toast("초안 삭제됨"); }
      bar.remove();
    });
  }
  // ── P13 공개모드 편집 역사 보존(2026-07-19 사용자 승인 설계, 옵트인): 암호(_histPw) 설정된 경우만 동작·미설정=완전 꺼짐 ──
  //    A안 = IDB wpHist 스토어(키=문서명)에 WebCrypto(PBKDF2 SHA256 20만회→AES-GCM, salt16+iv12) 암호문 보관
  //    C안 = HTML 내려받기에 <script type="application/x-wp-hist" hidden>WPH2:… 동봉(표준 HTML·렌더 무영향)
  //    복원 = 기기 restoreHistFlow 미러: 세션pw 자동 시도→모달, adoptHist 무결성 검증, 오답=거부만(삭제 없음)
  function histCryptoOk() { return !!(window.crypto && crypto.subtle && WP.histShot); }   // secure context(https·localhost)만
  function b64(u) { var s = "", i, C = 0x8000; for (i = 0; i < u.length; i += C) s += String.fromCharCode.apply(null, u.subarray(i, i + C)); return btoa(s); }
  function unb64(s) { var b = atob(s), u = new Uint8Array(b.length), i; for (i = 0; i < b.length; i++) u[i] = b.charCodeAt(i); return u; }
  function u8(x) { return x instanceof Uint8Array ? x : new Uint8Array(x); }
  function histKey(pw, salt, uses) {
    return crypto.subtle.importKey("raw", new TextEncoder().encode(pw), "PBKDF2", false, ["deriveKey"]).then(function (km) {
      return crypto.subtle.deriveKey({ name: "PBKDF2", salt: salt, iterations: 200000, hash: "SHA-256" }, km, { name: "AES-GCM", length: 256 }, false, uses);
    });
  }
  function histEncrypt(pw, obj) {
    var salt = crypto.getRandomValues(new Uint8Array(16)), iv = crypto.getRandomValues(new Uint8Array(12));
    var pt = new TextEncoder().encode(JSON.stringify(obj));
    if (pt.length > 8 * 1024 * 1024) return Promise.reject(new Error("too-big"));   // 기기 서버판과 동일 8MB 상한
    return histKey(pw, salt, ["encrypt"]).then(function (k) { return crypto.subtle.encrypt({ name: "AES-GCM", iv: iv }, k, pt); })
      .then(function (ct) { return { salt: salt, iv: iv, ct: new Uint8Array(ct) }; });
  }
  function histDecrypt(pw, rec) {
    var salt = u8(rec.salt), iv = u8(rec.iv), ct = u8(rec.ct);
    return histKey(pw, salt, ["decrypt"]).then(function (k) { return crypto.subtle.decrypt({ name: "AES-GCM", iv: iv }, k, ct); })
      .then(function (pt) { return JSON.parse(new TextDecoder().decode(pt)); });
  }
  var _histBusy = false;
  function histPersistPub(name) {   // A안: draftPut 시 역사 암호문 보관 — 게이트: _histPw 없으면 아무 것도 안 함
    try {
      var pw = WP.histPwGet && WP.histPwGet();
      if (!pw || !name || !histCryptoOk() || _histBusy) return;
      var shot = WP.histShot();
      if (!shot || !shot.hist || shot.hist.length < 2) return;   // 베이스뿐=보관 무의미
      _histBusy = true;
      histEncrypt(pw, shot).then(function (r) {
        return idb().then(function (db) {
          return new Promise(function (res) {
            var tx = db.transaction("wpHist", "readwrite");
            tx.objectStore("wpHist").put({ salt: r.salt, iv: r.iv, ct: r.ct, ts: Date.now() }, name);
            tx.oncomplete = res; tx.onerror = res;
          });
        });
      }).catch(function () {}).then(function () { _histBusy = false; });
    } catch (e) { _histBusy = false; }
  }
  function histGetIDB(name) {
    if (!name) return Promise.resolve(null);
    return idb().then(function (db) {
      if (!db.objectStoreNames.contains("wpHist")) return null;
      return new Promise(function (res) {
        var rq = db.transaction("wpHist").objectStore("wpHist").get(name);
        rq.onsuccess = function () { res(rq.result || null); };
        rq.onerror = function () { res(null); };
      });
    }).catch(function () { return null; });
  }
  function extractHistBlock(raw) {   // C안: 동봉 역사 블록 파싱(본문 오염 방지는 sanitizeHtml의 script 전체 제거가 담당)
    try {
      var m = String(raw).match(/<script[^>]*type\s*=\s*["']application\/x-wp-hist["'][^>]*>\s*WPH2:([A-Za-z0-9+/=]+):([A-Za-z0-9+/=]+):([A-Za-z0-9+/=]+)\s*<\/script>/);
      return m ? { salt: unb64(m[1]), iv: unb64(m[2]), ct: unb64(m[3]) } : null;
    } catch (e) { return null; }
  }
  function histRestorePub(name, rec) {   // 복원 플로우(rec=동봉 블록 우선, 없으면 IDB 조회)
    (rec ? Promise.resolve(rec) : histGetIDB(name)).then(function (r) {
      if (!r || !histCryptoOk() || !WP.histPwModal) return;
      var tryPw = function (pw, askOnFail) {
        histDecrypt(pw, r).then(function (d) {
          if (WP.adoptHistData && WP.adoptHistData(d)) toast("편집 역사 복원됨 — 되돌리기 " + d.hi + "단계 🔓");
          else toast("역사가 현재 문서와 달라 폐기됨(다른 곳에서 수정됨)");
        }).catch(function () { toast("암호가 일치하지 않습니다"); if (askOnFail) ask(); });
      };
      function ask() {
        WP.histPwModal("🔒 편집 역사 복원 — 암호", "이 문서의 되돌리기 역사가 잠겨 있습니다. 건너뜀=역사 없이 열기", function (pw) {
          if (!pw) return;
          if (!WP.histPwGet()) WP.histPwSet(pw);
          tryPw(pw, false);
        });
      }
      var spw = WP.histPwGet && WP.histPwGet();
      if (spw) tryPw(spw, true); else ask();
    }).catch(function () {});
  }

  // 시작 시: 직전 세션 초안(current)을 복구 사본(prev)으로 옮겨 새 세션 타이핑이 덮어쓰지 못하게 한 뒤 배너 제안
  Promise.all([draftGetKey("current"), draftGetKey("prev")]).then(function (r) {
    var cur = r[0], prev = r[1], d = cur || prev;
    if (cur) draftOp(function (st) { st.put(cur, "prev"); st.delete("current"); });
    if (d && d.html && d.html.replace(/<[^>]*>/g, "").trim()) draftBanner(d);
  });

  // ── 저장(다운로드) ──
  var _histAsked = false;   // 첫 저장(내려받기) 시 암호 설정 제안은 세션당 1회
  function dlHtml() {                          // HTML은 변환 없이 클라이언트에서 바로 내려받기
    var name = curName();
    var fin = function (extra, note) {
      download(new Blob([fullHtmlDoc(curHTML() + (extra || ""), name)], { type: "text/html;charset=utf-8" }), name + ".html");
      clean(); draftClear();                   // 파일로 보존됨 → 미저장 경고·초안 해제
      toast("HTML 내려받기 완료" + (note || "")); status("내려받음 " + hhmm(Date.now()));
    };
    if (!histCryptoOk()) { fin(); return; }
    var pw = WP.histPwGet && WP.histPwGet(), shot = WP.histShot();
    var hasHist = shot && shot.hist && shot.hist.length > 1;
    if (!pw) {                                 // P13 첫 저장 모달(설정 경로): 건너뜀=동봉 없이 즉시, 이후 도구 메뉴로만
      if (_histAsked || !hasHist || !WP.histPwModal) { fin(); return; }
      _histAsked = true;
      WP.histPwModal("편집 역사 동봉 — 암호 설정(선택)",
        "암호를 설정하면 되돌리기 역사가 암호화되어 문서 파일에 동봉되고 이 브라우저에도 보관됩니다(분실 시 역사만 복구 불가·문서는 무관). 건너뜀=동봉 안 함",
        function (p) { if (p) { WP.histPwSet(p); dlHtml(); } else fin(); });
      return;
    }
    if (!hasHist) { fin(); return; }
    histEncrypt(pw, shot).then(function (r) {   // P13-C: 문서 끝 동봉(비실행 데이터 script — 표준 HTML·렌더 무영향)
      var blk = '<script type="application/x-wp-hist" hidden>WPH2:' + b64(r.salt) + ':' + b64(r.iv) + ':' + b64(r.ct) + '</script>';
      fin(blk, " · 역사 동봉 +" + Math.max(1, Math.round(blk.length / 1024)) + "KB 🔒");
    }).catch(function (e) {
      fin("", (e && e.message === "too-big") ? " · 역사 8MB 초과로 동봉 생략" : " · 역사 동봉 실패(생략)");
    });
  }
  function shapesToImages(html) {   // 개체를 HWPX 호환으로 평탄화 — 도형(SVG)→PNG 그림, 이미지개체→인라인 그림(pic)
    return new Promise(function (resolve) {
      var tmp = document.createElement("div");
      tmp.style.cssText = "position:fixed;left:-99999px;top:0;width:210mm;font-size:11pt;line-height:1.6;";
      tmp.innerHTML = html;
      document.body.appendChild(tmp);
      // 이미지 개체(.wp-obj[data-obj=img])는 내부 img로 언랩 → HWPX 그림(pic)
      [].slice.call(tmp.querySelectorAll('.wp-obj[data-obj="img"]')).forEach(function (obj) {
        var img = obj.querySelector("img"); if (!img) return;
        var r = obj.getBoundingClientRect();
        var rep = img.cloneNode(true); rep.removeAttribute("style");
        rep.style.width = Math.max(1, Math.round(r.width || obj.offsetWidth || 100)) + "px";
        rep.style.height = Math.max(1, Math.round(r.height || obj.offsetHeight || 100)) + "px";
        if (obj.parentNode) obj.parentNode.replaceChild(rep, obj);
      });
      var svgs = [].slice.call(tmp.querySelectorAll("svg"));
      if (!svgs.length) { var out0 = tmp.innerHTML; document.body.removeChild(tmp); resolve(out0); return; }
      Promise.all(svgs.map(function (svg) {
        return new Promise(function (res) {
          var r = svg.getBoundingClientRect();
          var w = Math.max(1, Math.round(r.width || 120)), h = Math.max(1, Math.round(r.height || 80));
          try {
            var clone = svg.cloneNode(true);
            clone.setAttribute("width", w); clone.setAttribute("height", h);
            if (!clone.getAttribute("xmlns")) clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
            var url = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(new XMLSerializer().serializeToString(clone));
            var im = new Image();
            im.onload = function () {
              try {
                var c = document.createElement("canvas"); c.width = w * 2; c.height = h * 2;
                c.getContext("2d").drawImage(im, 0, 0, c.width, c.height);
                var rep = document.createElement("img");
                rep.src = c.toDataURL("image/png"); rep.style.width = w + "px"; rep.style.height = h + "px";
                var obj = svg.closest(".wp-obj") || svg;
                if (obj.parentNode) obj.parentNode.replaceChild(rep, obj);
              } catch (e) {}
              res();
            };
            im.onerror = function () { res(); };
            im.src = url;
          } catch (e) { res(); }
        });
      })).then(function () { var out = tmp.innerHTML; document.body.removeChild(tmp); resolve(out); });
    });
  }
  function dlHwpx() {
    status("한글 문서 변환 중…"); toast("한글 문서(HWPX) 변환 중…");
    var pg = null; try { pg = WP.paperInfo ? WP.paperInfo() : null; } catch (e) { pg = null; }   // 용지 → HWPX pagePr(2026-11-13)
    shapesToImages(curHTML()).then(function (h2) { return postFor("/api/convert/hwpx", { html: h2, page: pg }); }).then(function (b) {
      download(b, curName() + ".hwpx"); clean(); draftClear();   // 원본 충실 형식 → 보존 완료로 간주
      status("HWPX 내려받음"); toast("한글 문서(HWPX) 내려받기 완료");
    }).catch(function (e) { status(""); toast("HWPX 변환 실패: " + shortErr(e)); });
  }
  function dlDocx() {   // MS Word(.docx) 내려받기(2026-11-13) — 서버 무상태 변환, 용지(paperInfo)를 함께 보냄
    status("워드 문서 변환 중…"); toast("워드 문서(DOCX) 변환 중…");
    var pg = null; try { pg = WP.paperInfo ? WP.paperInfo() : null; } catch (e) { pg = null; }
    shapesToImages(curHTML()).then(function (h2) { return postFor("/api/convert/docx", { html: h2, page: pg }); }).then(function (b) {
      download(b, curName() + ".docx"); clean(); draftClear();   // 서식 보존 형식 → 보존 완료로 간주(HWPX와 동일)
      status("DOCX 내려받음"); toast("워드 문서(DOCX) 내려받기 완료");
    }).catch(function (e) { status(""); toast("DOCX 변환 실패: " + shortErr(e)); });
  }
  var _jspdfLoading = null;
  function ensureJsPdf() {
    if (window.jspdf && window.jspdf.jsPDF) return Promise.resolve();
    if (_jspdfLoading) return _jspdfLoading;
    _jspdfLoading = new Promise(function (res, rej) {
      var sc = document.createElement("script"); sc.src = "jspdf.min.js";
      sc.onload = function () { res(); };
      sc.onerror = function () { _jspdfLoading = null; rej(new Error("jsPDF 로드 실패")); };
      document.head.appendChild(sc);
    });
    return _jspdfLoading;
  }
  function pagesToPdfClient(pages) {   // 래스터 PNG dataURL 배열 → PDF Blob (브라우저 조립, 서버 무전송). JPEG 재인코딩으로 용량 축소.
    return new Promise(function (resolve, reject) {
      if (!pages || !pages.length) { reject(new Error("빈 문서")); return; }
      var JsPDF = window.jspdf.jsPDF, pdf = null, wpt = 0, hpt = 0, o = "p", i = 0;
      function step() {
        if (i >= pages.length) { try { resolve(pdf.output("blob")); } catch (e) { reject(e); } return; }
        var im = new Image();
        im.onload = function () {
          try {
            var w = im.naturalWidth || 600, h = im.naturalHeight || 848;
            var c = document.createElement("canvas"); c.width = w; c.height = h;
            var cx = c.getContext("2d"); cx.fillStyle = "#fff"; cx.fillRect(0, 0, w, h); cx.drawImage(im, 0, 0);
            var jpg = c.toDataURL("image/jpeg", 0.85);
            if (!pdf) { wpt = w * 0.75; hpt = h * 0.75; o = wpt > hpt ? "l" : "p"; pdf = new JsPDF({ unit: "pt", format: [wpt, hpt], orientation: o }); }
            else pdf.addPage([wpt, hpt], o);
            pdf.addImage(jpg, "JPEG", 0, 0, wpt, hpt);
            i++; step();
          } catch (e) { reject(e); }
        };
        im.onerror = function () { reject(new Error("이미지 로드 실패")); };
        im.src = pages[i];
      }
      step();
    });
  }
  function pdfHtmlWithBreaks() {   // 서버 PDF에 편집기 쪽 시작(pageStartIdx)을 강제 나눔으로 주입 → 서버 Chromium이 편집기와 같은 위치에서 나눔(WYSIWYG·쪽수 정합)
    var starts = window.WP.pageStartIdx || [];
    var html = curHTML();
    if (!starts.length) return html;
    var tmp = document.createElement("div"); tmp.innerHTML = html;
    var blocks = [].slice.call(tmp.children).filter(function (b) { return b.nodeType === 1 && b.id !== "wpmeta"; });
    starts.forEach(function (idx) { var b = blocks[idx]; if (b) { b.style.pageBreakBefore = "always"; b.style.breakBefore = "page"; } });
    return tmp.innerHTML;
  }
  function dlPdf() {   // 서버 벡터 PDF(Chromium) — 텍스트 완벽·쪽수 정합. 변환 위해 내용이 서버로 전송(메모리 변환·미저장).
    status("PDF 변환 중…"); toast("PDF 변환 중…");
    postFor("/api/convert/pdf", { html: curHTML() }).then(function (b) {
      download(b, curName() + ".pdf"); status("PDF 내려받음"); toast("PDF 내려받기 완료");
    }).catch(function (e) { status(""); toast("PDF 변환 실패: " + shortErr(e)); });
  }
  function shortErr(e) {                        // 서버 스택트레이스 원문 노출 방지(P2-8) — 첫 줄만, 상세는 콘솔
    var raw = String((e && e.message) || e || "");
    try { console.error("변환 실패 상세:", raw); } catch (x) {}
    var m = raw.split("\n")[0].slice(0, 120);
    return m || "서버 오류";
  }

  // ── 불러오기(업로드) ──
  var fi = document.createElement("input");
  fi.type = "file"; fi.accept = ".html,.htm,.hwpx,.hwp,.docx,.doc,.txt,.pdf"; fi.style.display = "none";
  document.body.appendChild(fi);
  fi.addEventListener("change", function () { var f = fi.files && fi.files[0]; if (f) loadFile(f); fi.value = ""; });
  function openUpload() { fi.click(); }
  function setDoc(name, html) {
    docname.value = name; page.innerHTML = (html && html.trim()) ? html : "<p><br></p>";
    clean(); if (WP.histReset) WP.histReset(); page.focus();
  }
  // 외부 문서 무해화: 노이즈 제거(head·스크립트 등) + XSS 벡터 제거(on* 속성, javascript:/위험 data: URL, 실행형 태그)
  function sanitizeHtml(raw) {
    try {
      var doc = new DOMParser().parseFromString(raw, "text/html");
      doc.querySelectorAll("script,style,meta,link,title,base,noscript,head,iframe,frame,frameset,object,embed,applet,form,svg,math,template").forEach(function (e) { e.remove(); });
      var w = doc.createTreeWalker(doc.body, NodeFilter.SHOW_COMMENT, null), rm = [], n;
      while ((n = w.nextNode())) rm.push(n);          // 주석 노드 수집 후 제거(누출원인)
      rm.forEach(function (c) { c.parentNode && c.parentNode.removeChild(c); });
      doc.body.querySelectorAll("*").forEach(function (el) {
        for (var i = el.attributes.length - 1; i >= 0; i--) {
          var a = el.attributes[i], an = a.name.toLowerCase();
          if (an.indexOf("on") === 0 || an === "srcdoc" || an === "formaction") { el.removeAttribute(a.name); continue; }
          if (an === "href" || an === "src" || an === "xlink:href" || an === "action" || an === "background" || an === "poster") {
            var u = String(a.value).replace(/[\s\u0000-\u001f]+/g, "").toLowerCase();
            if (u.indexOf("javascript:") === 0 || u.indexOf("vbscript:") === 0 ||
                (u.indexOf("data:") === 0 && !/^data:image\/(png|jpe?g|gif|webp|bmp|avif);/.test(u)))
              el.removeAttribute(a.name);
          }
        }
      });
      return doc.body.innerHTML;
    } catch (e) { return "<p></p>"; }                 // 파싱 실패 시 원문 그대로 넣지 않음(XSS 방지)
  }
  // ── TXT/PDF 열기(2026-07-22, 무상태 변환) ──
  function txtToHtml(text) {   // 평문 → 에디터 HTML(서버 text_to_html의 클라 미러: 빈 줄=빈 문단, \f=쪽 나누기, 탭=4칸)
    return text.split("\f").map(function (pg, i) {
      var pre = i ? '<p class="pgbreak"><br></p>' : "";
      return pre + pg.replace(/\r\n?/g, "\n").split("\n").map(function (line) {
        line = line.replace(/[\t ]+$/, "");
        return "<p>" + (line ? WP.esc(line).replace(/\t/g, "&nbsp;&nbsp;&nbsp;&nbsp;") : "<br>") + "</p>";
      }).join("");
    }).join("") || "<p><br></p>";
  }
  var _pendingPdf = null;
  function pdfImport(mode) {   // #m-pdfmode 선택 → 서버 무상태 변환(image=쪽 그림 / text=글자만)
    var pend = _pendingPdf; _pendingPdf = null;
    var m = document.getElementById("m-pdfmode"); if (m) m.classList.add("hidden");
    if (!pend) return;
    status(mode === "image" ? "PDF 쪽 그림 렌더 중…" : "PDF 글자 추출 중…"); toast("PDF 변환 중…");
    pend.file.arrayBuffer().then(function (buf) {
      return fetch("/api/convert/pdf-import?mode=" + mode, { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: buf });
    }).then(function (r) { return r.json(); }).then(function (r) {
      if (r && r.ok) { setDoc(pend.nm, sanitizeHtml(r.html)); status("불러옴: " + pend.nm); toast("PDF 열기 완료 (" + (mode === "image" ? "그대로" : "글자만") + ")"); }
      else { status(""); toast(r && r.err ? r.err : "PDF 열기 실패"); }
    }).catch(function () { status(""); toast("PDF 열기 실패(연결?)"); });
  }
  function loadFile(f) {
    if (WP.snap && WP.snap().dirty && !confirm("저장하지 않은 변경이 있습니다. 이 문서를 버리고 새 파일을 열까요?")) return;
    var nm = f.name.replace(/\.(html?|hwpx|hwp|docx?|txt|pdf)$/i, "");
    if (/\.txt$/i.test(f.name)) {              // TXT: UTF-8 클라 디코드 시도, 실패(CP949 등)면 서버 무상태 변환
      f.arrayBuffer().then(function (buf) {
        var txt = null;
        try { txt = new TextDecoder("utf-8", { fatal: true }).decode(new Uint8Array(buf)); } catch (e) { txt = null; }
        if (txt !== null) { setDoc(nm, txtToHtml(txt)); status("불러옴: " + nm); toast("텍스트 열기 완료"); return; }
        status("텍스트 여는 중…");
        return fetch("/api/convert/text", { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: buf })
          .then(function (r) { return r.json(); }).then(function (r) {
            if (r && r.ok) { setDoc(nm, sanitizeHtml(r.html)); status("불러옴: " + nm); toast("텍스트 열기 완료"); }
            else { status(""); toast("열기 실패: " + ((r && r.err) || "")); }
          });
      }).catch(function () { status(""); toast("열기 실패(연결?)"); });
      return;
    }
    if (/\.pdf$/i.test(f.name)) {               // PDF: 방식 선택 모달(그대로=쪽 그림 / 글자만=텍스트 추출)
      _pendingPdf = { file: f, nm: nm };
      if (WP.openModal) WP.openModal("m-pdfmode"); else pdfImport("image");
      return;
    }
    if (/\.html?$/i.test(f.name)) {            // HTML은 서버 없이 로드(단, 웹페이지 head·스크립트 등 비표시 메타 제거)
      var rd = new FileReader();
      rd.onload = function () {
        var raw = String(rd.result), emb = extractHistBlock(raw);   // P13-C: 동봉 역사 감지(본문에서는 sanitize가 script 제거)
        setDoc(nm, sanitizeHtml(raw)); status("불러옴: " + nm); toast("문서 열기 완료");
        histRestorePub(nm, emb);   // 동봉 우선, 없으면 IDB(wpHist) 조회 — 항목 없거나 암호 기능 미사용이면 no-op
      };
      rd.readAsText(f); return;
    }
    var isDocx = /\.docx?$/i.test(f.name), kind = isDocx ? "워드 문서" : "한글 문서";
    var isDoc = /\.doc$/i.test(f.name);   // 레거시 Word 97-2003: 서버가 텍스트만 추출 → 완료 시 안내
    status(kind + " 여는 중…"); toast(kind + " 변환 중…");   // hwpx/hwp/docx → 서버 변환(형식은 서버가 내용으로 판별)
    f.arrayBuffer().then(function (buf) {
      return fetch("/api/convert/import?name=" + encodeURIComponent(f.name),
                   { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: buf });
    }).then(function (r) { return r.json(); }).then(function (r) {
      if (r && r.ok) { setDoc(nm, sanitizeHtml(r.html)); status("불러옴: " + nm + (isDoc ? " (텍스트만)" : "")); toast(isDoc ? "Word 97-2003(.doc) 문서는 텍스트만 가져왔습니다 — 서식·표·그림은 .docx로 저장해 여세요" : kind + " 열기 완료"); histRestorePub(nm, null); }   // 변환 결과도 무해화(심층 방어)
      else { status(""); toast("열기 실패: " + ((r && r.err) || "")); }
    }).catch(function () { status(""); toast("열기 실패(연결?)"); });
  }

  // ── 그림 삽입: 서버 이미지 폴더 대신 브라우저에서 파일 선택 → data URI ──
  var imgIn = document.createElement("input");
  imgIn.type = "file"; imgIn.accept = "image/*"; imgIn.style.display = "none";
  document.body.appendChild(imgIn);
  imgIn.addEventListener("change", function () {
    var f = imgIn.files && imgIn.files[0]; imgIn.value = ""; if (!f) return;
    var rd = new FileReader();
    rd.onload = function () {
      page.focus();
      if (WP.insertImageObj) WP.insertImageObj(rd.result);   // 개체(.wp-obj img)로 삽입 → z-order·어울림·크기손잡이·회전
      else document.execCommand("insertHTML", false, '<img src="' + rd.result + '" style="max-width:100%">');
      if (WP.markDirty) WP.markDirty(); status("그림 삽입됨");
    };
    rd.readAsDataURL(f);
  });
  function pickImage() { imgIn.click(); }

  function pubPrint() {   // 공개모드 인쇄: 화면 그대로 래스터 캡처 → 새 창에 이미지 → 브라우저 인쇄(본인 프린터)
    status("인쇄 준비 중…"); toast("인쇄 준비 중…");
    if (!WP.rasterPages) { window.print(); return; }
    WP.rasterPages({ onProgress: WP.printProgress && WP.printProgress("인쇄") }).then(function (pages) {
      var w = window.open("", "_blank");
      if (!w) { status(""); toast("팝업 차단 — 인쇄 창을 열 수 없어요. 팝업 허용 후 다시 시도."); return; }
      var imgs = pages.map(function (du) { return '<img src="' + du + '">'; }).join("");
      w.document.open();
      w.document.write('<!doctype html><meta charset="utf-8"><title>인쇄</title>' +
        '<style>@page{margin:0}html,body{margin:0;padding:0}img{display:block;width:100%;page-break-after:always}img:last-child{page-break-after:auto}</style>' +
        imgs +
        '<scr' + 'ipt>window.onload=function(){setTimeout(function(){try{window.focus();window.print();}catch(e){}},300);};window.onafterprint=function(){window.close();};</scr' + 'ipt>');
      w.document.close();
      status(""); toast("인쇄 대화상자에서 프린터를 고르세요");
    }).catch(function (e) { status(""); toast("인쇄 준비 실패: " + shortErr(e)); });
  }

  function pubBrowserPrint() {   // 방식 A: DOM 브라우저 인쇄(텍스트 완벽·서버 무전송) + 편집기 쪽 시작에 강제 나눔(페이지 정합)
    status("인쇄 준비…"); toast("인쇄 대화상자에서 '대상 = PDF로 저장' 또는 프린터를 고르세요");
    var marked = [];
    try {
      var starts = window.WP.pageStartIdx || [];
      if (starts.length) {
        var blocks = [].slice.call(page.children).filter(function (b) {
          return b.nodeType === 1 && b.id !== "wpmeta" && !(b.hasAttribute && b.hasAttribute("data-pgfill"));
        });
        starts.forEach(function (idx) { var b = blocks[idx]; if (b) { b.style.pageBreakBefore = "always"; b.style.breakBefore = "page"; marked.push(b); } });
      }
    } catch (e) {}
    var cleanup = function () {
      marked.forEach(function (b) { b.style.pageBreakBefore = ""; b.style.breakBefore = ""; });
      window.removeEventListener("afterprint", cleanup); status("");
    };
    window.addEventListener("afterprint", cleanup);
    setTimeout(function () { try { window.print(); } catch (e) { cleanup(); toast("인쇄 실패: " + shortErr(e)); } }, 60);
    setTimeout(cleanup, 120000);   // 안전장치
  }
  WP.sanitizeHtml = sanitizeHtml;   // 디버그/테스트용 노출
  function dlTxt() {   // 문서 → 평문(표=박스문자) 내려받기(2026-07-22). 손실 변환이라 초안·dirty는 그대로.
    if (!WP.docText) { toast("텍스트 변환 모듈 로드 실패"); return; }
    download(new Blob([WP.docText()], { type: "text/plain;charset=utf-8" }), curName() + ".txt");
    toast("텍스트 내려받기 완료"); status("내려받음 " + hhmm(Date.now()));
  }
  WP.register({
    open: openUpload, openHwpx: openUpload, upload: openUpload,
    save: dlHtml, saveas: dlHtml, dlHtml: dlHtml,
    exportHwpx: dlHwpx, dlHwpx: dlHwpx,
    dlDocx: dlDocx,   // 워드 문서(DOCX) 내려받기
    pdf: dlPdf, dlPdf: dlPdf,   // PDF = 서버 벡터(Chromium)+강제나눔 정합
    dlTxt: dlTxt,   // 텍스트로 내려받기(표=박스문자 평문)
    pdfModeImage: function () { pdfImport("image"); }, pdfModeText: function () { pdfImport("text"); },   // #m-pdfmode 버튼
    image: pickImage,
    printer: pubBrowserPrint, browserPrint: pubBrowserPrint,   // 인쇄 = DOM 브라우저 인쇄(텍스트 완벽·무전송)
  });
  // 무상태 모드: 서버 저장이 없으므로 닫기/새로고침 전 미저장 경고
  window.addEventListener("beforeunload", function (e) {
    if (WP.snap && WP.snap().dirty) { e.preventDefault(); e.returnValue = ""; }
  });
  // ── 첫 실행 안내문(감독 지시 07-17): 공개 웹 첫 방문이면 빈 문서 대신 사용 안내문 로드 ──
  //    per-user: 판정=이 브라우저 localStorage 플래그뿐(서버 무상태 유지 — /guide.html은 정적 자산 GET).
  //    이 파일 자체가 공개모드 전용 로드라 로컬 dev(window.WP_PUBLIC 미설정)엔 원천 무영향.
  try {
    if (true) {   // 주인 지시 07-17: 매 방문 표시(첫방문 한정 해제, 아래 page 내용가드는 유지)
      fetch("guide.html").then(function (r) { return r.ok ? r.text() : null; }).then(function (html) {
        if (!html) return;   // 로드 실패=플래그 안 세움(다음 방문 재시도)
        if (WP.page.textContent.replace(/\s/g, "")) return;   // 이미 내용 있음(초안 복구 등) → 덮지 않음
        WP.page.innerHTML = html;
        if (WP.resolveMediaSrcs) WP.resolveMediaSrcs();   // 배너 미디어 파일명→재생URL(회귀방지, 감독 07-20)
        if (WP.normalizeEdges) WP.normalizeEdges();
        if (WP.histReset) WP.histReset();   // 안내문=초기 콘텐츠(dirty 아님·undo 기준점)
        status("사용 안내문 — 새 문서(Alt+N)나 내 PC에서 열기로 시작하세요");
      }).catch(function () {});
    }
  } catch (e) {}   // localStorage 접근 불가 환경 = 안내문 생략(조용히)

  status("공개 모드 · 파일은 내 PC에서 열고(업로드) 내려받습니다(다운로드)");
})();
