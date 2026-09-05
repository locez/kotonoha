  var root = document.documentElement;

  /* ---- messages ---------------------------------------------------------
     One table, keyed. A key missing from a locale falls back to the source
     rather than rendering the key, and check.sh reports the coverage. */
  /* The source locale ships inline so the first paint needs no fetch. The other
     catalogues are one file each, loaded when a reader asks for them: a single
     file holding every script is one artifact mixing Traditional and Simplified,
     which is the one thing the wording rules refuse outright. */
  var MESSAGES = { "zh-Hans": {
      "site.title": "Kotonoha — Wayland 桌面歌词",
      "site.description": "Kotonoha：Wayland 桌面歌词，支持任意 MPRIS 播放器，无需播放器插件。",
      "does.mpris": "任何 MPRIS 播放器，无需插件",
      "does.mpris.body": "通过 D-Bus 读取曲目和播放位置。播放器无需适配。播放位置用本地时钟插值，不逐帧查询。",
      "does.sources": "多种歌词来源",
      "does.sources.body": "来源顺序、匹配规则、回退和本地缓存都能配置。",
      "aria.language": "语言",
      "aria.theme": "主题",
      "aria.pause": "暂停",
      "aria.play": "播放",
      "aria.lockPosition": "锁定位置",
      "aria.lockedPosition": "已锁定位置",
      "aria.searchLyrics": "搜索歌词",
      "aria.settingsCategories": "设置分类",
      "settings.title": "Kotonoha 设置",
      "settings.general": "通用",
      "settings.text": "文字",
      "settings.effects": "效果",
      "settings.lyrics": "歌词",
      "settings.position": "位置",
      "settings.theme": "主题",
      "settings.light": "浅色",
      "settings.dark": "深色",
      "settings.followSystem": "跟随系统",
      "settings.frosted": "毛玻璃窗口",
      "settings.opacity": "窗口不透明度",
      "settings.accent": "强调色",
      "settings.pink": "粉",
      "settings.blue": "蓝",
      "settings.green": "绿",
      "settings.gold": "金",
      "settings.fontSize": "字号",
      "settings.weight": "字重",
      "settings.regular": "常规",
      "settings.semibold": "中黑",
      "settings.bold": "加粗",
      "settings.lineHeight": "行距",
      "settings.currentGlow": "当前行发光",
      "settings.currentWord": "高亮当前字",
      "settings.transition": "换行动画",
      "settings.rise": "上浮",
      "settings.fade": "淡入",
      "settings.none": "不动",
      "settings.translation": "显示翻译",
      "settings.wordTiming": "逐字时间",
      "settings.sync": "同步微调",
      "settings.horizontal": "水平",
      "settings.clickThrough": "点击穿透",
      "settings.lock": "锁定位置",
      "does.through": "点击穿透",
      "does.through.body": "启用后，鼠标事件直接传给下层窗口。歌词层不拦截点击。",
      "does.follow": "主题和语言都能跟随系统",
      "does.follow.body": "浅色、深色，或跟随系统。界面语言也能跟随系统。设置首页就能改，改完立即生效，不用重启。",
      "does.layer": "Wayland Overlay",
      "does.layer.table.capability": "能力",
      "does.layer.table.condition": "条件",
      "does.layer.table.behavior": "行为",
      "does.layer.fullscreen": "全屏上方显示",
      "does.layer.fullscreen.condition": "Wayland 合成器支持 <code>wlr-layer-shell</code>",
      "does.layer.fullscreen.behavior": "KDE/KWin、wlroots 可浮在全屏窗口上方",
      "does.layer.blur": "毛玻璃",
      "does.layer.blur.condition": "支持 <code>ext-background-effect-v1</code> 或 <code>org_kde_kwin_blur</code>",
      "does.layer.blur.behavior": "缺少时保留半透明，禁用毛玻璃",
      "does.layer.compatibility": "兼容性：不支持 <code>wlr-layer-shell</code> 的合成器（如 GNOME/Mutter）使用普通置顶窗口。",
      "theme.light": "浅色",
      "theme.dark": "深色",
      "theme.system": "系统",
      "hero.title": "Wayland 桌面歌词",
      "hero.lead": "Kotonoha 通过 D-Bus 读取 MPRIS 播放状态，在 Wayland 图层上显示逐字歌词。支持任意 MPRIS 播放器，无需播放器插件。",
      "hero.install": "安装",
      "scene.note": "点击可交互体验",
      "does.follow.a": "浅色 / 深色 / 跟随系统",
      "does.follow.b": "简体 · 繁體 · English",
      "s.search": "搜索窗口",
      "s.search.lead": "搜索结果多时，点表头排序。时长按秒数，匹配度按等级。",
      "search.title": "搜索歌词",
      "search.lead": "从不同来源找歌词，选中后应用。",
      "search.lyricSource": "歌词来源",
      "search.wordTimed": "逐字",
      "search.playbackSource": "播放来源",
      "search.cacheStatus": "缓存状态",
      "search.cached": "已缓存",
      "search.searchLyrics": "搜索歌词",
      "search.song": "歌曲",
      "search.artist": "艺术家",
      "search.artistPlaceholder": "艺术家名称",
      "search.album": "专辑",
      "search.albumPlaceholder": "专辑名称",
      "search.search": "搜索",
      "search.results": "搜索结果",
      "search.onlyHigh": "仅看高匹配",
      "search.source": "来源",
      "search.sourceA": "来源 A",
      "search.sourceB": "来源 B",
      "search.sourceC": "来源 C",
      "search.sourceD": "来源 D",
      "search.duration": "时长",
      "search.version": "歌词版本",
      "search.match": "匹配度",
      "search.apply": "应用所选歌词",
      "search.close": "关闭",
      "search.unavailable": "不可用：两个来源未响应",
      "search.count": "%n 条结果",
      "search.hidden": "，另有 %n 条隐藏",
      "search.verWord": "逐字",
      "search.verLine": "逐行",
      "search.verNone": "无时间",
      "search.verTranslation": "逐字 · 带翻译",
      "search.confNone": "无",
      "search.confMid": "中",
      "search.confHigh": "高",
      "s.get": "安装",
      "get.lead": "Gentoo 用 <code>gentoo-zh</code>，Arch 用 AUR 的 <code>kotonoha-git</code>，NixOS 用 flake；Debian/Ubuntu 可直接安装 DEB，Fedora 等 RPM 系可安装 RPM，也可以从源码构建。",
      "eb.search": "歌词来源",
      "ends.try.eb": "可交互",
      "ends.try.title": "顶部的窗口可以直接操作",
      "ends.try.lead": "拖动歌词栏改变位置，锁定、点击穿透与设置项即时生效。",
      "ends.try.go": "尝试一下",
      "ends.repo.eb": "源码",
      "ends.repo.title": "源码在 GitHub",
      "ends.repo.lead": "仓库包含 Wayland 图层、D-Bus 适配与歌词来源的实现。",
      "ends.repo.go": "在 GitHub 上加星",
      "eb.get": "软件包",
      "copy": "复制",
      "copied": "已复制",
      "get.distribution": "发行版",
      "get.official": "官方源",
      "get.mirror": "CERNET 镜像",
      "get.manual": "手动 repos.conf",
      "get.source": "从源码编译",
      "get.deb": "Debian / Ubuntu",
      "get.rpm": "Fedora / RPM",
      "get.deb.note": "官方 Release 提供 amd64 包；需要 curl 和 jq 命令。",
      "get.rpm.note": "官方 Release 提供 x86_64 包；需要 curl 和 jq 命令。",
      "get.arch.note": "AUR 包名是 kotonoha-git，构建自 main 分支最新提交。",
      "get.nixos.note": "加进 flake，再把包放进 systemPackages。",
      "get.source.note": "先装系统依赖。uv sync 会自动编译原生 Wayland 桥接。",
      "get.live.comment": "live ebuild 没有任何关键字",
      "foot.lead": "Linux 上的 Wayland 歌词",
      "foot.source": "源码",
      "foot.releases": "发行版",
      "foot.license": "MIT 授权",
      "foot.architecture": "架构",
      "foot.lyricsCache": "歌词与缓存",
      "foot.adapterProtocol": "外部适配协议",
      "foot.controlIcons": "控件图标：Lucide，ISC。",
      "foot.distroIcons": "发行版图标：simple-icons，CC0。",
      "foot.desc": "需要支持 wlr-layer-shell 的 Wayland 合成器。KDE/KWin 和 wlroots 合成器都可以。",
      "foot.project": "项目",
      "foot.docs": "文档",
      "foot.credit": "图标、软件界面与网站：<a href=\"https://github.com/Zakkaus\">Zakk</a>。"
  } };

  var SOURCE = "zh-Hans";
  var localeUpdaters = [];

  // Named msg, not t: the overlay's clock already owns `t`, and a var at the
  // same scope overwrote the function without a word from anyone.
  function msg(key) {
    var loc = root.dataset.locale || SOURCE;
    var table = MESSAGES[loc] || {};
    if (key in table) { return table[key]; }
    return MESSAGES[SOURCE][key] !== undefined ? MESSAGES[SOURCE][key] : key;
  }
  function loadLocale(loc, then) {
    if (loc === SOURCE || MESSAGES[loc]) { then(); return; }
    // head 里可能已经把这一份发出去了，再要一次就是白白多走一个来回。
    var early = window.__locale;
    if (early && early.at === loc) {
      early.table.then(function (table) { MESSAGES[loc] = table; then(); });
      return;
    }
    fetch("assets/i18n/" + loc + ".json")
      .then(function (r) { return r.ok ? r.json() : {}; })
      .then(function (table) { MESSAGES[loc] = table; then(); },
            // A catalogue that will not load must not take the page with it:
            // an empty table falls every key back to the source.
            function () { MESSAGES[loc] = {}; then(); });
  }

  function paintLocale(loc) {
    if (!MESSAGES[loc] && loc !== SOURCE) { loadLocale(loc, function () { paintLocale(loc); }); return; }
    root.dataset.locale = loc;
    root.lang = loc;
    document.querySelectorAll("[data-i18n]").forEach(function (el) {
      // The markup's own text is the last fallback. Painting the key on screen
      // is the one thing a missing translation must never do.
      if (el.dataset.i18nSource === undefined) { el.dataset.i18nSource = el.innerHTML; }
      var text = msg(el.dataset.i18n);
      el.innerHTML = text === el.dataset.i18n ? el.dataset.i18nSource : text;
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach(function (el) {
      el.placeholder = msg(el.dataset.i18nPlaceholder);
    });
    document.querySelectorAll("[data-i18n-aria-label]").forEach(function (el) {
      el.setAttribute("aria-label", msg(el.dataset.i18nAriaLabel));
    });
    document.querySelectorAll("[data-i18n-content]").forEach(function (el) {
      el.setAttribute("content", msg(el.dataset.i18nContent));
    });
    document.querySelectorAll("#langSeg button").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.dataset.lang === loc));
    });
    localeUpdaters.forEach(function (update) { update(); });
    // 第一帧把译文留白而不是画错的那份，画完就撤掉这个标记。
    delete root.dataset.langPending;
    try { localStorage.setItem("kotonoha-site-locale", loc); } catch (e) {}
  }
  document.querySelectorAll("#langSeg button").forEach(function (b) {
    b.addEventListener("click", function () { paintLocale(b.dataset.lang); });
  });

  function apply(choice) {
    root.dataset.choice = choice;
    root.dataset.theme = choice === "system"
      ? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
      : choice;
    document.querySelectorAll("#themeSeg button").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.dataset.themeSet === choice));
    });
    // The browser's own chrome takes the window colour from the token layer
    // rather than a second copy of it in a meta tag, which would drift.
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) { meta.content = getComputedStyle(root).getPropertyValue("--window").trim(); }
    try { localStorage.setItem("kotonoha-site-theme", choice); } catch (e) {}
  }
  document.querySelectorAll("#themeSeg button").forEach(function (b) {
    b.addEventListener("click", function () { apply(b.dataset.themeSet); });
  });
  // The system preference moving mid-session moves the page, but only while the
  // reader has actually chosen "follow system".
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function () {
    var stored = null;
    try { stored = localStorage.getItem("kotonoha-site-theme"); } catch (e) {}
    if (stored === "system") { apply("system"); }
  });
  var stored = null, storedLoc = null;
  try {
    stored = localStorage.getItem("kotonoha-site-theme");
    storedLoc = localStorage.getItem("kotonoha-site-locale");
  } catch (e) {}
  apply(stored || "dark");
  paintLocale(storedLoc || SOURCE);

  // One named guard, read by every pointer-driven effect. Declaring it in one
  // place is what keeps a tilt from firing on a tap and sticking there.
  var finePointer = matchMedia("(hover: hover) and (pointer: fine)");
  var stillness = matchMedia("(prefers-reduced-motion: reduce)");
  function guards() {
    var fine = finePointer.matches && !stillness.matches;
    root.dataset.pointer = fine ? "fine" : "coarse";
    root.dataset.motion = stillness.matches ? "reduced" : "full";
    return fine;
  }
  var pointerOk = guards();
  finePointer.addEventListener("change", function () { pointerOk = guards(); });
  stillness.addEventListener("change", function () { pointerOk = guards(); });

  function track(el, onMove) {
    el.addEventListener("pointermove", function (event) {
      if (!pointerOk) { return; }
      var box = el.getBoundingClientRect();
      onMove(el, (event.clientX - box.left) / box.width, (event.clientY - box.top) / box.height);
    });
    el.addEventListener("pointerleave", function () { onMove(el, 0.5, 0.5); });
  }

  /* ---- the overlay demo: one timeline, two lyric shapes ------------------
     The word-timed source carries a start for every word, the line-timed one
     carries a start per line. Same player, same clock; what differs is how
     much the sheet knows, which is exactly the difference the version column
     in the search window reports. */
  var SOURCES = [
    {
      mode: "word",
      total: 21,
      lines: [
        { at: 0.0, sub: "How many times do I have to tell you",
          words: [["为什么",0.0],["这么",0.9],["熟悉",1.6],["的",2.4],["旋律",2.8]] },
        { at: 4.6, sub: "Even the silence sounds the same",
          words: [["连",4.6],["沉默",5.0],["都",5.9],["一样",6.3],["长",7.4]] },
        { at: 8.8, sub: "I keep the light on, you keep walking",
          words: [["灯",8.8],["还",9.3],["亮着",9.8],["你",10.9],["还",11.4],["在",11.9],["走",12.5]] },
        { at: 14.2, sub: "Nothing here is waiting any more",
          words: [["这里",14.2],["已经",15.0],["没有",16.0],["谁",17.0],["在等",17.6]] }
      ]
    },
    {
      mode: "line",
      total: 21,
      lines: [
        { at: 0.0, sub: "How many times do I have to tell you", words: [["为什么这么熟悉的旋律", 0.0]] },
        { at: 4.6, sub: "Even the silence sounds the same", words: [["连沉默都一样长", 4.6]] },
        { at: 8.8, sub: "I keep the light on, you keep walking", words: [["灯还亮着，你还在走", 8.8]] },
        { at: 14.2, sub: "Nothing here is waiting any more", words: [["这里已经没有谁在等", 14.2]] }
      ]
    }
  ];

  var ovl = {
    line: document.getElementById("ovlLine"),
    sub: document.getElementById("ovlSub"),
    prev: document.getElementById("ovlPrev"),
    next: document.getElementById("ovlNext"),
    play: document.getElementById("ovlPlay")
  };

  if (ovl.line) {
    var src = 0, t = 0, running = true, last = null, dragging = false;

    function lineAt(time) {
      var set = SOURCES[src].lines, found = set[0];
      for (var i = 0; i < set.length; i++) { if (set[i].at <= time) { found = set[i]; } }
      return found;
    }
    // The line is built once and then only its word states change. Rebuilding
    // every span on every frame laid the text out sixty times a second — that
    // is what the stutter was — and it also meant no word ever transitioned:
    // a span created this frame has no previous colour to move from.
    var wordSpans = [], subSpan = null, builtSrc = -1, builtIndex = -1;
    function build(set, current, index) {
      function plain(row) { return row ? row.words.map(function (w) { return w[0]; }).join("") : ""; }
      ovl.prev.textContent = plain(set.lines[index - 1]);
      ovl.next.textContent = plain(set.lines[index + 1]);
      wordSpans = current.words.map(function (word) {
        var span = document.createElement("span");
        span.textContent = word[0];
        span.dataset.sung = "no";
        return span;
      });
      ovl.line.replaceChildren.apply(ovl.line, wordSpans);
      // The translation is sung along with the line it translates: the program
      // colours it by the same clock, which is why it reads as one row.
      subSpan = document.createElement("span");
      subSpan.textContent = current.sub;
      subSpan.dataset.sung = "no";
      ovl.sub.replaceChildren(subSpan);
      builtSrc = src; builtIndex = index;
    }
    function paint() {
      var set = SOURCES[src], current = lineAt(t), index = set.lines.indexOf(current);
      if (builtSrc !== src || builtIndex !== index) { build(set, current, index); }
      var lineEnd = set.lines[index + 1] ? set.lines[index + 1].at : set.total;
      var chars = 0, litChars = 0;
      current.words.forEach(function (word, i) {
        var after = current.words[i + 1];
        var sung = t >= word[1];
        var state = sung && (!after || t < after[1]) ? "now" : (sung ? "yes" : "no");
        if (wordSpans[i].dataset.sung !== state) { wordSpans[i].dataset.sung = state; }
        // Each word fills across its own span of the clock, which is what
        // word-timed lyrics are: a step per word is line-timed with extra steps.
        var ends = after ? after[1] : lineEnd;
        var over = Math.max(ends - word[1], 0.001);
        var done = Math.min(1, Math.max(0, (t - word[1]) / over));
        wordSpans[i].style.setProperty("--sung", done.toFixed(3));
        chars += word[0].length;
        litChars += word[0].length * done;
      });
      // The translation fills to the same fraction of its text as the line
      // above has filled of its own — measured in characters, not in time.
      // Timed instead, the two drift apart within a line, because words take
      // an equal share of the clock and an unequal share of the row.
      subSpan.style.setProperty("--sung", (chars ? litChars / chars : 0).toFixed(3));
    }
    function tick(stamp) {
      if (last !== null && running && !dragging) {
        t = (t + (stamp - last) / 1000) % SOURCES[src].total;
        paint();
      }
      last = stamp;
      requestAnimationFrame(tick);
    }
    ovl.play.addEventListener("click", function () {
      running = !running;
      ovl.play.setAttribute("aria-pressed", String(running));
      ovl.play.setAttribute("aria-label", running ? msg("aria.pause") : msg("aria.play"));
    });
    window.setWordTiming = function (on) {
      var want = on ? 0 : 1;
      if (src !== want) { src = want; paint(); }
    };
    // A demo that runs forever is still motion: reduced motion holds it still
    // at a position that shows the effect rather than an empty first frame.
    if (stillness.matches) {
      running = false; t = 10.2;
      ovl.play.setAttribute("aria-pressed", "false");
      ovl.play.setAttribute("aria-label", msg("aria.play"));
    }
    paint();
    requestAnimationFrame(tick);
  }

  /* ---- the stack: click a window to bring it forward, tilt with the pointer */

  /* ---- the settings window drives the overlay, the way it does in the program.
     Panels are data: adding one is a row here, not a branch anywhere else. ---- */
  var PANELS = {
    general: [
      { kind: "select", labelKey: "settings.theme", id: "theme", options: [["light","settings.light"],["dark","settings.dark"],["system","settings.followSystem"]] },
      { kind: "switch", labelKey: "settings.frosted", id: "frost", on: true },
      { kind: "range", labelKey: "settings.opacity", id: "opacity", min: 40, max: 100, value: 80, unit: " %" },
      { kind: "dots", labelKey: "settings.accent", id: "accent" }
    ],
    text: [
      { kind: "range", labelKey: "settings.fontSize", id: "size", min: 14, max: 34, value: 24, unit: " px" },
      { kind: "select", labelKey: "settings.weight", id: "weight", options: [["400","settings.regular"],["650","settings.semibold"],["800","settings.bold"]] },
      { kind: "range", labelKey: "settings.lineHeight", id: "leading", min: 110, max: 190, value: 140, unit: " %" }
    ],
    effects: [
      { kind: "switch", labelKey: "settings.currentGlow", id: "glow", on: false },
      { kind: "switch", labelKey: "settings.currentWord", id: "pop", on: true },
      { kind: "select", labelKey: "settings.transition", id: "rise", options: [["rise","settings.rise"],["fade","settings.fade"],["none","settings.none"]] }
    ],
    lyrics: [
      { kind: "switch", labelKey: "settings.translation", id: "trans", on: true },
      { kind: "switch", labelKey: "settings.wordTiming", id: "word", on: true },
      { kind: "range", labelKey: "settings.sync", id: "nudge", min: -20, max: 20, value: 0, unit: " ×0.1s" }
    ],
    position: [
      { kind: "range", labelKey: "settings.horizontal", id: "px", min: 0, max: 100, value: 50, unit: " %" },
      { kind: "switch", labelKey: "settings.clickThrough", id: "through", on: false },
      { kind: "switch", labelKey: "settings.lock", id: "lock", on: true }
    ]
  };

  // The same glyphs the settings window draws, from icons.py.
  var NAV_ICON = { general: "general", text: "text", effects: "effects", lyrics: "lyrics", position: "position" };
  var kcard = document.getElementById("kcard");
  var knav = document.getElementById("knav");
  var activePanel = null;
  var state = { size: 24, weight: "650", leading: 140, glow: false, pop: true,
                trans: true, word: true, nudge: 0, px: 50, through: false, lock: false,
                frost: true, opacity: 80, rise: "rise" };

  function formRow(spec) {
    var row = document.createElement("label");
    row.className = "kfield";
    var name = document.createElement("span");
    name.textContent = msg(spec.labelKey);
    row.append(name);

    if (spec.kind === "select") {
      row.append(listbox(spec));
    } else if (spec.kind === "switch") {
      var sw = document.createElement("button");
      sw.type = "button"; sw.className = "ksw"; sw.setAttribute("role", "switch");
      sw.dataset.bind = spec.id;
      sw.setAttribute("aria-checked", String(state[spec.id]));
      sw.append(document.createElement("i"));
      sw.addEventListener("click", function () {
        var on = sw.getAttribute("aria-checked") !== "true";
        sw.setAttribute("aria-checked", String(on));
        apply1(spec.id, on);
      });
      row.append(sw);
    } else if (spec.kind === "range") {
      var input = document.createElement("input");
      input.type = "range"; input.min = spec.min; input.max = spec.max;
      input.value = String(state[spec.id]); input.setAttribute("aria-label", msg(spec.labelKey));
      input.dataset.bind = spec.id;
      var out = document.createElement("b");
      out.dataset.bind = spec.id;
      out.textContent = state[spec.id] + spec.unit;
      input.addEventListener("input", function () {
        out.textContent = input.value + spec.unit;
        apply1(spec.id, Number(input.value));
      });
      row.append(input, out);
    } else if (spec.kind === "dots") {
      var wrap = document.createElement("span");
      wrap.className = "kdots";
      wrap.id = "kAccent";
      [["--preset-pink","settings.pink"],["--preset-cyan","settings.blue"],["--preset-green","settings.green"],["--preset-gold","settings.gold"]].forEach(function (tok, i) {
        var dot = document.createElement("button");
        dot.type = "button"; dot.dataset.a = tok[0];
        dot.style.setProperty("--dot", "var(" + tok[0] + ")");
        dot.setAttribute("aria-label", msg(tok[1]));
        dot.setAttribute("aria-pressed", String(i === 0));
        dot.addEventListener("click", function () {
          wrap.querySelectorAll("button").forEach(function (o) { o.setAttribute("aria-pressed", String(o === dot)); });
          root.style.setProperty("--accent", "var(" + tok[0] + ")");
        });
        wrap.append(dot);
      });
      row.append(wrap);
    }
    return row;
  }

  /* A listbox drawn here rather than a native <select>: the browser's own popup
     is painted by the platform, so no stylesheet reaches it and the demo window
     opened a white system menu over a dark panel. Keyboard behaviour is the part
     a replacement usually loses, so it is written out: Enter and the arrows open
     it, the arrows move, Enter takes, Escape closes and hands focus back. */
  function listbox(spec) {
    var wrap = document.createElement("span");
    wrap.className = "lb";
    var current = spec.id === "theme" ? (root.dataset.choice || "dark") : String(state[spec.id]);
    var button = document.createElement("button");
    button.type = "button";
    button.className = "lb__btn";
    button.setAttribute("role", "combobox");
    button.setAttribute("aria-expanded", "false");
    button.setAttribute("aria-haspopup", "listbox");
    var label = document.createElement("span");
    var chev = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    chev.setAttribute("viewBox", "0 0 24 24"); chev.setAttribute("aria-hidden", "true");
    chev.setAttribute("fill", "none"); chev.setAttribute("stroke", "currentColor");
    chev.setAttribute("stroke-width", "2"); chev.setAttribute("stroke-linecap", "round");
    chev.setAttribute("stroke-linejoin", "round");
    var chevPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
    chevPath.setAttribute("d", "m6 9 6 6 6-6");
    chev.append(chevPath);
    button.append(label, chev);

    var list = document.createElement("div");
    list.className = "lb__list";
    list.setAttribute("role", "listbox");
    list.id = "lb-" + spec.id;
    button.setAttribute("aria-controls", list.id);
    list.hidden = true;

    var options = spec.options.map(function (o, i) {
      var item = document.createElement("div");
      item.setAttribute("role", "option");
      item.id = list.id + "-" + i;
      item.dataset.labelKey = o[1];
      item.textContent = msg(o[1]);
      item.dataset.value = o[0];
      item.setAttribute("aria-selected", String(o[0] === current));
      list.append(item);
      return item;
    });

    function paintLabel() {
      var picked = options.find(function (o) { return o.getAttribute("aria-selected") === "true"; });
      label.textContent = picked ? picked.textContent : "";
    }
    function close(focusBack) {
      list.hidden = true;
      button.setAttribute("aria-expanded", "false");
      button.removeAttribute("aria-activedescendant");
      if (focusBack) { button.focus(); }
    }
    function open() {
      list.hidden = false;
      button.setAttribute("aria-expanded", "true");
      dropWhereItFits();
      var at = options.findIndex(function (o) { return o.getAttribute("aria-selected") === "true"; });
      move(at < 0 ? 0 : at);
    }
    // The window clips what leaves it, so a list opened downwards with no room
    // below is not merely awkward — it is cut off. Measured on the effects page:
    // 12px past the window on a desktop, 92px of a 122px list on a phone, with
    // 279px standing free above the field. A real combo flips; this one did not.
    function dropWhereItFits() {
      var frame = button.closest(".kwin") || document.documentElement;
      var room = frame.getBoundingClientRect();
      var field = button.getBoundingClientRect();
      var wanted = list.getBoundingClientRect().height;
      var below = room.bottom - field.bottom;
      var above = field.top - room.top;
      list.dataset.drop = wanted > below && above > below ? "up" : "down";
    }

    function move(index) {
      var wrapped = (index + options.length) % options.length;
      options.forEach(function (o, i) { o.dataset.active = String(i === wrapped); });
      button.setAttribute("aria-activedescendant", options[wrapped].id);
    }
    function activeIndex() {
      return options.findIndex(function (o) { return o.dataset.active === "true"; });
    }
    function take(index) {
      options.forEach(function (o, i) { o.setAttribute("aria-selected", String(i === index)); });
      paintLabel();
      close(true);
      apply1(spec.id, options[index].dataset.value);
    }

    button.addEventListener("click", function () {
      if (list.hidden) { open(); } else { close(false); }
    });
    button.addEventListener("keydown", function (event) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp" || event.key === "Enter" || event.key === " ") {
        if (list.hidden) { event.preventDefault(); open(); return; }
      }
      if (list.hidden) { return; }
      if (event.key === "ArrowDown") { event.preventDefault(); move(activeIndex() + 1); }
      else if (event.key === "ArrowUp") { event.preventDefault(); move(activeIndex() - 1); }
      else if (event.key === "Home") { event.preventDefault(); move(0); }
      else if (event.key === "End") { event.preventDefault(); move(options.length - 1); }
      else if (event.key === "Enter" || event.key === " ") { event.preventDefault(); take(activeIndex()); }
      else if (event.key === "Escape") { event.preventDefault(); close(true); }
    });
    options.forEach(function (item, i) {
      item.addEventListener("click", function () { take(i); });
      item.addEventListener("pointermove", function () { move(i); });
    });
    document.addEventListener("pointerdown", function (event) {
      if (!list.hidden && !wrap.contains(event.target)) { close(false); }
    });

    paintLabel();
    wrap.append(button, list);
    return wrap;
  }

  function apply1(id, value) {
    if (id === "theme") { apply(String(value)); return; }
    state[id] = value;
    reflect();
  }

  function reflect() {
    var sceneEl = document.getElementById("scene");
    var ovlEl = document.getElementById("ovl");
    if (!ovlEl) { return; }
    ovlEl.style.setProperty("--ovl-size", state.size / 16 + "rem");
    ovlEl.style.setProperty("--ovl-weight", state.weight);
    ovlEl.style.setProperty("--ovl-leading", state.leading / 100);
    ovlEl.dataset.glow = String(state.glow);
    ovlEl.dataset.pop = String(state.pop);
    ovlEl.dataset.trans = String(state.trans);
    ovlEl.dataset.through = String(state.through);
    ovlEl.dataset.grab = !state.lock && !state.through ? "1" : "0";
    // 「锁定位置」有三个视图：浮窗上的按钮、设置里的开关、面板抓不抓得住。
    // 三个都从这一份状态读，所以它们不会各说各话。
    var lockBtn = document.getElementById("ovlLock");
    if (lockBtn) {
      lockBtn.setAttribute("aria-pressed", String(state.lock));
      lockBtn.setAttribute("aria-label", msg(state.lock ? "aria.lockedPosition" : "aria.lockPosition"));
    }
    document.querySelectorAll(".ksw[data-bind]").forEach(function (sw) {
      var want = String(!!state[sw.dataset.bind]);
      if (sw.getAttribute("aria-checked") !== want) { sw.setAttribute("aria-checked", want); }
    });
    ovlEl.style.setProperty("--ovl-shift", (state.px - 50) / 5 + "%");
    document.querySelectorAll(".kwin, .scene .ovl").forEach(function (w) {
      w.style.backdropFilter = state.frost ? "" : "none";
    });
    // The setting moves the surface, not the text: fading the whole scene is
    // what made it read as a cheap demo rather than as the program.
    root.style.setProperty("--win-alpha", state.opacity + "%");
    if (typeof setWordTiming === "function") { setWordTiming(state.word); }
  }

  /* 浮窗可以直接拖。它和「水平」那根滑杆做的是同一件事，所以写同一份状态，
     不是第二份副本——两份状态迟早会说出两个不同的位置。

     「锁定位置」与「点击穿透」都在这里被读到。在此之前两个开关都没有任何读者：
     按下去界面上什么都不会发生，而那正是它们要演示的功能。 */
  /* 浮窗右上角那两个按钮此前一个只翻自己的样子、一个什么都不做。
     锁写进同一份状态；搜索把人带到下面那个搜索窗口——它就在这一页上，
     一个点了没有任何反应的按钮，比没有这个按钮更糟。 */
  /* 沉下去只是为了让人第一次注意到它。人一旦动过手，这句话就说完了，
     再沉回去只是每次移开鼠标都闪一下。 */

  function wireOverlayChrome() {
    var lockBtn = document.getElementById("ovlLock");
    if (lockBtn && lockBtn.dataset.wired !== "1") {
      lockBtn.dataset.wired = "1";
      lockBtn.addEventListener("click", function () {
        apply1("lock", lockBtn.getAttribute("aria-pressed") !== "true");
      });
    }
    var searchBtn = document.getElementById("ovlSearch");
    if (searchBtn && searchBtn.dataset.wired !== "1") {
      searchBtn.dataset.wired = "1";
      searchBtn.addEventListener("click", function () {
        var target = document.getElementById("search");
        if (target) { target.scrollIntoView({ behavior: "smooth", block: "start" }); }
      });
    }
  }

  // 大多数读者以为右边那块是一张图，鼠标根本不会移过去，所以任何要先悬停
  // 才出现的提示都等不到人。这个按钮不写字解释，它把歌词栏推出去再拉回来：
  // 面板动过一次，加上滑杆同步跟着走，能不能拖就不用讲了。
  // 宽屏时面板在右边，窄屏时它在下面，箭头得指对地方。
  // 按下之后，背景那片颗粒彙集成一支指向面板的箭头。这一页别处就是这么说话的
  // ——能力那一节的图标就是同一批颗粒聚出来的——所以这里不必再发明一种效果。
  var heroField = null, heroOpts = null, heroAim = false, heroCentre = null;

  // 取样要走 getPointAtLength，一支箭上千个点，每按一次重算会卡一下。
  var arrowCache = {};

  // 把一条路径取样成颗粒的目标点。箭头和下面两块去处共用这一条，
  // 免得同一件事写两遍。
  var pathCache = {};
  function pathPoints(d) {
    if (pathCache[d]) { return pathCache[d]; }
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    d.split("|").forEach(function (one) {
      var p = document.createElementNS("http://www.w3.org/2000/svg", "path");
      p.setAttribute("d", one);
      svg.appendChild(p);
    });
    // getTotalLength 要求元素在渲染树里，取完样再摘掉。
    svg.style.cssText = "position:absolute;inline-size:0;block-size:0;overflow:hidden";
    document.body.append(svg);
    var pts = glyphOf(svg, "0 0 24 24");
    svg.remove();
    pathCache[d] = pts;
    return pts;
  }

  function arrowPoints(beside) {
    var key = beside ? "beside" : "below";
    if (arrowCache[key]) { return arrowCache[key]; }
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    var path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    // 弯的，不是直的：一支手画的箭比一条几何线更像有人在指，而这一页的
    // 颗粒本来就不是印出来的形状。头是单独一笔，尖端落在曲线的末点上。
    // 头要占到整个盒子的四分之一。上一版的倒钩只有 4/24，缩到一百多像素、
    // 再用 5px 宽的乱向碎片去画，两根倒钩糊成一团，整支读起来没有方向。
    // 头是闭合三角，不是两根倒钩。倒钩在这个画法下（5px 宽、朝向随机的碎片）
    // 只会糊成一团，看不出哪头是尖；三角的周长把点吃满，方向立刻读得出来。
    // 两种排版各画一支，不是同一支镜像：宽屏是从文案下方抬起来横扫向右，
    // 窄屏是从左上落下去、指进下面的面板。
    // 两种排版两支不同的箭，不是同一支镜像。
    // 宽屏是手画的那种：从左上荡出去、绕一个圈、再落向右下的面板。圈是它读起来
    // 像有人随手一指而不是像一个图标的原因。
    // 窄屏是直的：那一条只有一百来像素高，绕圈缩到那个尺寸只会糊成一团。
    var d = beside
      ? ["M1.5 6.5C6 3.5 12.5 4.5 13.5 8C14.2 10.5 10.5 11.8 8 10.4C5.4 8.9 9.5 6.6 13 9.2C16.5 11.8 19 13.6 22 15.5",
         "M22 15.5 17.4 15.7 20.2 11.3Z"]
      : ["M12 2.5V15", "M12 20.5 5 12.5 19 12.5Z"];
    path.setAttribute("d", d[0]);
    svg.appendChild(path);
    var head = document.createElementNS("http://www.w3.org/2000/svg", "path");
    head.setAttribute("d", d[1]);
    svg.appendChild(head);
    // getTotalLength 要求元素在渲染树里，取完样再摘掉。
    svg.style.cssText = "position:absolute;inline-size:0;block-size:0;overflow:hidden";
    document.body.append(svg);
    var pts = glyphOf(svg, "0 0 24 24");
    svg.remove();
    arrowCache[key] = pts;
    return pts;
  }

  // 箭头落在按钮行以下那条空带里，不压在标题和正文上。位置从量到的盒子算，
  // 不写死：这一节的排版随宽度换过两种，写死的坐标只在其中一种下成立。
  // 宽屏那支箭在 24 的盒子里只占中间一条：横向 1.5–22、纵向 3.5–16。
  // 下面几个数就是这条墨迹的占比，位置和尺寸都从它算，不从盒子算。
  var INK = { w: 20.5 / 24, h: 12.5 / 24, cy: 9.75 / 24, right: 22 / 24 };

  function arrowPlace() {
    var canvas = document.getElementById("field");
    var row = document.querySelector("#hero .row");
    var sceneEl = document.getElementById("scene");
    if (!canvas || !row || !sceneEl) { return null; }
    var c = canvas.getBoundingClientRect();
    var r = row.getBoundingClientRect();
    var s = sceneEl.getBoundingClientRect();
    // 面板在旁边还是在下面，问它自己的位置，不问断点：断点会和布局各改各的。
    var beside = s.left > r.right;
    var h1 = document.querySelector("#hero h1");
    var x, y, span;
    if (beside && h1) {
      // 盒子是正方的，而这支箭是扁的，所以尺寸和位置都按墨迹在盒子里的实际
      // 占比反算：只按盒子摆，上下会空掉一大截，右端也够不到面板。
      var lid = h1.getBoundingClientRect().top;
      var room = (lid - c.top) * 0.9;
      span = Math.max(180, Math.min(380, Math.min(room / INK.h, (s.left - c.left - 40) / INK.w)));
      x = s.left - 24 - INK.right * span + span / 2;
      y = (c.top + lid) / 2 + (0.5 - INK.cy) * span;
    } else {
      // 按钮行与面板之间量到只有 48px，箭头放那儿一定被面板切掉一半。
      // 按钮右边那块（正文以下、面板以上、最后一个按钮以右）是空的，
      // 而且紧挨着要指的东西。
      var tb = document.getElementById("tryIt");
      var lead = document.querySelector("#hero .lead");
      var right = tb ? tb.getBoundingClientRect().right : r.left;
      var edge = lead ? lead.getBoundingClientRect().bottom : r.top;
      span = Math.max(80, Math.min(200, Math.min(r.right - right, s.top - edge) * 0.96));
      x = (right + r.right) / 2;
      y = (edge + s.top) / 2;
    }
    return {
      beside: beside,
      at: (x - c.left) / Math.max(c.width, 1),
      tall: span / Math.max(c.height, 1),
      centre: y - c.top
    };
  }

  var arrowHold = null, arrowDrop = null;

  function arrowPulse() {
    // 静止偏好下这片场只在滚动时重画一帧，彙集会变成一次跳变，不如不做。
    if (!heroField || stillness.matches) { return; }
    var spot = arrowPlace();
    if (!spot) { return; }
    // 上一轮的两个定时器必须先撤。一轮箭头五秒，而按钮三秒就放开，
    // 第二次按下时上一轮那个「撤掉形状」会在新箭头成形到一半时开火，
    // 颗粒当场瞬移——那就是再按一次会卡一下的原因。
    clearTimeout(arrowHold);
    clearTimeout(arrowDrop);
    heroOpts.at = spot.at;
    heroOpts.tall = spot.tall;
    heroCentre = spot.centre;
    heroField.setAim(arrowPoints(spot.beside));
    heroAim = true;
    arrowHold = setTimeout(function () {
      heroAim = false;
      // 形状要等颗粒回到散落的位置再撤。还在形上就撤，它们会瞬移。
      arrowDrop = setTimeout(function () { heroField.setAim(null); }, 2400);
    }, 2600);
  }

  // 读到下面几节的人多半已经滑过了那块面板。这一行把人送回去，等滚动停下
  // 再把彙集跑一次 —— 跳过去只是到了跟前，指出来才算说完。
  function backToPanel() {
    var btn = document.getElementById("tryUp");
    var sceneEl = document.getElementById("scene");
    if (!btn || !sceneEl || btn.dataset.wired === "1") { return; }
    btn.dataset.wired = "1";
    btn.addEventListener("click", function (e) {
      if (e && e.detail > 0 && btn.blur) { btn.blur(); }
      var soft = !stillness.matches;
      sceneEl.scrollIntoView({ behavior: soft ? "smooth" : "auto", block: "center" });
      setTimeout(arrowPulse, soft ? 700 : 0);
    });
  }

  function demoOverlay() {
    var btn = document.getElementById("tryIt");
    var ovlEl = document.getElementById("ovl");
    var sceneEl = document.getElementById("scene");
    if (!btn || !ovlEl || !sceneEl || btn.dataset.wired === "1") { return; }
    btn.dataset.wired = "1";
    var running = false;

    function put(value) {
      state.px = value;
      reflect();
      document.querySelectorAll('[data-bind="px"]').forEach(function (el) {
        if (el.tagName === "INPUT") { el.value = String(value); }
        else { el.textContent = value + " %"; }
      });
    }

    function slide(from, to, ms, then) {
      var t0 = null;
      requestAnimationFrame(function step(now) {
        if (t0 === null) { t0 = now; }
        var k = Math.min(1, (now - t0) / ms);
        // 走的是和面板同一条缓动：读者看到的是这块面板在动，不是一个动画在跑。
        var e = k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
        put(Math.round(from + (to - from) * e));
        if (k < 1) { requestAnimationFrame(step); } else { then(); }
      });
    }

    function play() {
      var from = state.px;
      // 往还有余地的那一边推。停在边上再往外推是看不出来的。
      var to = Math.max(0, Math.min(100, from <= 50 ? from + 26 : from - 26));
      if (stillness.matches) {
        put(to);
        setTimeout(function () { put(from); running = false; }, 700);
        return;
      }
      slide(from, to, 760, function () {
        setTimeout(function () {
          slide(to, from, 880, function () { running = false; });
        }, 300);
      });
    }

    btn.addEventListener("click", function (e) {
      // 鼠标点完不留焦点环。这一页的焦点环是给键盘用的，而一部分浏览器在
      // 鼠标点击之后仍然匹配 :focus-visible，于是按钮上留下一圈亮边。
      // detail 为 0 的是键盘触发的 click，那种要留。
      if (e && e.detail > 0 && btn.blur) { btn.blur(); }
      if (running) { return; }
      running = true;
      // 这里不动 woken。那个标记一设上就不再撤，是留给「读者真的碰过面板」
      // 用的；按钮设它等于把悬浮抬起、移开沉回那一套永久关掉。
      arrowPulse();
      // 锁上时程序本来就不让拖，演示也不该骗人：先把锁打开，
      // 开锁这一下本身就说明了右上角那几个按钮是活的。
      if (state.lock) { apply1("lock", false); }
      var box = ovlEl.getBoundingClientRect();
      var off = box.top < 0 || box.bottom > innerHeight;
      // 箭头先立起来，指够一会儿再让面板动：先说看哪儿，再说它会动。
      var wait = stillness.matches ? 0 : 1100;
      if (off) {
        sceneEl.scrollIntoView({ behavior: stillness.matches ? "auto" : "smooth", block: "center" });
        wait += stillness.matches ? 0 : 520;
      }
      setTimeout(play, wait);
    });
  }

  function dragOverlay() {
    var ovlEl = document.getElementById("ovl");
    var sceneEl = document.getElementById("scene");
    if (!ovlEl || !sceneEl || ovlEl.dataset.draggable === "1") { return; }
    ovlEl.dataset.draggable = "1";
    var from = 0, began = 50, span = 1, dragging = false;

    ovlEl.addEventListener("pointerdown", function (e) {
      // 右上角那几个按钮有自己的活，拖动不抢它们。
      if (state.lock || state.through) { return; }
      if (e.button !== 0 || (e.target.closest && e.target.closest("button"))) { return; }
      dragging = true;
      from = e.clientX;
      began = state.px;
      span = sceneEl.getBoundingClientRect().width;
      ovlEl.setPointerCapture(e.pointerId);
      ovlEl.dataset.dragging = "1";
      e.preventDefault();
    });
    ovlEl.addEventListener("pointermove", function (e) {
      if (!dragging) { return; }
      // 面板的位移是 (px-50)/5 个百分点的内联外边距，左右各一次，
      // 所以滑满 100 点等于走过场景宽度的 20%。
      var moved = (e.clientX - from) / Math.max(span, 1) * 500;
      var next = Math.max(0, Math.min(100, Math.round(began + moved)));
      if (next === state.px) { return; }
      state.px = next;
      reflect();
      // 滑杆在场上就让它跟着走：读者看到的是一个值，不是两个。
      document.querySelectorAll('[data-bind="px"]').forEach(function (el) {
        if (el.tagName === "INPUT") { el.value = String(next); }
        else { el.textContent = next + " %"; }
      });
    });
    ["pointerup", "pointercancel"].forEach(function (kind) {
      ovlEl.addEventListener(kind, function () {
        dragging = false;
        delete ovlEl.dataset.dragging;
      });
    });
  }

  function panel(id) {
    activePanel = id;
    kcard.replaceChildren();
    PANELS[id].forEach(function (spec) { kcard.append(formRow(spec)); });
    knav.querySelectorAll("button").forEach(function (b) {
      if (b.dataset.panel === id) { b.setAttribute("aria-current", "page"); }
      else { b.removeAttribute("aria-current"); }
    });
  }

  if (kcard && knav) {
    knav.replaceChildren();
    Object.keys(PANELS).forEach(function (id, i) {
      var b = document.createElement("button");
      b.type = "button";
      b.dataset.panel = id;
      var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("aria-hidden", "true");
      var use = document.createElementNS("http://www.w3.org/2000/svg", "use");
      use.setAttribute("href", "#n-" + NAV_ICON[id]);
      use.setAttribute("width", "24"); use.setAttribute("height", "24");
      svg.append(use);
      var label = document.createTextNode(msg("settings." + id));
      b.append(svg, label);
      b._localeLabel = label;
      if (i === 0) { b.setAttribute("aria-current", "page"); }
      b.addEventListener("click", function () { panel(id); });
      knav.append(b);
    });
    panel(Object.keys(PANELS)[0]);
    reflect();
    dragOverlay();
    demoOverlay();
    backToPanel();
    wireOverlayChrome();
    localeUpdaters.push(function () {
      knav.querySelectorAll("button").forEach(function (b) {
        b._localeLabel.nodeValue = msg("settings." + b.dataset.panel);
      });
      panel(activePanel || Object.keys(PANELS)[0]);
    });
  }

  /* ---- install: one switcher, one block. Commands are the README's, verbatim.
     A second level appears only where a distribution really has two right
     answers, which here is the AUR helper. ---------------------------------- */
  function liveKeys() {
    return "\n\n# " + msg("get.live.comment") + "\necho 'media-plugins/kotonoha **' | sudo tee /etc/portage/package.accept_keywords/kotonoha\n\nsudo emerge --ask media-plugins/kotonoha::gentoo-zh";
  }
  var RELEASE_API = "https://api.github.com/repos/locez/kotonoha/releases/latest";
  function releaseCommand(suffix, filename, installer) {
    return "set -e\nasset_url=\"$(curl -fsSL " + RELEASE_API + " | jq -r '.assets[] | select(.name | endswith(\"" + suffix + "\")) | .browser_download_url' | head -n 1)\"\ntest -n \"$asset_url\"\n" +
      "curl -fL \"$asset_url\" -o " + filename + "\n" +
      installer + "\n" +
      "rm " + filename;
  }
  var GET = [
    { id: "gentoo", mark: "gentoo", label: "Gentoo",
      note: "",
      helpers: [
        { id: "upstream", labelKey: "get.official",
          cmd: function () { return "sudo emerge --ask app-eselect/eselect-repository\nsudo eselect repository enable gentoo-zh\nsudo emaint sync -r gentoo-zh" + liveKeys(); } },
        { id: "cernet", labelKey: "get.mirror",
          cmd: function () { return "sudo emerge --ask app-eselect/eselect-repository\nsudo eselect repository add gentoo-zh git https://mirrors.cernet.edu.cn/gentoo-zh.git\nsudo emaint sync -r gentoo-zh" + liveKeys(); } },
        { id: "manual", labelKey: "get.manual",
          cmd: function () { return "sudo tee /etc/portage/repos.conf/gentoo-zh.conf <<'EOF'\n[gentoo-zh]\nlocation = /var/db/repos/gentoo-zh\nsync-type = git\nsync-uri = https://mirrors.cernet.edu.cn/gentoo-zh.git\nauto-sync = yes\nEOF\n\nsudo emaint sync -r gentoo-zh" + liveKeys(); } }
      ] },
    { id: "arch", mark: "archlinux", label: "Arch",
      noteKey: "get.arch.note",
      helpers: [
        { id: "paru", label: "paru", cmd: "paru -S kotonoha-git" },
        { id: "yay", label: "yay", cmd: "yay -S kotonoha-git" },
        { id: "makepkg", label: "makepkg", cmd: "git clone https://aur.archlinux.org/kotonoha-git.git\ncd kotonoha-git\nmakepkg -si" }
      ] },
    { id: "nixos", mark: "nixos", label: "NixOS",
      noteKey: "get.nixos.note",
      cmd: 'inputs.kotonoha = {\n  url = "github:locez/kotonoha";\n  inputs.nixpkgs.follows = "nixpkgs";\n};\n\nenvironment.systemPackages = [\n  inputs.kotonoha.packages.${pkgs.stdenv.hostPlatform.system}.default\n];' },
    { id: "deb", mark: "debian", labelKey: "get.deb",
      noteKey: "get.deb.note",
      cmd: releaseCommand("_amd64.deb", "kotonoha.deb", "sudo apt install ./kotonoha.deb") },
    { id: "rpm", mark: "fedora", labelKey: "get.rpm",
      noteKey: "get.rpm.note",
      cmd: releaseCommand(".x86_64.rpm", "kotonoha.rpm", "sudo dnf install ./kotonoha.rpm") },
    { id: "source", mark: "terminal", line: true, labelKey: "get.source",
      noteKey: "get.source.note",
      cmd: "# Arch\nsudo pacman -S cmake qt6-base qt6-wayland layer-shell-qt\n# Gentoo\nsudo emerge -a dev-build/cmake kde-plasma/layer-shell-qt dev-qt/qtwayland\n\ngit clone https://github.com/locez/kotonoha.git\ncd kotonoha\nuv sync\nuv run kotonoha" }
  ];

  var getTabs = document.getElementById("getTabs");
  if (getTabs) {
    var getSub = document.getElementById("getSub");
    var getCmd = document.getElementById("getCmd");
    var getNote = document.getElementById("getNote");
    var picked = GET[0], helper = null;

    function getLabel(item) {
      return item.labelKey ? msg(item.labelKey) : item.label;
    }
    function getCommand(item) {
      return typeof item.cmd === "function" ? item.cmd() : (item.cmd || "");
    }

    function show() {
      getCmd.textContent = getCommand(helper || picked);
      getNote.textContent = picked.noteKey ? msg(picked.noteKey) : (picked.note || "");
      getSub.hidden = !picked.helpers;
      getTabs.querySelectorAll("button").forEach(function (b) {
        b.setAttribute("aria-selected", String(b.dataset.get === picked.id));
      });
      if (picked.helpers) {
        getSub.querySelectorAll("button").forEach(function (b) {
          b.setAttribute("aria-selected", String(helper && b.dataset.helper === helper.id));
        });
      }
    }
    function chooseHelpers() {
      getSub.replaceChildren();
      // Cleared first: without this, switching from Arch to NixOS kept the AUR
      // helper and printed paru's command under the NixOS note.
      helper = null;
      if (!picked.helpers) { return; }
      picked.helpers.forEach(function (h, i) {
        var b = document.createElement("button");
        b.type = "button"; b.role = "tab"; b.dataset.helper = h.id;
        var label = document.createTextNode(getLabel(h));
        b.append(label); b._localeLabel = label; b._getHelper = h;
        b.addEventListener("click", function () { helper = h; show(); });
        getSub.append(b);
      });
      helper = picked.helpers[0];
    }
    GET.forEach(function (entry) {
      var b = document.createElement("button");
      b.type = "button"; b.role = "tab"; b.dataset.get = entry.id;
      if (entry.mark) {
        var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("viewBox", "0 0 24 24");
        svg.setAttribute("aria-hidden", "true");
        if (entry.line) { svg.setAttribute("class", "line"); }
        var use = document.createElementNS("http://www.w3.org/2000/svg", "use");
        use.setAttribute("href", "#m-" + entry.mark);
        use.setAttribute("width", "24"); use.setAttribute("height", "24");
        svg.append(use); b.append(svg);
      }
      var label = document.createTextNode(getLabel(entry));
      b.append(label); b._localeLabel = label; b._getEntry = entry;
      b.addEventListener("click", function () { picked = entry; chooseHelpers(); show(); });
      getTabs.append(b);
    });
    chooseHelpers();
    show();
    localeUpdaters.push(function () {
      getTabs.querySelectorAll("button").forEach(function (b) {
        b._localeLabel.nodeValue = getLabel(b._getEntry);
      });
      getSub.querySelectorAll("button").forEach(function (b) {
        b._localeLabel.nodeValue = getLabel(b._getHelper);
      });
      show();
    });

    // Copy reads the pane on screen, and falls back where the clipboard API is
    // absent — a page served over plain http does not get one.
    var status = document.getElementById("getStatus");
    document.getElementById("getCopy").addEventListener("click", function () {
      var btn = this, text = getCmd.textContent;
      var label = document.getElementById("getCopyLabel");
      function done() {
        btn.dataset.state = "done";
        // Said on screen as well as to a screen reader: a colour change alone is
        // not feedback for anyone who did not already know the button copied.
        if (label) { label.textContent = msg("copied"); }
        status.textContent = msg("copied");
        setTimeout(function () {
          btn.dataset.state = "";
          if (label) { label.textContent = msg("copy"); }
          status.textContent = "";
        }, 1600);
      }
      if (navigator.clipboard && window.isSecureContext) {
        // The rejection path matters: a denied permission used to leave the
        // reader with no feedback at all, which reads as a dead button.
        navigator.clipboard.writeText(text).then(done, legacy);
      } else {
        legacy();
      }
      function legacy() {
        var box = document.createElement("textarea");
        box.value = text; box.setAttribute("readonly", "");
        box.style.position = "absolute"; box.style.left = "-9999px";
        document.body.append(box); box.select();
        try { document.execCommand("copy"); done(); } finally { box.remove(); }
      }
    });
  }

  /* ---- entry ------------------------------------------------------------
     One mechanism for every browser: an observer marks a block seen and the
     stylesheet moves it in. This was written as a fallback behind
     `CSS.supports("animation-timeline: view()")` and that was the wrong
     question — a browser can parse the declaration and animate nothing, and
     then the stylesheet's scroll-driven version and this one both stand down,
     which is a page with no entry at all. The hidden state is written under
     [data-reveal="js"], set here, so a page whose script never runs is the
     finished page rather than a blank one. */
  if (!stillness.matches) {
    root.dataset.reveal = "js";
    var seen = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.dataset.seen = "1"; return; }
        // Left downwards, meaning the reader scrolled back up past it: forget
        // it so it arrives again on the way down. Marking it seen once and
        // unobserving gave the effect exactly one showing per page load, and a
        // second pass down the page had nothing left to play.
        if (e.boundingClientRect.top > 0) { delete e.target.dataset.seen; }
      });
    }, { rootMargin: "0px 0px -18% 0px", threshold: 0.12 });
    // Result rows are rebuilt on every sort, so they are left out: an element
    // created after the observer ran never gets marked, and the hidden half of
    // the rule would keep it hidden for good.
    var waiting = [].slice.call(
      document.querySelectorAll(".rise, .sec-head--top > *, .rail-body > *"));
    waiting.forEach(function (el) { seen.observe(el); });
    // The bottom margin above means an element sitting at the very end of the
    // page can be on screen and still never cross the line — the page has no
    // more scroll to give. Anything still waiting when the page bottom is
    // reached is shown, because a footer that never arrives is a footer that
    // is missing.
    addEventListener("scroll", function () {
      if (window.scrollY + window.innerHeight < root.scrollHeight - 2) { return; }
      waiting.forEach(function (el) { el.dataset.seen = "1"; });
    }, { passive: true });
  }

  /* ---- the point clouds --------------------------------------------------
     The section opens with the mark drawn out of the same flecks the hero
     field is made of — short coloured strokes, not dots — and then each panel
     draws its own icon the same way. Points are sampled from the markup's own
     <svg>, rasterised once through an image, so no artwork is kept twice. */
  /* Points are walked along the artwork's own geometry with getPointAtLength,
     not read back out of a rasterised copy. The raster route put the flecks
     wherever a 2px sampling lattice happened to cross the ink, which on a mark
     with fine curves came out as a smear; on the path they land on the line. */
  function glyphOf(src, box) {
    var vb = (box || "0 0 24 24").trim().split(/[\s,]+/).map(Number);
    var shapes = [].slice.call(src.querySelectorAll("path,circle,rect,line,polyline,polygon"));
    var lens = shapes.map(function (el) {
      try { return el.getTotalLength ? el.getTotalLength() : 0; } catch (err) { return 0; }
    });
    var total = lens.reduce(function (a, b) { return a + b; }, 0);
    if (!total) { return []; }
    // Spacing along the path, not a fixed count: a fixed count packs a short
    // outline like the sun solid while leaving a long one like the note thin.
    var want = Math.max(200, Math.min(1400, Math.round(total / (vb[2] * 0.0042))));
    var pts = [];
    shapes.forEach(function (el, i) {
      if (!lens[i]) { return; }
      var n = Math.max(2, Math.round(want * lens[i] / total));
      for (var k = 0; k < n; k++) {
        var p = el.getPointAtLength(lens[i] * (k + 0.5) / n);
        pts.push([(p.x - vb[0]) / vb[2], (p.y - vb[1]) / vb[3]]);
      }
    });
    return pts;
  }

  function dotField(canvas, opts) {
    var g = canvas.getContext("2d");
    var ddpr = Math.min(window.devicePixelRatio || 1, 3);
    var motes = [], hues = [], aim = null, live = false, centre = 0, gather = 0;
    var sown = 0;
    var pointer = { x: -1e4, y: -1e4 };

    function readHues() {
      var cs = getComputedStyle(document.documentElement);
      hues = ["--preset-pink", "--preset-cyan", "--preset-green", "--preset-gold", "--accent"]
        .map(function (t) { return cs.getPropertyValue(t).trim(); })
        .filter(Boolean);
      // 颜色挂在每颗自己的号上，不挂在它在数组里的下标上：形状是按步长取的，
      // 步长一旦和颜色数成倍数（彙集那一节正好是 5），选中的就永远是同一色。
      motes.forEach(function (m) { m.hue = hues[m.tint % hues.length]; });
    }
    function size() {
      var r = canvas.getBoundingClientRect();
      canvas.width = Math.round(r.width * ddpr);
      canvas.height = Math.round(r.height * ddpr);
      // A pinned canvas needs enough flecks for the whole thing it scrolls
      // over, not just for one screen of it.
      var reach = opts.scrollWith ? opts.scrollWith.getBoundingClientRect().height : r.height;
      var tall = Math.max(r.height, reach);
      // A fleck's home is normalised, so it keeps its place through a change of
      // box and only the number of them depends on the area. Reseeding on every
      // box change threw the whole field away twice a chorus: a lyric line that
      // wraps grows the panel, and the hero with it, by two pixels, and the
      // observer fired. Reseed only when the box genuinely calls for a
      // different number of flecks.
      var want = countFor(r.width, tall);
      if (!motes.length || Math.abs(want - sown) > sown * 0.12) { seed(r.width, tall); }
      centre = r.height / 2;
    }
    // Scatter homes sit on a jittered grid rather than at random points: pure
    // random clumps, and a field that clumps reads as dirt on the screen.
    function countFor(w, h) {
      // 下限是给整屏宽的场设的；卡片那么小的画布按这个下限播，就成了一锅碎纸。
      return Math.max(opts.seedMin || 800, Math.min(2600, Math.round((w * h) / 1600)));
    }
    function seed(w, h) {
      var count = countFor(w, h);
      sown = count;
      var cols = Math.max(1, Math.round(Math.sqrt(count * (w / Math.max(h, 1)))));
      var rows = Math.max(1, Math.ceil(count / cols));
      motes = [];
      for (var i = 0; i < count; i++) {
        var gx = (i % cols + 0.5) / cols, gy = ((i / cols) | 0) / rows + 0.5 / rows;
        motes.push({
          x: Math.random() * w, y: Math.random() * h, vx: 0, vy: 0,
          // Scattered over two and a half cells rather than inside one: a
          // mote per cell is a lattice, and a lattice is what the eye reads
          // first. Overlapping cells clump and leave gaps, which is what a
          // scatter looks like.
          hx: -0.14 + 1.28 * Math.min(1, Math.max(0, gx + (Math.random() - 0.5) * 2.5 / cols)),
          hy: -0.14 + 1.28 * Math.min(1, Math.max(0, gy + (Math.random() - 0.5) * 2.5 / rows)),
          len: (7 + Math.random() * 12) * (opts.len || 1),
          a: Math.random() * Math.PI,
          spin: (Math.random() - 0.5) * 0.004,
          alpha: 0.3 + Math.random() * 0.5,
          // Each fleck keeps its own small offset from the point it is aimed
          // at. The sampler walks a 2px lattice, and a glyph drawn straight
          // onto that lattice reads as print rather than as a swarm.
          turn: Math.random(),
          tint: Math.floor(Math.random() * 5),
          jx: (Math.random() - 0.5) * 0.062,
          jy: (Math.random() - 0.5) * 0.062,
          hue: ""
        });
      }
      // 播完统一按各自的号上色，和 readHues 用同一条规则。
      motes.forEach(function (m) { m.hue = hues[m.tint % Math.max(hues.length, 1)]; });
    }
    function step(still) {
      var w = canvas.width / ddpr, h = canvas.height / ddpr;
      g.setTransform(ddpr, 0, 0, ddpr, 0, 0);
      g.clearRect(0, 0, w, h);
      var span = Math.min(w * opts.fill, h * (opts.tall || 0.66));
      var ox = w * (opts.at === undefined ? 0.5 : opts.at) - span / 2;
      var at = opts.centreOf(canvas, h);
      // Gathering runs on its own clock, not on the scroll offset. Tied to the
      // offset, stopping halfway left the flecks halfway — a state that is
      // neither the scatter nor the glyph. Now a new glyph starts the animation
      // and it finishes wherever the reader stops.
      // Gathering waits until the panel is actually near the middle of the
      // screen. Starting when the section merely intersects meant the glyph was
      // already assembled at the bottom of the hero, before the reader had
      // arrived at it.
      var target = at.ready === false ? 0 : 1;
      gather = still ? target : gather + (target - gather) * 0.032;
      var pull = gather;
      centre = still ? at.centre : centre + (at.centre - centre) * 0.22;
      // The glyph follows its panel and is allowed to run off the canvas as the
      // panel leaves, the way the copy does. Clamped to half a canvas it sat
      // pinned at the top edge while its own copy was in the middle, which
      // reads as stuck rather than as attached to anything.
      var half = span * 0.34;
      var oy = Math.min(Math.max(centre, half), h - half) - span / 2;
      g.lineCap = "round";
      g.lineWidth = opts.weight || 5;
      // The scatter needs flecks for the whole scrolled height; the glyph needs
      // far fewer or it packs solid. So a fixed quota draws the shape, cycling
      // through the outline's points, and every fleck outside the quota fades
      // to nothing as the shape stands — leaving it at a low alpha instead put
      // a crowd around the glyph, worst on a short outline like the sun.
      // 取的是「每隔几颗取一颗」，不是「前几颗」。颗粒是按行播种的，取前 460 颗
      // 等于只征用最上面那几行：形状底下那一片从头到尾没参与过，看起来就是
      // 上半边散开、下半边一直空着。跨步取则整片都在动。
      var used = aim ? Math.min(motes.length, opts.quota || 460) : 0;
      var stride = used ? Math.max(1, Math.floor(motes.length / used)) : 0;
      var picked = stride ? Math.ceil(motes.length / stride) : 1;
      var count = aim ? aim.length : 1;
      var pace = count / Math.max(picked, 1);
      var faint = 0.22;
      for (var i = 0; i < motes.length; i++) {
        var tx, ty;
        var drawn = stride > 0 && i % stride === 0;
        var m = motes[i];
        // The scatter belongs to the page, not to the canvas. On a canvas that
        // is pinned to the viewport, homes measured in canvas coordinates stand
        // still while everything around them scrolls, which reads as a fixed
        // layer of specks stuck over the section.
        var hx = m.hx * w, hy;
        if (opts.scrollWith) {
          var hostBox = opts.scrollWith.getBoundingClientRect();
          var ownBox = canvas.getBoundingClientRect();
          hy = m.hy * hostBox.height + (hostBox.top - ownBox.top);
        } else {
          hy = m.hy * h;
        }
        // Each fleck crosses at its own point in the scroll. Moving them all
        // together only shrinks the scatter toward the glyph, which reads as a
        // lump; staggered, half of them are still loose while half have landed,
        // and that reads as gathering.
        var mix = drawn ? Math.min(1, Math.max(0, (pull - m.turn * 0.72) / 0.28)) : 0;
        mix = mix * mix * (3 - 2 * mix);
        if (drawn) {
          var pt = aim[Math.floor((i / stride) * pace) % count];
          tx = hx + (ox + (pt[0] + m.jx) * span - hx) * mix;
          ty = hy + (oy + (pt[1] + m.jy) * span - hy) * mix;
        }
        else { tx = hx; ty = hy; }
        if (still) { m.x = tx; m.y = ty; }
        else {
          var dx = m.x - pointer.x, dy = m.y - pointer.y, d2 = dx * dx + dy * dy;
          if (d2 < 26000) {
            var d = Math.sqrt(d2) || 1;
            var push = (1 - d / 161) * 3.4;
            m.vx += (dx / d) * push; m.vy += (dy / d) * push;
          }
          m.vx += (tx - m.x) * 0.05; m.vy += (ty - m.y) * 0.05;
          m.vx *= 0.85; m.vy *= 0.85;
          m.x += m.vx; m.y += m.vy;
          m.a += m.spin;
        }
        var len = m.len;
        var ex = Math.cos(m.a) * len, ey = Math.sin(m.a) * len;
        g.strokeStyle = m.hue;
        // The flecks with no place on the glyph clear out in the first third of
        // the gather rather than fading with it: fading at the same rate as the
        // shape appears, they read as part of the shape arriving.
        // A field with no glyph to form is all "loose" and must not fade at all:
        // the hero and the two window sections are nothing but loose flecks.
        // 淡出的陡度可调。彙集那一节要的是杂散颗粒快速消失，而英雄区这支箭头
        // 是按出来的：3.5 让它们在 0.2 秒内整片开关一次，散回时就像凭空冒出来。
        var weight = drawn ? faint + (1 - faint) * mix
                   : aim ? faint * Math.max(0, 1 - pull * (opts.shed || 3.5)) : faint;
        g.globalAlpha = Math.min(1, m.alpha + 0.55) * weight;
        g.beginPath();
        g.moveTo(m.x - ex / 2, m.y - ey / 2);
        g.lineTo(m.x + ex / 2, m.y + ey / 2);
        g.stroke();
      }
      g.globalAlpha = 1;
    }
    function frame() { step(false); if (live) { requestAnimationFrame(frame); } }

    readHues(); size();
    // The box changes without the window changing: a breakpoint swaps the
    // canvas between two layouts, a scrollbar appears, a font lands. When that
    // happened the backing store kept its old size and the flecks were drawn
    // into part of the canvas with the rest left blank.
    if (window.ResizeObserver) {
      var box = new ResizeObserver(function () { size(); });
      box.observe(canvas);
    } else {
      window.addEventListener("resize", size);
    }
    new MutationObserver(readHues)
      .observe(root, { attributes: true, attributeFilter: ["data-theme", "style"] });
    return {
      setAim: function (pts) {
        // Changing glyph does not restart the gather. Restarting it meant that
        // arriving at a panel showed nothing at all for a second or two while
        // the flecks flew in from the scatter again, which reads as broken.
        // Entering the section still gathers from scratch, because `ready` puts
        // the whole thing back to nought while no panel is near the middle.
        aim = pts && pts.length ? pts : null;
      },
      still: function () { step(true); },
      watch: function (host) {
        if (stillness.matches) {
          window.addEventListener("scroll", function () { step(true); }, { passive: true });
          step(true);
          return;
        }
        new IntersectionObserver(function (entries) {
          var on = entries[0].isIntersecting;
          if (on && !live) { live = true; requestAnimationFrame(frame); }
          if (!on) { live = false; }
        }, { threshold: 0 }).observe(host);
        host.addEventListener("pointermove", function (e) {
          if (!pointerOk) { return; }
          var r = canvas.getBoundingClientRect();
          pointer.x = e.clientX - r.left; pointer.y = e.clientY - r.top;
        });
        host.addEventListener("pointerleave", function () { pointer.x = -1e4; pointer.y = -1e4; });
      }
    };
  }

  var does = document.getElementById("does");

  var capsCanvas = document.getElementById("capsFx");
  if (does && capsCanvas) {
    var panels = [].slice.call(document.querySelectorAll(".cap"));
    var clouds = [];
    // Which panel is centred is a geometry question, so it is answered from
    // geometry. An observer answered it from the order its entries arrived in,
    // which put panel five's glyph beside panel four's copy.
    // The nearest panel to the middle of the screen, so there is always one to
    // stand for while the section is on screen. Requiring the middle to be
    // inside a panel left a gap between two of them with nothing to draw.
    var lit = !(window.CSS && CSS.supports && CSS.supports("animation-timeline: view()"));
    // Plainly the nearest panel to the middle of the screen. This carried
    // hysteresis for a while, to stop the pick flipping at the border between
    // two panels — but a panel stays in the viewport long after it stops being
    // the nearest, so holding it meant the pick jumped from the first panel to
    // the last and the ones between never got their turn. Flipping costs
    // nothing now: a change of glyph retargets the flecks instead of sending
    // them back to the scatter.
    function centredPanel() {
      var mid = window.innerHeight / 2, best = -1, near = Infinity;
      for (var i = 0; i < panels.length; i++) {
        var r = panels[i].getBoundingClientRect();
        if (r.bottom < 0 || r.top > window.innerHeight) { continue; }
        var d = Math.abs((r.top + r.bottom) / 2 - mid);
        if (d < near) { near = d; best = i; }
      }
      return best;
    }
    var capsField = dotField(capsCanvas, {
      // 画布从 1296 变成整屏宽之后，同一个比例会把图标往右挪 33px；这里换成
      // 让它落在原来那个位置上的比例。
      fill: 0.42, at: 0.707, scrollWith: capsCanvas.parentNode,
      centreOf: function (c, h) {
        // On a narrow screen the copy runs the full width and the canvas sits
        // straight behind it, so a gathered glyph lands on the words. There the
        // field stays loose and stays background.
        if (window.innerWidth < 992) { return { centre: h / 2, ready: false }; }
        var i = centredPanel();
        capsField.setAim(i >= 0 ? clouds[i] : null);
        if (i < 0) { return { centre: h / 2, ready: false }; }
        var box = c.getBoundingClientRect(), pr = panels[i].getBoundingClientRect();
        var mid = window.innerHeight / 2;
        if (lit) {
          // Same dimming the stylesheet does with a view() timeline, for the
          // browsers that do not have one.
          panels.forEach(function (panel, k) {
            var b = panel.getBoundingClientRect();
            var d = Math.abs((b.top + b.bottom) / 2 - mid) / window.innerHeight;
            panel.style.opacity = Math.max(0.4, 1 - d * 1.4).toFixed(2);
          });
        }
        return {
          centre: (pr.top + pr.bottom) / 2 - box.top,
          ready: Math.abs((pr.top + pr.bottom) / 2 - mid) < window.innerHeight * 0.36
        };
      }
    });
    panels.forEach(function (panel, i) {
      var src = panel.querySelector(".cap__hd svg");
      if (src) { clouds[i] = glyphOf(src, "0 0 24 24"); }
    });
    capsField.watch(capsCanvas.parentNode);
  }

  /* The same flecks with nothing to gather into. One implementation covers the
     hero and the two window sections as well, so the four cannot drift into
     four looks. */
  [["field", "hero"], ["fx-search", "search"], ["fx-get", "get"]].forEach(function (pair) {
    var canvas = document.getElementById(pair[0]);
    var host = document.getElementById(pair[1]);
    if (canvas && host) {
      // 播一块场要遍历上千颗，四块在加载时一起播，量到占了启动那个 159ms 长任务里的
      // 一百毫秒，而那一刻最多只有一两块在视口里。等它快进画面了再建。
      var start = function () {
        var hero = pair[0] === "field";
        // Only the hero has a shape to make, and only while the reader has asked
        // for it: `ready` is what the gather runs off, so a false here keeps this
        // field a plain scatter exactly as the other two are.
        var opts = hero
          ? {
              fill: 0.5, at: 0.34, tall: 0.4, shed: 1.15, quota: 300,
              // Where the reader is looking, not the middle of the canvas. On a
              // narrow screen this section is several screens tall, so its middle
              // is far below the fold: the flecks all left to build a shape
              // nobody could see, and the hero simply emptied.
              centreOf: function (c, h) {
                var r = c.getBoundingClientRect();
                // 有量好的位置就用它；还没按过按钮时退回视口中央，那时也没有形状。
                var y = heroCentre === null ? innerHeight / 2 - r.top : heroCentre;
                return { centre: Math.min(Math.max(y, 0), h), ready: heroAim };
              }
            }
          : { fill: 0.5, centreOf: function (c, h) { return { centre: h / 2 }; } };
        var made = dotField(canvas, opts);
        made.watch(host);
        if (hero) { heroField = made; heroOpts = opts; }
      };
      var near = new IntersectionObserver(function (es) {
        if (!es[0].isIntersecting) { return; }
        near.disconnect();
        start();
      }, { rootMargin: "300px" });
      near.observe(host);
    }
  });

  /* 两个去处各带一块场：指针进来才彙集，离开就散回去。能力那一节是滚到中间
     就聚，这里是移过去才聚 —— 同一批颗粒、同一个动作，触发的人不同。 */
  /* 一圈圆角框，不是一个图形：图形有实心的笔画，会从文字和按钮身上穿过去 ——
     箭头和星都是这样，无论放多大都在字上划一道。框的笔画只走外围，文字落在
     它围出来的空里，这也正是那张参考图里的做法。 */
  /* 各聚各的符号：一支指针说「去试」，一颗星说「给星」。框虽然能把文字围住，
     却把两块的区别一起抹平了 —— 这一节的意思本来就在符号上。 */
  var ENDS = {
    endTry: "M3 3 10.07 19.97 12.58 12.58 19.97 10.07Z",
    endRepo: "M12 2.6 14.9 8.5 21.4 9.4 16.7 14 17.8 20.5 12 17.5 6.2 20.5 7.3 14 2.6 9.4 9.1 8.5Z"
  };
  Object.keys(ENDS).forEach(function (id) {
    var host = document.getElementById(id);
    var canvas = host && host.querySelector(".end__fx");
    if (!canvas) { return; }
    var on = false;
    var field = dotField(canvas, {
      // 形状要比这段字大一圈，才像围着它而不是压在它上面；同时点少一些，
      // 让它读起来是一圈颗粒勾出来的轮廓，不是一团实心。
      // 细一点短一点：参考里那圈是细点勾出来的，而这一页默认的碎片是 5px 宽、
      // 最长 19px 的粗划，同样的形状会显得笨重。
      fill: 0.95, tall: 0.96, quota: 220, shed: 1.5, seedMin: 180, weight: 3, len: 0.5,
      centreOf: function (c, h) { return { centre: h / 2, ready: on }; }
    });
    field.watch(host);
    // 静止偏好下这片场只在滚动时重画一帧，彙集会变成一次跳变，不如不做。
    if (stillness.matches) { return; }
    host.addEventListener("pointerenter", function () {
      field.setAim(pathPoints(ENDS[id]));
      on = true;
    });
    host.addEventListener("pointerleave", function () { on = false; });
  });

  if (capsCanvas) {
  }

  /* The rows and the two lower blocks drift a little as the page scrolls, off
     for reduced motion. */
  var cells = [].slice.call(document.querySelectorAll(".cap, .swin, .get"));
  if (cells.length && !stillness.matches) {
    var ticking = false;
    function drift() {
      var h = window.innerHeight;
      cells.forEach(function (cell, i) {
        var r = cell.getBoundingClientRect();
        var mid = (r.top + r.height / 2) / h;          // 0 at the top, 1 at the bottom
        var depth = 1 + (i % 3) * 0.6;                  // three lanes, so a row is not one block
        cell.style.setProperty("--drift", ((0.5 - mid) * 14 * depth).toFixed(1) + "px");
      });
      ticking = false;
    }
    addEventListener("scroll", function () {
      if (!ticking) { ticking = true; requestAnimationFrame(drift); }
    }, { passive: true });
    drift();
  }

  /* ---- the search window ------------------------------------------------
     Sorting is the point of this demo: neither column sorts on what it shows.
     "高" falls under "中" alphabetically and "4:03" under "10:00", so match
     sorts by rank and length by seconds. */
  var RESULTS = [
    { src: "A", srcKey: "search.sourceA", title: "何度でも立ち上がれ", artist: "结束乐队", album: "结束バンド", len: 243, ver: "逐字", verKey: "search.verWord", conf: 2 },
    { src: "B", srcKey: "search.sourceB", title: "何度でも立ち上がれ (TV Size)", artist: "结束乐队", album: "TV 主题曲集", len: 89, ver: "逐行", verKey: "search.verLine", conf: 1 },
    { src: "C", srcKey: "search.sourceC", title: "何度でも立ち上がれ (Live)", artist: "结束乐队", album: "现场辑", len: 267, ver: "逐行", verKey: "search.verLine", conf: 0 },
    { src: "A", srcKey: "search.sourceA", title: "何度でも立ち上がれ (Instrumental)", artist: "结束乐队", album: "结束バンド", len: 241, ver: "无时间", verKey: "search.verNone", conf: 0 },
    { src: "D", srcKey: "search.sourceD", title: "何度でも立ち上がれ", artist: "结束乐队", album: "结束バンド", len: 243, ver: "逐字 · 带翻译", verKey: "search.verTranslation", conf: 2 },
    { src: "B", srcKey: "search.sourceB", title: "立ち上がれ", artist: "另一位歌手", album: "单曲", len: 198, ver: "逐行", verKey: "search.verLine", conf: 1 }
  ];
  var CONF = [
    { key: "none", labelKey: "search.confNone" },
    { key: "mid", labelKey: "search.confMid" },
    { key: "high", labelKey: "search.confHigh" }
  ];

  var res = document.getElementById("res");
  if (res) {
    var sortKey = "conf", sortDown = true, chosen = 0, highOnly = false;
    var body = res.querySelector("tbody");

    function clock(sec) {
      var m = Math.floor(sec / 60), s2 = sec % 60;
      return m + ":" + (s2 < 10 ? "0" : "") + s2;
    }
    function rows() {
      var list = RESULTS.map(function (r, i) { return Object.assign({ i: i }, r); });
      if (highOnly) { list = list.filter(function (r) { return r.conf === 2; }); }
      var pick = { src: "src", title: "title", artist: "artist", album: "album", len: "len", ver: "ver", conf: "conf" }[sortKey];
      list.sort(function (a, b) {
        var x = a[pick], y = b[pick];
        var out = typeof x === "number" ? x - y : String(x).localeCompare(String(y), "zh-Hans");
        return sortDown ? -out : out;
      });
      return list;
    }
    function paintRes() {
      var list = rows();
      body.replaceChildren();
      list.forEach(function (r) {
        var tr = document.createElement("tr");
        tr.setAttribute("aria-selected", String(r.i === chosen));
        [
          { text: msg(r.srcKey), cls: "src" },
          r.title,
          r.artist,
          r.album,
          { text: clock(r.len), cls: "num" },
          { text: msg(r.verKey), cls: "ver" },
          { conf: r.conf }
        ].forEach(function (cell) {
          var td = document.createElement("td");
          if (cell && cell.conf !== undefined) {
            var tag = document.createElement("span");
            tag.className = "conf";
            tag.dataset.c = CONF[cell.conf].key;
            tag.textContent = msg(CONF[cell.conf].labelKey);
            td.append(tag);
          } else if (cell && cell.text !== undefined) {
            td.className = cell.cls; td.textContent = cell.text;
          } else {
            td.textContent = cell;
          }
          tr.append(td);
        });
        tr.addEventListener("click", function () { chosen = r.i; paintRes(); });
        body.append(tr);
      });
      res.querySelectorAll("th button").forEach(function (b) {
        if (b.dataset.sort === sortKey) {
          b.setAttribute("aria-sort", sortDown ? "descending" : "ascending");
          b.dataset.mark = sortDown ? "▾" : "▴";
        } else {
          b.removeAttribute("aria-sort"); b.removeAttribute("data-mark");
        }
      });
      var hidden = RESULTS.length - list.length;
      var count = msg("search.count").replace("%n", String(list.length));
      if (hidden) { count += msg("search.hidden").replace("%n", String(hidden)); }
      document.getElementById("swCount").textContent = count;
      document.getElementById("swMiss").textContent = msg("search.unavailable");
    }
    res.querySelectorAll("th button").forEach(function (b) {
      b.addEventListener("click", function () {
        if (sortKey === b.dataset.sort) { sortDown = !sortDown; }
        else { sortKey = b.dataset.sort; sortDown = true; }
        paintRes();
      });
    });
    document.getElementById("swHigh").addEventListener("change", function () {
      highOnly = this.checked; paintRes();
    });
    paintRes();
    localeUpdaters.push(function () { paintRes(); });
  }

  var scene = document.getElementById("scene");
  if (scene) {
    // Each layer answers the pointer by its own depth, and the whole thing eases
    // toward the target on a frame loop rather than snapping: a tilt that lands
    // instantly reads as a jump, and one shared angle reads as a flat picture
    // sliding. Depth is a number per layer, not a rule per element.
    // Depth per layer. The desk leans the other way, which is what makes the
    // windows read as standing off it rather than painted on it.
    var DEPTH = { desk: -0.35, kwin: 0.85, ovl: 1.5 };
    var want = { x: 0.5, y: 0.5 }, have = { x: 0.5, y: 0.5 }, live = false;

    track(scene, function (el, x, y) { want.x = x; want.y = y; });
    scene.addEventListener("pointerenter", function () { live = true; });
    scene.addEventListener("pointerleave", function () { live = false; want.x = 0.5; want.y = 0.5; });

    function ease() {
      have.x += (want.x - have.x) * 0.1;
      have.y += (want.y - have.y) * 0.1;
      var dx = have.x - 0.5, dy = 0.5 - have.y;
      scene.querySelectorAll(":scope > *").forEach(function (layer) {
        var d = DEPTH[layer.classList[0]] || 0.6;
        layer.style.setProperty("--ry", (dx * 26 * d).toFixed(2) + "deg");
        layer.style.setProperty("--rx", (dy * 18 * d).toFixed(2) + "deg");
        layer.style.setProperty("--px", (-dx * 46 * d).toFixed(1) + "px");
        layer.style.setProperty("--py", (-dy * 30 * d).toFixed(1) + "px");
        layer.style.setProperty("--cast", (dx * 30 * d).toFixed(1) + "px");
      });
      requestAnimationFrame(ease);
    }
    if (pointerOk) { requestAnimationFrame(ease); }
  }
  var stack = document.getElementById("stack");
  if (stack) {
    stack.querySelectorAll("[data-card]").forEach(function (card) {
      card.addEventListener("click", function () { stack.dataset.front = card.dataset.card; });
    });
    function markDepth() {
      stack.querySelectorAll("[data-card]").forEach(function (card) {
        card.dataset.depth = card.dataset.card === stack.dataset.front ? "front" : "back";
      });
    }
    new MutationObserver(markDepth).observe(stack, { attributes: true, attributeFilter: ["data-front"] });
    markDepth();

    track(stack, function (el, x, y) {
      var cards = el.querySelectorAll("[data-card]");
      var ry = ((x - 0.5) * 14).toFixed(2) + "deg";
      var rx = ((0.5 - y) * 9).toFixed(2) + "deg";
      cards.forEach(function (c) { c.style.setProperty("--ry", ry); c.style.setProperty("--rx", rx); });
      // The badges drift the other way, which is what reads as depth rather
      // than as the whole picture sliding.
      el.querySelectorAll(".orbit").forEach(function (o, i) {
        var pull = (i % 2 ? -1 : 1) * 14;
        o.style.setProperty("--ox", ((0.5 - x) * pull).toFixed(1) + "px");
        o.style.setProperty("--oy", ((0.5 - y) * pull).toFixed(1) + "px");
      });
    });
  }

  document.querySelectorAll(".tilt").forEach(function (frame) {
    track(frame, function (el, x, y) {
      var inner = el.firstElementChild;
      if (!inner) { return; }
      inner.style.setProperty("--ry", ((x - 0.5) * 10).toFixed(2) + "deg");
      inner.style.setProperty("--rx", ((0.5 - y) * 10).toFixed(2) + "deg");
    });
  });
