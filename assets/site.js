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
      "chip.draft": "设计语言 · 草案",
      "hero.title": "Wayland 桌面歌词",
      "hero.lead": "Kotonoha 通过 D-Bus 读取 MPRIS 播放状态，在 Wayland 图层上显示逐字歌词。支持任意 MPRIS 播放器，无需播放器插件。",
      "hero.install": "安装",
      "nav.design": "设计语言",
      "nav.home": "首页",
      "design.title": "网站长得像程序，<br>因为值是同一份。",
      "design.lead": "颜色一个都不另取——全部来自 <code>theme.py</code> 与 <code>models.py</code>。这一页记录取值、组件，以及哪些规则能报红。",
      "s.calibrate": "先答五个问题",
      "s.color": "颜色",
      "s.type": "字级",
      "s.shape": "圆角与间距",
      "s.parts": "组件",
      "s.parts.lead": "一个角色一份实现。它们在这里并排出现，是因为一起看才看得出哪一个跑偏了。",
      "s.does": "能力与前提",
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
      "s.motion": "动效预算",
      "s.not": "刻意不做",
      "s.get": "安装",
      "get.lead": "Gentoo 用 <code>gentoo-zh</code>，Arch 用 AUR 的 <code>kotonoha-git</code>，NixOS 用 flake；Debian/Ubuntu 可直接安装 DEB，Fedora 等 RPM 系可安装 RPM，也可以从源码构建。",
      "eb.does": "概览",
      "eb.search": "歌词来源",
      "eb.get": "软件包",
      "s.red": "什么能报红",
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
    var lock = document.getElementById("ovlLock");
    if (lock) {
      lock.addEventListener("click", function () {
        var on = lock.getAttribute("aria-pressed") !== "true";
        lock.setAttribute("aria-pressed", String(on));
        lock.setAttribute("aria-label", on ? msg("aria.lockedPosition") : msg("aria.lockPosition"));
      });
    }
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
                trans: true, word: true, nudge: 0, px: 50, through: false, lock: true,
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
      var out = document.createElement("b");
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
    ovlEl.style.setProperty("--ovl-shift", (state.px - 50) / 5 + "%");
    document.querySelectorAll(".kwin, .scene .ovl").forEach(function (w) {
      w.style.backdropFilter = state.frost ? "" : "none";
    });
    // The setting moves the surface, not the text: fading the whole scene is
    // what made it read as a cheap demo rather than as the program.
    root.style.setProperty("--win-alpha", state.opacity + "%");
    if (typeof setWordTiming === "function") { setWordTiming(state.word); }
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
      document.querySelectorAll(".rise, .sec-head--top > *, .rail-body > *, .swin > *, .get > *"));
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
    var pointer = { x: -1e4, y: -1e4 };

    function readHues() {
      var cs = getComputedStyle(document.documentElement);
      hues = ["--preset-pink", "--preset-cyan", "--preset-green", "--preset-gold", "--accent"]
        .map(function (t) { return cs.getPropertyValue(t).trim(); })
        .filter(Boolean);
      motes.forEach(function (m, i) { m.hue = hues[i % hues.length]; });
    }
    function size() {
      var r = canvas.getBoundingClientRect();
      canvas.width = Math.round(r.width * ddpr);
      canvas.height = Math.round(r.height * ddpr);
      // A pinned canvas needs enough flecks for the whole thing it scrolls
      // over, not just for one screen of it.
      var reach = opts.scrollWith ? opts.scrollWith.getBoundingClientRect().height : r.height;
      seed(r.width, Math.max(r.height, reach));
      centre = r.height / 2;
    }
    // Scatter homes sit on a jittered grid rather than at random points: pure
    // random clumps, and a field that clumps reads as dirt on the screen.
    function seed(w, h) {
      var count = Math.max(800, Math.min(2600, Math.round((w * h) / 1600)));
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
          len: 7 + Math.random() * 12,
          a: Math.random() * Math.PI,
          spin: (Math.random() - 0.5) * 0.004,
          alpha: 0.3 + Math.random() * 0.5,
          // Each fleck keeps its own small offset from the point it is aimed
          // at. The sampler walks a 2px lattice, and a glyph drawn straight
          // onto that lattice reads as print rather than as a swarm.
          turn: Math.random(),
          jx: (Math.random() - 0.5) * 0.062,
          jy: (Math.random() - 0.5) * 0.062,
          hue: hues[i % Math.max(hues.length, 1)]
        });
      }
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
      g.lineWidth = 5;
      // The scatter needs flecks for the whole scrolled height; the glyph needs
      // far fewer or it packs solid. So a fixed quota draws the shape, cycling
      // through the outline's points, and every fleck outside the quota fades
      // to nothing as the shape stands — leaving it at a low alpha instead put
      // a crowd around the glyph, worst on a short outline like the sun.
      var used = aim ? Math.min(motes.length, 460) : 0;
      var count = aim ? aim.length : 1;
      var pace = count / Math.max(used, 1);
      var faint = 0.22;
      for (var i = 0; i < motes.length; i++) {
        var tx, ty;
        var drawn = i < used;
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
          var pt = aim[Math.floor(i * pace) % count];
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
        var weight = drawn ? faint + (1 - faint) * mix
                   : aim ? faint * Math.max(0, 1 - pull * 3.5) : faint;
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
      fill: 0.42, at: 0.73, scrollWith: capsCanvas.parentNode,
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
      dotField(canvas, { fill: 0.5, centreOf: function (c, h) { return { centre: h / 2 }; } })
        .watch(host);
    }
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
