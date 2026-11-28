/* 书库助手内嵌阅读器：epub.js / pdf.js 渲染与 QWebChannel 桥对接。 */
(function () {
  "use strict";

  const STATE = {
    bookId: 0,
    kind: "",
    prefs: {},
    foliate: null,
    lastDetail: null,
    toc: [],
    currentCfi: "",
    currentHref: "",
    currentLabel: "",
    currentPage: 1,
    totalPages: 0,
    pdf: null,
    pdfTotal: 0,
    pdfRatio: 0,
    pdfRendered: new Set(),
    pdfObserver: null,
    pdfHandler: null,
    selection: null,
    searchQuery: "",
    searchHits: [],
    searchIndex: 0,
    lastPalette: null,
  };

  const $ = (id) => document.getElementById(id);

  /* 内置字体清单：与 reader.html <head> 的 @font-face 一一对应，family 名取自字体 name 表。
     foliate 正文 iframe 用 srcdoc 加载，base 是 about:srcdoc，相对 URL 无法解析，
     因此这里用 new URL(..., location.href) 生成绝对 file:// 地址注入 iframe。 */
  const EMBEDDED_FONTS = [
    { family: "LXGW WenKai", file: "LXGWWenKai-Regular.ttf", format: "truetype", weight: "400" },
    { family: "Source Han Serif CN", file: "SourceHanSerifCN-Regular.otf", format: "opentype", weight: "400" },
    { family: "LXGW Heart Serif CHS", file: "LXGWHeartSerifCHS.ttf", format: "truetype", weight: "400" },
    { family: "Noto Sans SC", file: "NotoSansSC-Variable.ttf", format: "truetype", weight: "100 900" },
    { family: "Literata", file: "Literata-Variable.ttf", format: "truetype", weight: "200 900" },
    { family: "Source Serif 4", file: "SourceSerif4-Variable.ttf", format: "truetype", weight: "200 900" },
    { family: "EB Garamond", file: "EBGaramond-Variable.ttf", format: "truetype", weight: "400 800" },
    { family: "Inter", file: "Inter-Variable.ttf", format: "truetype", weight: "100 900" },
  ];

  function fontFaceRules() {
    return EMBEDDED_FONTS.map((f) =>
      '@font-face{font-family:"' + f.family + '";src:url("' +
      new URL("fonts/" + f.file, location.href).href + '") format("' + f.format +
      '");font-weight:' + f.weight + ';font-display:block}'
    ).join("\n");
  }

  let lastTapAt = 0; // 快速连点合并为一次
  let turnLockAt = 0; // 防止同一次按键/点击被重复处理
  let lastSpreadActive = null; // R2：摊开模式上一次的生效状态，变化时才回传 Python

  /* ---------------- 桥 ---------------- */
  function bridge() {
    return window.bridge || null;
  }

  function whenBridgeReady(callback) {
    if (window.bridge) {
      callback();
      return;
    }
    let tries = 0;
    const timer = setInterval(() => {
      tries += 1;
      if (window.bridge) {
        clearInterval(timer);
        callback();
      } else if (tries > 200) {
        clearInterval(timer);
      }
    }, 50);
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (typeof QWebChannel === "undefined" || typeof qt === "undefined") {
      console.warn("QWebChannel 不可用");
      return;
    }
    new QWebChannel(qt.webChannelTransport, (channel) => {
      window.bridge = channel.objects.bridge;
      window.bridge.ready();
    });
  });

  /* ---------------- 工具 ---------------- */
  /** Python 下发的主题色卡；缺字段时回落到纸白。 */
  function palette() {
    return (STATE.prefs && STATE.prefs.palette) || {};
  }

  function themeColors() {
    const p = palette();
    return {
      text: p.ink || "#1f2328",
      muted: p.muted || "#8b9099",
      accent: p.accent || "#3f6fa8",
    };
  }

  function setLoading(visible, text) {
    const node = $("loading");
    if (!node) return;
    if (text) node.textContent = text;
    node.classList.toggle("hidden", !visible);
  }

  function reportError(message) {
    setLoading(false);
    if (bridge()) bridge().reportError(String(message || "未知错误"));
  }

  function logStage(text) {
    const target = bridge();
    if (target && target.log) {
      try {
        target.log(String(text));
      } catch (err) {
        /* 日志失败不影响阅读 */
      }
    }
  }

  /** 给 Promise 加超时，避免解析或排版异常时界面永久停在 65%。 */
  function withTimeout(promise, ms, message) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error(message)), ms);
      Promise.resolve(promise).then(
        (value) => {
          clearTimeout(timer);
          resolve(value);
        },
        (error) => {
          clearTimeout(timer);
          reject(error);
        }
      );
    });
  }

  function showSelectionBar() {
    const bar = $("selectionBar");
    if (!bar) return;
    bar.classList.remove("hidden");
    syncHighlightDot();
    positionSelectionBar();
  }

  /** 让浮条里的「高亮」色点反映当前选中的高亮色（纸面明暗自动适配）。 */
  function syncHighlightDot() {
    const dot = $("hlDot");
    if (!dot) return;
    try {
      dot.style.background = hlColor(activeHighlightName());
    } catch (err) {
      dot.style.background = "var(--hl)";
    }
  }

  /** 把选中浮条定位到选区上方 44px；上方空间不足时落到选区下方。
   *  epub 选区在 iframe 内，需把 iframe 偏移叠加到主文档坐标。 */
  function positionSelectionBar() {
    const bar = $("selectionBar");
    if (!bar) return;
    let rect = null;
    try {
      const doc = STATE.selection && STATE.selection.doc;
      const sel = doc
        ? doc.getSelection
          ? doc.getSelection()
          : null
        : window.getSelection
        ? window.getSelection()
        : null;
      if (sel && sel.rangeCount) {
        const r = sel.getRangeAt(0).getBoundingClientRect();
        const iframe = doc && doc.defaultView ? doc.defaultView.frameElement : null;
        if (iframe) {
          const f = iframe.getBoundingClientRect();
          rect = {
            left: r.left + f.left,
            top: r.top + f.top,
            bottom: r.bottom + f.top,
            width: r.width,
            height: r.height,
          };
        } else {
          rect = { left: r.left, top: r.top, bottom: r.bottom, width: r.width, height: r.height };
        }
      }
    } catch (err) {
      rect = null;
    }
    bar.style.visibility = "hidden";
    const bw = bar.offsetWidth || 220;
    const bh = bar.offsetHeight || 36;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let left = rect ? rect.left + rect.width / 2 - bw / 2 : vw / 2 - bw / 2;
    left = Math.max(8, Math.min(vw - bw - 8, left));
    let top = rect ? rect.top - bh - 44 : 80;
    if (top < 8) top = rect ? rect.bottom + 44 : 80;
    if (top + bh > vh - 8) top = Math.max(8, vh - bh - 8);
    bar.style.left = left + "px";
    bar.style.top = top + "px";
    bar.style.bottom = "auto";
    bar.style.transform = "none";
    bar.style.visibility = "visible";
  }

  function hideSelection() {
    const bar = $("selectionBar");
    if (bar) bar.classList.add("hidden");
    STATE.selection = null;
  }

  /** T16：重排前记下当前位置（epub CFI / pdf 页码），重排后归位（允许 ±1 页）。 */
  let anchorTimer = 0;
  function captureLocationAnchor() {
    if (STATE.kind === "pdf") {
      const page = Number(STATE.currentPage) || 0;
      return page > 0 ? { kind: "pdf", page: page } : null;
    }
    const cfi = STATE.currentCfi ? String(STATE.currentCfi) : "";
    return cfi ? { kind: "epub", cfi: cfi } : null;
  }
  function scheduleRestoreAnchor(anchor) {
    if (!anchor) return;
    clearTimeout(anchorTimer);
    anchorTimer = setTimeout(() => {
      const api = window.readerApi;
      if (!api || typeof api.goTo !== "function") return;
      try {
        if (anchor.kind === "pdf" && anchor.page) api.goTo(anchor.page);
        else if (anchor.kind === "epub" && anchor.cfi) api.goTo(anchor.cfi);
      } catch (err) {
        /* 归位失败不影响阅读 */
      }
    }, 80);
  }

  /** foliate-js 的目录标题可能是字符串或语言映射对象。 */
  function tocLabel(value) {
    if (!value) return "";
    if (typeof value === "string") return value;
    const keys = Object.keys(value);
    if (!keys.length) return "";
    const raw = value[keys[0]];
    return raw == null ? "" : String(raw);
  }

  function flattenToc(items, level, out) {
    (items || []).forEach((item) => {
      const label = tocLabel(item.label || item.title).replace(/\s+/g, " ").trim();
      out.push({ label: label, href: item.href || "", level: level });
      if (item.subitems && item.subitems.length) {
        flattenToc(item.subitems, level + 1, out);
      }
    });
    return out;
  }

  /* ---------------- 主题与排版 ---------------- */
  /** 切主题时用旧纸面颜色盖住 Web 视图淡出，避免 iframe 正文瞬切造成闪烁。 */
  function fadeTheme(previous) {
    const existing = $("themeFade");
    if (existing) existing.remove();
    const paper = $("paper");
    const rect = paper ? paper.getBoundingClientRect() : null;
    const node = document.createElement("div");
    node.id = "themeFade";
    node.style.background = previous.canvas || "#e9e6df";
    if (rect) {
      const sheet = document.createElement("div");
      sheet.className = "theme-fade-sheet";
      sheet.style.left = rect.left + "px";
      sheet.style.top = rect.top + "px";
      sheet.style.width = rect.width + "px";
      sheet.style.height = rect.height + "px";
      sheet.style.background = previous.page || "#fbfaf7";
      node.appendChild(sheet);
    }
    document.body.appendChild(node);
    void node.offsetWidth; // 强制布局一次，保证透明度过渡真正播放
    node.classList.add("fading");
    setTimeout(() => {
      if (node.parentNode) node.remove();
    }, 240);
  }

  /** 唯一主题入口：先把 palette 写进 CSS 变量，再刷新正文样式。 */
  function applyPalette() {
    const p = palette();
    const previous = STATE.lastPalette;
    const root = document.documentElement.style;
    root.setProperty("--canvas", p.canvas || "#e9e6df");
    root.setProperty("--page-bg", p.page || "#fbfaf7");
    root.setProperty("--page-text", p.ink || "#1f2328");
    root.setProperty("--muted", p.muted || "#8b9099");
    root.setProperty("--chrome", p.chrome || "#f3f1ec");
    root.setProperty("--border", p.border || "#ddd8cd");
    root.setProperty("--accent", p.accent || "#3f6fa8");
    const dark = p.key === "dark" || p.key === "night";
    document.documentElement.setAttribute(
      "data-paper",
      dark ? "night" : (p.key || "light")
    );
    STATE.lastPalette = {
      canvas: p.canvas || "#e9e6df",
      page: p.page || "#fbfaf7",
    };
    if (previous && (previous.page !== STATE.lastPalette.page || previous.canvas !== STATE.lastPalette.canvas)) {
      fadeTheme(previous);
    }
    if (STATE.foliate && STATE.foliate.renderer && STATE.foliate.renderer.setBackground) {
      try {
        STATE.foliate.renderer.setBackground(p.page || "#fbfaf7");
      } catch (err) {
        /* 渲染器尚未就绪时忽略 */
      }
    }
  }

  /** 背景纹理：外层纸面与 PDF 页共用同一套 class。 */
  function applyTexture() {
    const texture = String((STATE.prefs && STATE.prefs.texture) || "none");
    document.body.classList.toggle("texture-paper", texture === "paper");
    document.body.classList.toggle("texture-noise", texture === "noise");
  }

  function applyPrefs() {
    applyPalette();
    applyTexture();
    applyFixedPageWidth();
    if (STATE.foliate) {
      layoutFoliate();
      applyFoliateStyles();
      applyTurnStyle();
    }
  }

  /** 把「页宽固定」开关同步到 DOM class（CSS 决定纸面是否钉宽）。 */
  function applyFixedPageWidth() {
    const prefs = STATE.prefs || {};
    const fixed =
      prefs.fixed_page_width !== false &&
      String(prefs.fixed_page_width) !== "false" &&
      prefs.fixed_page_width !== 0;
    if (document.body) document.body.classList.toggle("fixed-page-width", !!fixed);
  }

  /** 五档翻页动效：instant/push 用内置分页，slide/curl 交给渲染器，flip 用 View Transitions。 */
  function applyTurnStyle() {
    const style = String((STATE.prefs && STATE.prefs.turn_style) || "push");
    document.body.classList.toggle("no-turn-anim", style === "instant");
    const renderer = STATE.foliate && STATE.foliate.renderer;
    if (!renderer) return;
    try {
      if (style === "slide" || style === "curl") {
        renderer.setAttribute("turn-style", style);
      } else {
        renderer.removeAttribute("turn-style");
      }
    } catch (err) {
      console.warn("设置翻页动效失败", err);
    }
  }

  /** 纹理贴图：极低透明度的同色细线，深浅主题都不会脏。 */
  function textureImage(color, texture) {
    if (texture === "paper") {
      return (
        "repeating-linear-gradient(0deg, color-mix(in srgb, " + color +
        " 4%, transparent) 0 1px, transparent 1px 3px), " +
        "repeating-linear-gradient(90deg, color-mix(in srgb, " + color +
        " 2.5%, transparent) 0 1px, transparent 1px 4px)"
      );
    }
    if (texture === "noise") {
      return (
        "radial-gradient(color-mix(in srgb, " + color +
        " 6%, transparent) 0.5px, transparent 0.7px)"
      );
    }
    return "none";
  }

  /* ---- 高亮荧光笔 4 色：存语义名，按当前纸面解析 hex（T13）---- */
  const HL_PALETTES = {
    light: { blue: "#CFE3F3", amber: "#F5D9A8", green: "#D8E8C2", pink: "#ECCFD8" },
    dark: { blue: "#2C4257", amber: "#4A3B22", green: "#31412A", pink: "#45303A" },
  };
  const HL_DEFAULT = "blue";
  function hlName(v) {
    const s = String(v == null ? "" : v).trim().toLowerCase();
    return HL_PALETTES.light[s] ? s : HL_DEFAULT;
  }
  function isDarkPaper() {
    const p = (STATE.prefs && STATE.prefs.palette) || {};
    const k = p.key || (STATE.prefs && STATE.prefs.theme) || "";
    return k === "dark" || k === "night";
  }
  function hlColor(name) {
    return HL_PALETTES[isDarkPaper() ? "dark" : "light"][hlName(name)];
  }
  function activeHighlightName() {
    return hlName(STATE.prefs && STATE.prefs.highlight_color);
  }

  /** 注入正文样式：字体、字号、行距、主题色，与 Readest 的排版面板一致。 */
  function foliateStyles() {
    const prefs = STATE.prefs || {};
    const p = palette();
    const colors = themeColors();
    const bg = p.page || "#fbfaf7";
    const isDark = (p.key || prefs.theme) === "dark" || p.key === "night";
    // 中英混排：西文走拉丁字体、中文回落 CJK，故拉丁字体在前。
    // 兼容旧键 font_family（单字体）；新键 reader_font_cjk / reader_font_latin。
    const legacy = String(prefs.font_family || "").replace(/"/g, "").trim();
    const cjk = String(prefs.reader_font_cjk || "").replace(/"/g, "").trim()
      || legacy || "LXGW WenKai";
    const latin = String(prefs.reader_font_latin || "").replace(/"/g, "").trim()
      || "Literata";
    const family =
      '"' + latin + '", "' + cjk + '", ' +
      '"Noto Serif CJK SC", "Source Han Serif SC", "Microsoft YaHei", SimSun, serif';
    const size = num(prefs.font_size, 19);
    const lineHeight = num(prefs.line_height, 1.9);
    const weight = num(prefs.font_weight, 400);
    const para = num(prefs.para_spacing, 0.75);
    const indent = prefs.indent !== false;
    const justify = prefs.justify !== false;
    const hyphens = prefs.hyphens === true;
    const texture = String(prefs.texture || "none");
    const background =
      "background-color: " + bg + "; background-image: " +
      textureImage(colors.text, texture) + ";";
    const textureSize = texture === "noise" ? "background-size: 3px 3px;" : "";
    return fontFaceRules() + "\n" + [
      '@namespace epub "http://www.idpf.org/2007/ops";',
      "html { color-scheme: " + (isDark ? "dark" : "light") + ";",
      "  background: " + bg + "; --theme-bg-color: " + bg + "; --override-color: true; }",
      "body { " + background + " " + textureSize + " color: " + colors.text + ";",
      "  font-family: " + family + "; font-size: " + size + "px; font-weight: " + weight + ";",
      "  line-height: " + lineHeight + "; margin: 0; }",
      "p, li, blockquote, dd { line-height: " + lineHeight + "; text-align: " +
        (justify ? "justify" : "start") + ";",
      "  -webkit-hyphens: " + (hyphens ? "auto" : "manual") + "; hyphens: " +
        (hyphens ? "auto" : "manual") + "; }",
      "p { text-indent: " + (indent ? "2em" : "0") + "; margin: 0 0 " + para + "em; }",
      "h1, h2, h3, h4, h5, h6 { line-height: 1.35; text-indent: 0; }",
      "a:link { color: " + colors.accent + "; }",
      // 出版方 CSS 常写 img{height:100%}，必须 !important 才能保证等比缩放。
      "img, svg { max-width: 100% !important; height: auto !important; object-fit: contain; }",
      "figure, .cover, .calibre1 { max-height: none !important; }",
      "img.fullpage { display: block; margin: 0 auto; max-height: 100%; width: auto; max-width: 100%; }",
      "pre { white-space: pre-wrap !important; }",
      "::selection { background: color-mix(in srgb, " + colors.accent + " 32%, transparent); }",
    ].join("\n");
  }

  function applyFoliateStyles() {
    if (!STATE.foliate || !STATE.foliate.renderer) return;
    try {
      STATE.foliate.renderer.setStyles(foliateStyles());
    } catch (err) {
      console.warn("应用排版失败", err);
    }
  }

  function num(value, fallback) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  /** 画布内尺寸（剔除 padding），作为页框计算的视口输入（T16）。 */
  function viewportSize() {
    const canvas = $("canvas");
    if (!canvas) return { width: 0, height: 0 };
    const style = getComputedStyle(canvas);
    return {
      width: canvasInnerWidth(),
      height: Math.max(
        0,
        canvas.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom)
      ),
    };
  }

  function canvasInnerWidth() {
    const canvas = $("canvas");
    if (!canvas) return 0;
    const style = getComputedStyle(canvas);
    return Math.max(
      0,
      canvas.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight)
    );
  }

  /** 摊开与单页宽度：纯逻辑委托 BSPageFrame（T16 固定页框，单测覆盖）。 */
  function computeSpread() {
    if (typeof BSPageFrame === "undefined" || !BSPageFrame.computeFrame) {
      return { spread: false, pageWidth: 560 };
    }
    const frame = BSPageFrame.computeFrame(viewportSize(), STATE.prefs || {}, STATE.kind);
    return { spread: frame.spread, pageWidth: frame.pageWidth };
  }

  /** 把摊开状态写到 DOM（dataset / --page-max），变化时回传 Python。 */
  function applySpreadMode(spread, pageWidth) {
    const paper = document.getElementById("paper");
    if (paper) paper.dataset.pageMode = spread ? "spread" : "single";
    document.documentElement.style.setProperty("--page-max", pageWidth + "px");
    if (lastSpreadActive !== spread) {
      lastSpreadActive = spread;
      const b = bridge();
      if (b && b.reportSpread && STATE.bookId) b.reportSpread(STATE.bookId, spread);
    }
  }

  /** 纸面页框尺寸：高度 = 视口高（固定页框），宽度走 BSPageFrame（T16）。 */
  function paperMetrics() {
    if (typeof BSPageFrame === "undefined" || !BSPageFrame.computeFrame) {
      return { width: 560, height: 640 };
    }
    const frame = BSPageFrame.computeFrame(viewportSize(), STATE.prefs || {}, STATE.kind);
    return { width: frame.width, height: frame.height };
  }

  function layoutFoliate() {
    const renderer = STATE.foliate && STATE.foliate.renderer;
    if (!renderer) return;
    const prefs = STATE.prefs || {};
    const legacy = num(prefs.margin_px, 64);
    const top = Math.max(0, num(prefs.margin_top, legacy));
    const bottom = Math.max(0, num(prefs.margin_bottom, legacy));
    const left = Math.max(0, num(prefs.margin_left, legacy));
    const right = Math.max(0, num(prefs.margin_right, legacy));
    const layout = computeSpread();
    const metrics = paperMetrics();
    applySpreadMode(layout.spread, layout.pageWidth);
    renderer.setAttribute("flow", "paginated");
    renderer.setAttribute("gap", layout.spread ? "6%" : "8%");
    renderer.setAttribute("margin-top", top + "px");
    renderer.setAttribute("margin-bottom", bottom + "px");
    renderer.setAttribute("margin-left", left + "px");
    renderer.setAttribute("margin-right", right + "px");
    renderer.setAttribute("max-column-count", layout.spread ? "2" : "1");
    renderer.setAttribute("max-inline-size", metrics.width + "px");
    renderer.setAttribute("max-block-size", metrics.height + "px");
    applyFoliateStyles();
  }

  let fitTimer = 0;

  function fitPaper() {
    const metrics = paperMetrics();
    const layout = computeSpread();
    applySpreadMode(layout.spread, layout.pageWidth);
    document.documentElement.style.setProperty("--page-max", metrics.width + "px");
    if (STATE.foliate && STATE.foliate.renderer) {
      STATE.foliate.renderer.setAttribute("max-inline-size", metrics.width + "px");
      STATE.foliate.renderer.setAttribute("max-block-size", metrics.height + "px");
      STATE.foliate.renderer.setAttribute(
        "max-column-count",
        layout.spread ? "2" : "1"
      );
    }
    if (STATE.pdf) relayoutPdf();
  }

  function scheduleFitPaper() {
    clearTimeout(fitTimer);
    fitTimer = setTimeout(fitPaper, 150);
  }

  /* ---------------- 翻页与点击区 ---------------- */
  function turnStyle() {
    return String((STATE.prefs && STATE.prefs.turn_style) || "push");
  }

  function scrollPdfBy(direction) {
    const canvas = $("canvas");
    if (!canvas) return;
    canvas.scrollBy({
      top: canvas.clientHeight * 0.92 * direction,
      behavior: "smooth",
    });
  }

  /** 所有翻页入口（点击区、两侧箭头、键盘、底栏按钮）统一走这里。 */
  function turn(direction) {
    const dir = direction >= 0 ? 1 : -1;
    const now = Date.now();
    if (now - turnLockAt < 80) return;
    turnLockAt = now;
    if (STATE.kind === "pdf") {
      scrollPdfBy(dir);
      return;
    }
    if (!STATE.foliate) return;
    const action = dir > 0 ? "next" : "prev";
    if (turnStyle() === "flip" && typeof document.startViewTransition === "function") {
      const root = document.documentElement;
      root.style.setProperty("--flip-angle", dir > 0 ? "-102deg" : "102deg");
      root.style.setProperty("--flip-origin", dir > 0 ? "left center" : "right center");
      try {
        document.startViewTransition(() => STATE.foliate[action]());
        return;
      } catch (err) {
        console.warn("整页翻过渡失败，退回内置翻页", err);
      }
    }
    const task = STATE.foliate[action]();
    if (task && task.catch) task.catch(() => {});
  }

  /** 上/下一章：EPUB 走目录 href，PDF 走 outline 页码。 */
  function rotateChapter(direction) {
    const dir = direction >= 0 ? 1 : -1;
    if (!STATE.toc.length) {
      turn(dir);
      return;
    }
    if (STATE.kind === "pdf") {
      const pages = STATE.toc
        .map((item) => Number(item.href) || 0)
        .filter((page) => page > 0)
        .sort((a, b) => a - b);
      const target =
        dir > 0
          ? pages.find((page) => page > STATE.currentPage)
          : pages
              .slice()
              .reverse()
              .find((page) => page < STATE.currentPage);
      if (target) api.goTo({ page: target });
      return;
    }
    let index = -1;
    STATE.toc.forEach((item, position) => {
      if (item.href && item.href === STATE.currentHref) index = position;
    });
    if (index < 0) {
      turn(dir);
      return;
    }
    const target = STATE.toc[Math.min(STATE.toc.length - 1, Math.max(0, index + dir))];
    if (target && target.href) api.goTo(target.href);
  }

  /** 点击区：左 25% 上一页、右 25% 下一页、中间 50% 收放工具条。 */
  function handleTap(event, doc, rect) {
    if (STATE.prefs && STATE.prefs.click_turn === false) return;
    const target = event.target;
    if (target && target.closest) {
      const blocked = target.closest(
        "a, img, svg, input, textarea, select, button, video, audio, [contenteditable='true']"
      );
      if (blocked) return;
    }
    const selection = doc && doc.getSelection ? doc.getSelection() : null;
    if (selection && selection.rangeCount && String(selection.toString()).trim()) return;
    const now = Date.now();
    if (now - lastTapAt < 200) return;
    lastTapAt = now;
    const ratio = rect.width ? (event.clientX - rect.left) / rect.width : 0.5;
    if (ratio < 0.25) {
      turn(-1);
    } else if (ratio > 0.75) {
      turn(1);
    } else if (bridge()) {
      bridge().toggleChrome();
    }
  }

  function bindSideNav() {
    const binds = [
      ["prevChapterBtn", () => rotateChapter(-1)],
      ["prevPageBtn", () => turn(-1)],
      ["nextPageBtn", () => turn(1)],
      ["nextChapterBtn", () => rotateChapter(1)],
    ];
    binds.forEach(([id, handler]) => {
      const node = $(id);
      if (node) node.addEventListener("click", handler);
    });
  }

  /* ---------------- 打开 ---------------- */
  function reset() {
    hideSelection();
    STATE.lastPalette = null;
    const fade = $("themeFade");
    if (fade) fade.remove();
    if (STATE.foliate) {
      try {
        STATE.foliate.close();
      } catch (err) {
        /* 忽略销毁异常 */
      }
      try {
        STATE.foliate.remove();
      } catch (err) {
        /* 忽略 */
      }
      STATE.foliate = null;
    }
    STATE.lastDetail = null;
    document.body.classList.remove("epub-mode");
    if (STATE.pdfObserver) {
      STATE.pdfObserver.disconnect();
      STATE.pdfObserver = null;
    }
    if (STATE.pdfHandler) {
      const canvas = $("canvas");
      if (canvas) canvas.removeEventListener("scroll", STATE.pdfHandler);
      STATE.pdfHandler = null;
    }
    if (STATE.pdfClickHandler) {
      const canvas = $("canvas");
      if (canvas) canvas.removeEventListener("click", STATE.pdfClickHandler);
      STATE.pdfClickHandler = null;
    }
    if (STATE.pdf && STATE.pdf.destroy) {
      try {
        STATE.pdf.destroy();
      } catch (err) {
        /* 忽略 */
      }
    }
    STATE.pdf = null;
    STATE.pdfRatio = 0;
    STATE.pdfRendered = new Set();
    STATE.toc = [];
    STATE.currentCfi = "";
    STATE.currentHref = "";
    STATE.currentLabel = "";
    STATE.currentPage = 1;
    STATE.totalPages = 0;
    STATE.searchHits = [];
    STATE.searchQuery = "";
    STATE.selection = null;
    document.body.classList.remove("pdf-mode");
    const viewer = $("viewer");
    if (viewer) viewer.innerHTML = "";
    const canvas = $("canvas");
    if (canvas) canvas.scrollTop = 0;
  }

  function open(payload) {
    try {
      reset();
      STATE.bookId = payload.bookId || 0;
      STATE.kind = payload.kind || "";
      STATE.prefs = payload.prefs || {};
      applyPrefs();
      setLoading(true, "正在加载…");
      if (STATE.kind === "pdf") {
        openPdf(payload).catch((err) => reportError(err && err.message ? err.message : err));
      } else {
        openEpub(payload).catch((err) => reportError(err && err.message ? err.message : err));
      }
    } catch (err) {
      reportError(err && err.message ? err.message : err);
    }
  }

  /* ---------------- EPUB（foliate-js / Readest 内核） ---------------- */
  function bindFoliateDoc(doc, index) {
    if (!doc || doc.__bookshelfBound) return;
    doc.__bookshelfBound = true;
    doc.addEventListener("keyup", handleKey);
    doc.addEventListener("click", (event) => {
      const root = doc.documentElement;
      handleTap(event, doc, root.getBoundingClientRect());
    });
    doc.addEventListener("mouseup", () => {
      if (STATE.kind !== "epub" || !STATE.foliate) return;
      const selection = doc.getSelection ? doc.getSelection() : null;
      const text = selection ? String(selection.toString() || "").trim() : "";
      if (!text || !selection.rangeCount) {
        hideSelection();
        return;
      }
      let cfiRange = "";
      try {
        cfiRange = STATE.foliate.getCFI(index, selection.getRangeAt(0));
      } catch (err) {
        cfiRange = "";
      }
      STATE.selection = { text: text, cfiRange: cfiRange, doc: doc };
      showSelectionBar();
    });
  }

  function reportFoliateProgress(detail) {
    if (!detail) return;
    STATE.lastDetail = detail;
    STATE.currentCfi = detail.cfi || "";
    const percent = Math.min(1, Math.max(0, Number(detail.fraction) || 0));
    const tocItem = detail.tocItem || null;
    const label = tocLabel(tocItem && tocItem.label) || "";
    STATE.currentLabel = label;
    STATE.currentHref = (tocItem && tocItem.href) || "";
    const location = detail.location || {};
    const total = Math.max(0, Number(location.total) || 0);
    const page = Math.max(1, (Number(location.current) || 0) + 1);
    STATE.currentPage = page;
    STATE.totalPages = total;
    const seconds = Math.max(0, Number(detail.time && detail.time.section) || 0);
    const remaining = Math.round(seconds * 300);
    const locator = {
      type: "epub",
      cfi: STATE.currentCfi,
      href: STATE.currentHref,
      label: label,
      page: page,
      total: total,
    };
    if (!bridge()) return;
    bridge().location(
      STATE.bookId,
      JSON.stringify({
        label: label,
        href: STATE.currentHref,
        page: page,
        total: total,
        percent: percent,
        // 当前章节剩余阅读秒数，底栏据此估算“本章剩余 N 分钟 / M 页”。
        sectionSeconds: seconds,
        remainingChars: remaining,
      })
    );
    bridge().saveProgress(STATE.bookId, JSON.stringify(locator), percent);
  }

  async function openEpub(payload) {
    if (typeof Foliate === "undefined") {
      throw new Error("阅读内核未加载，请重新安装或检查 foliate-js 资源");
    }
    document.body.classList.add("epub-mode");
    const host = document.createElement("foliate-view");
    host.id = "foliateView";
    $("paper").appendChild(host);
    STATE.foliate = host;

    host.addEventListener("load", (event) => {
      const detail = event.detail || {};
      bindFoliateDoc(detail.doc, detail.index);
    });
    host.addEventListener("relocate", (event) => {
      reportFoliateProgress(event.detail);
    });
    host.addEventListener("draw-annotation", (event) => {
      const detail = event.detail || {};
      if (!detail.draw) return;
      const value = String((detail.annotation && detail.annotation.value) || "");
      if (value.indexOf("foliate-search:") === 0) {
        detail.draw(Foliate.Overlayer.outline);
      } else {
        detail.draw(Foliate.Overlayer.highlight, {
          color: hlColor(
            (detail.annotation && detail.annotation.color) || activeHighlightName()
          ),
        });
      }
    });

    logStage("开始解析 EPUB");
    await withTimeout(
      host.open(payload.url),
      25000,
      "解析 EPUB 超时，文件可能损坏或过大"
    );
    logStage("EPUB 解析完成");
    layoutFoliate();
    applyTurnStyle();

    STATE.toc = flattenToc((host.book && host.book.toc) || [], 0, []);
    if (bridge()) bridge().toc(STATE.bookId, JSON.stringify(STATE.toc));

    for (const mark of payload.highlights || []) {
      if (!mark || !mark.cfiRange) continue;
      try {
        await host.addAnnotation({ value: mark.cfiRange, color: hlName(mark.color) });
      } catch (err) {
        console.warn("恢复高亮失败", err);
      }
    }

    const target = payload.locator && payload.locator.cfi ? payload.locator.cfi : null;
    logStage(target ? "载入上次阅读位置" : "载入正文首页");
    let restored = false;
    if (target) {
      try {
        await withTimeout(host.goTo(target), 15000, "载入上次阅读位置超时");
        restored = true;
      } catch (err) {
        console.warn("按上次位置打开失败，改为从首页打开", err);
        logStage("上次阅读位置载入失败，改为从首页打开");
      }
    }
    if (!restored) {
      await withTimeout(host.init({}), 20000, "载入正文超时，章节可能过大");
    }

    logStage("章节已显示");
    if (bridge()) bridge().rendered(STATE.bookId);
    setLoading(false);
  }

  /* ---------------- PDF ---------------- */
  async function openPdf(payload) {
    if (typeof pdfjsLib === "undefined") {
      throw new Error("pdf.js 未加载");
    }
    pdfjsLib.GlobalWorkerOptions.workerSrc = "vendor/pdf.worker.min.js";
    logStage("开始解析 PDF");
    const doc = await withTimeout(
      pdfjsLib.getDocument({ url: payload.url }).promise,
      40000,
      "PDF 载入超时，文件可能过大或已损坏"
    );
    STATE.pdf = doc;
    STATE.pdfTotal = doc.numPages;
    document.body.classList.add("pdf-mode");

    const viewer = $("viewer");
    viewer.innerHTML = "";
    const pages = document.createElement("div");
    pages.id = "pdfPages";
    viewer.appendChild(pages);

    const first = await doc.getPage(1);
    const firstViewport = first.getViewport({ scale: 1 });
    const ratio = firstViewport.height / firstViewport.width;
    STATE.pdfRatio = ratio;
    const width = Math.max(320, paperMetrics().width - 8);

    for (let index = 1; index <= doc.numPages; index += 1) {
      const page = document.createElement("div");
      page.className = "pdf-page";
      page.dataset.page = String(index);
      page.style.width = width + "px";
      page.style.height = Math.round(width * ratio) + "px";
      pages.appendChild(page);
    }

    if (payload.toc && payload.toc.items) {
      STATE.toc = payload.toc.items.map((item) => ({
        label: item.label,
        href: String(item.page || 1),
        level: item.level || 0,
      }));
      if (bridge()) bridge().toc(STATE.bookId, JSON.stringify(STATE.toc));
    }

    const canvas = $("canvas");
    if (window.IntersectionObserver) {
      STATE.pdfObserver = new IntersectionObserver(
        (entries) => {
          entries.forEach((entry) => {
            if (entry.isIntersecting) {
              renderPdfPage(Number(entry.target.dataset.page));
            }
          });
        },
        { root: canvas, rootMargin: "900px 0px" }
      );
      pages.querySelectorAll(".pdf-page").forEach((node) => STATE.pdfObserver.observe(node));
    } else {
      for (let index = 1; index <= doc.numPages; index += 1) renderPdfPage(index);
    }

    STATE.pdfHandler = () => onPdfScroll();
    canvas.addEventListener("scroll", STATE.pdfHandler, { passive: true });
    STATE.pdfClickHandler = (event) => {
      handleTap(event, document, canvas.getBoundingClientRect());
    };
    canvas.addEventListener("click", STATE.pdfClickHandler);

    document.addEventListener("mouseup", onPdfSelection);

    const locator = payload.locator || null;
    const initialPage = locator && locator.page ? Number(locator.page) : 1;
    await renderPdfPage(initialPage);
    if (!STATE.pdfRendered.has(initialPage)) {
      throw new Error("PDF 第 " + initialPage + " 页渲染失败");
    }
    if (locator && locator.page) scrollToPage(initialPage, false);
    reportPdfProgress(initialPage);
    if (bridge()) bridge().rendered(STATE.bookId);
    setLoading(false);
  }

  async function renderPdfPage(number) {
    if (!STATE.pdf || STATE.pdfRendered.has(number)) return;
    const container = document.querySelector('.pdf-page[data-page="' + number + '"]');
    if (!container) return;
    STATE.pdfRendered.add(number);
    try {
      const page = await STATE.pdf.getPage(number);
      const base = page.getViewport({ scale: 1 });
      const scale = container.clientWidth / base.width;
      const viewport = page.getViewport({ scale: scale });
      container.style.height = Math.round(viewport.height) + "px";

      const ratio = window.devicePixelRatio || 1;
      const canvas = document.createElement("canvas");
      canvas.width = Math.floor(viewport.width * ratio);
      canvas.height = Math.floor(viewport.height * ratio);
      canvas.style.width = viewport.width + "px";
      canvas.style.height = viewport.height + "px";
      container.appendChild(canvas);
      const context = canvas.getContext("2d");
      context.scale(ratio, ratio);
      await page.render({ canvasContext: context, viewport: viewport }).promise;

      try {
        const textContent = await page.getTextContent();
        const layer = document.createElement("div");
        layer.className = "textLayer";
        container.appendChild(layer);
        pdfjsLib.renderTextLayer({
          textContent: textContent,
          container: layer,
          viewport: viewport,
          textDivs: [],
        });
      } catch (err) {
        /* 文本层失败不影响翻页 */
      }
    } catch (err) {
      STATE.pdfRendered.delete(number);
      console.warn("渲染第 " + number + " 页失败", err);
    }
  }

  /** 窗口尺寸变化后重排 PDF 页宽；只重渲染视口附近的页，避免整本重绘。 */
  function relayoutPdf() {
    if (!STATE.pdf || !STATE.pdfRatio) return;
    const width = Math.max(320, paperMetrics().width - 8);
    document.querySelectorAll(".pdf-page").forEach((container) => {
      const number = Number(container.dataset.page);
      container.style.width = width + "px";
      container.style.height = Math.round(width * STATE.pdfRatio) + "px";
      container.querySelectorAll("canvas, .textLayer").forEach((node) => node.remove());
      STATE.pdfRendered.delete(number);
    });
    document.querySelectorAll(".pdf-page").forEach((container) => {
      const rect = container.getBoundingClientRect();
      if (rect.bottom > -600 && rect.top < window.innerHeight + 600) {
        renderPdfPage(Number(container.dataset.page));
      }
    });
  }

  function onPdfScroll() {
    clearTimeout(STATE.scrollTimer);
    STATE.scrollTimer = setTimeout(() => {
      const canvas = $("canvas");
      if (!canvas) return;
      const middle = canvas.scrollTop + canvas.clientHeight / 2;
      let page = 1;
      document.querySelectorAll(".pdf-page").forEach((node) => {
        if (node.offsetTop <= middle) page = Number(node.dataset.page);
      });
      if (page !== STATE.currentPage) reportPdfProgress(page);
    }, 150);
  }

  function scrollToPage(page, smooth) {
    const node = document.querySelector('.pdf-page[data-page="' + page + '"]');
    const canvas = $("canvas");
    if (!node || !canvas) return;
    canvas.scrollTo({ top: Math.max(0, node.offsetTop - 14), behavior: smooth ? "smooth" : "auto" });
  }

  function pdfLabel(page) {
    let label = "";
    STATE.toc.forEach((item) => {
      const itemPage = Number(item.href) || 0;
      if (itemPage && itemPage <= page) label = item.label;
    });
    return label;
  }

  function reportPdfProgress(page) {
    STATE.currentPage = page;
    const total = STATE.pdfTotal || 1;
    const percent = total > 1 ? Math.min(1, Math.max(0, (page - 1) / (total - 1))) : 1;
    const label = pdfLabel(page);
    STATE.currentLabel = label;
    if (!bridge()) return;
    bridge().location(
      STATE.bookId,
      JSON.stringify({
        label: label,
        href: "",
        page: page,
        total: total,
        percent: percent,
        sectionSeconds: 0,
        remainingChars: 0,
      })
    );
    bridge().saveProgress(
      STATE.bookId,
      JSON.stringify({ type: "pdf", page: page, percent: percent, label: label }),
      percent
    );
  }

  function onPdfSelection(event) {
    if (STATE.kind !== "pdf") return;
    if (event && event.target && event.target.closest && event.target.closest("#selectionBar")) return;
    const selection = window.getSelection();
    const text = selection ? selection.toString().trim() : "";
    if (!text) {
      hideSelection();
      return;
    }
    STATE.selection = { text: text };
    showSelectionBar();
  }

  /* ---------------- 选中工具条 ---------------- */
  function highlightSelection(color, note) {
    const selection = STATE.selection;
    if (!selection || !selection.text) return;
    let locator = null;
    if (STATE.kind === "epub") {
      locator = {
        type: "epub",
        cfi: STATE.currentCfi,
        cfiRange: selection.cfiRange || "",
        text: selection.text,
      };
      if (selection.cfiRange && STATE.foliate) {
        try {
          STATE.foliate.addAnnotation({ value: selection.cfiRange, color: color });
        } catch (err) {
          console.warn("绘制高亮失败", err);
        }
      }
    } else {
      locator = { type: "pdf", page: STATE.currentPage, text: selection.text };
    }
    if (bridge()) {
      bridge().addHighlight(
        STATE.bookId,
        JSON.stringify(locator),
        color,
        selection.text,
        note || ""
      );
    }
    hideSelection();
  }

  function bindSelectionBar() {
    const bar = $("selectionBar");
    if (!bar) return;
    const hlBtn = $("hlBtn");
    if (hlBtn) {
      hlBtn.addEventListener("click", () => {
        highlightSelection(activeHighlightName(), "");
        hideSelection();
      });
    }
    const noteBtn = $("noteBtn");
    if (noteBtn) {
      noteBtn.addEventListener("click", () => {
        const text = STATE.selection && STATE.selection.text ? STATE.selection.text : "";
        const note = bridge() ? bridge().askNote(text) : "";
        if (note) highlightSelection(activeHighlightName(), note);
        hideSelection();
      });
    }
    const copyBtn = $("copyBtn");
    if (copyBtn) {
      copyBtn.addEventListener("click", () => {
        const text = STATE.selection && STATE.selection.text ? STATE.selection.text : "";
        if (text && bridge()) bridge().copyText(text);
        hideSelection();
      });
    }
    const readBtn = $("readBtn");
    if (readBtn) {
      readBtn.addEventListener("click", () => {
        startReadAloud();
        hideSelection();
      });
    }
  }

  /** 朗读选中文字：优先 foliate 内建 TTS，回落 Web Speech API。 */
  function startReadAloud() {
    const text = STATE.selection && STATE.selection.text ? STATE.selection.text : "";
    if (!text) return;
    const foliate = STATE.foliate;
    if (foliate && typeof foliate.startReadAloud === "function") {
      try {
        foliate.startReadAloud();
        return;
      } catch (err) {
        /* fall through to Web Speech */
      }
    }
    if ("speechSynthesis" in window && "SpeechSynthesisUtterance" in window) {
      try {
        window.speechSynthesis.cancel();
        window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
      } catch (err) {
        /* no-op */
      }
    }
  }

  /* ---------------- 键盘 ---------------- */
  /** 正文区只保留 Escape（收起选中工具条），其余快捷键统一由 Qt 侧注册，避免双触发。 */
  function handleKey(event) {
    if (event.key !== "Escape") return;
    hideSelection();
    if (window.getSelection) {
      const selection = window.getSelection();
      if (selection) selection.removeAllRanges();
    }
  }

  /* ---------------- 对外 API ---------------- */
  const api = {
    open: open,

    setPrefs(prefs) {
      const anchor = captureLocationAnchor();
      STATE.prefs = Object.assign({}, STATE.prefs, prefs || {});
      applyPrefs();
      scheduleRestoreAnchor(anchor);
    },

    goTo(target) {
      if (STATE.kind === "pdf") {
        const page = typeof target === "number" ? target : Number(target && target.page);
        if (page > 0) {
          renderPdfPage(page);
          scrollToPage(page, false);
          reportPdfProgress(page);
        }
        return;
      }
      if (!STATE.foliate) return;
      const value = typeof target === "string" ? target : (target && (target.cfi || target.href));
      if (value) STATE.foliate.goTo(value).catch(() => {});
    },

    next() {
      turn(1);
    },

    goToPercent(percent) {
      const value = Math.min(1, Math.max(0, Number(percent) || 0));
      if (STATE.kind === "pdf") {
        const page = Math.max(1, Math.min(STATE.pdfTotal || 1, Math.round(value * (STATE.pdfTotal || 1))));
        renderPdfPage(page);
        scrollToPage(page, false);
        reportPdfProgress(page);
        return;
      }
      if (STATE.foliate) STATE.foliate.goToFraction(value).catch(() => {});
    },

    prev() {
      turn(-1);
    },

    turnChapter(direction) {
      rotateChapter(Number(direction) || 1);
    },

    addBookmark() {
      if (!bridge()) return;
      if (STATE.kind === "pdf") {
        const locator = {
          type: "pdf",
          page: STATE.currentPage,
          percent: STATE.pdfTotal ? STATE.currentPage / STATE.pdfTotal : 0,
          label: STATE.currentLabel,
        };
        bridge().addBookmark(
          STATE.bookId,
          JSON.stringify(locator),
          STATE.currentLabel,
          "第 " + STATE.currentPage + " 页"
        );
        return;
      }
      if (!STATE.currentCfi) return;
      const locator = {
        type: "epub",
        cfi: STATE.currentCfi,
        href: STATE.currentHref,
        label: STATE.currentLabel,
        page: STATE.currentPage,
        total: STATE.totalPages,
      };
      bridge().addBookmark(
        STATE.bookId,
        JSON.stringify(locator),
        STATE.currentLabel,
        STATE.selection ? STATE.selection.text : ""
      );
    },

    async search(keyword) {
      const query = String(keyword || "").trim();
      if (!query) return;
      STATE.searchQuery = query;
      STATE.searchIndex = 0;
      if (STATE.kind === "pdf") {
        STATE.searchHits = [];
        for (let index = 1; index <= STATE.pdfTotal; index += 1) {
          try {
            const page = await STATE.pdf.getPage(index);
            const content = await page.getTextContent();
            const text = content.items.map((item) => item.str).join("");
            if (text.indexOf(query) >= 0) STATE.searchHits.push(index);
          } catch (err) {
            /* 单页失败继续 */
          }
        }
        if (STATE.searchHits.length) {
          renderPdfPage(STATE.searchHits[0]);
          scrollToPage(STATE.searchHits[0], false);
        }
        if (bridge()) bridge().searchResult(STATE.searchHits.length, STATE.searchHits.length ? 1 : 0);
        return;
      }
      if (!STATE.foliate) {
        if (bridge()) bridge().searchResult(0, 0);
        return;
      }
      STATE.searchHits = [];
      try {
        for await (const result of STATE.foliate.search({ query: query })) {
          if (result === "done") break;
          const items = result && result.subitems
            ? result.subitems
            : result && result.cfi
              ? [result]
              : [];
          items.forEach((item) => {
            if (item && item.cfi) STATE.searchHits.push(item.cfi);
          });
          if (STATE.searchHits.length >= 1500) break;
        }
      } catch (err) {
        console.warn("全文搜索失败", err);
      }
      STATE.searchHits = Array.from(new Set(STATE.searchHits));
      if (STATE.searchHits.length) {
        try {
          await STATE.foliate.goTo(STATE.searchHits[0]);
        } catch (err) {
          /* 跳转失败仍返回命中数 */
        }
      }
      if (bridge()) {
        bridge().searchResult(STATE.searchHits.length, STATE.searchHits.length ? 1 : 0);
      }
    },

    searchNext() {
      if (STATE.kind === "pdf") {
        if (!STATE.searchHits.length) return;
        STATE.searchIndex = (STATE.searchIndex + 1) % STATE.searchHits.length;
        const page = STATE.searchHits[STATE.searchIndex];
        renderPdfPage(page);
        scrollToPage(page, false);
        if (bridge()) bridge().searchResult(STATE.searchHits.length, STATE.searchIndex + 1);
        return;
      }
      if (!STATE.searchHits.length || !STATE.foliate) return;
      STATE.searchIndex = (STATE.searchIndex + 1) % STATE.searchHits.length;
      STATE.foliate.goTo(STATE.searchHits[STATE.searchIndex]).catch(() => {});
      if (bridge()) {
        bridge().searchResult(STATE.searchHits.length, STATE.searchIndex + 1);
      }
    },

    closeSearch() {
      STATE.searchQuery = "";
      STATE.searchHits = [];
      STATE.searchIndex = 0;
      if (STATE.foliate) {
        try {
          STATE.foliate.clearSearch();
        } catch (err) {
          /* 忽略 */
        }
      }
    },
  };

  window.readerApi = api;

  document.addEventListener("DOMContentLoaded", () => {
    bindSelectionBar();
    bindSideNav();
    window.addEventListener("resize", scheduleFitPaper);
    document.addEventListener("keyup", handleKey);
    document.addEventListener("mouseup", (event) => {
      if (event.target && event.target.closest && event.target.closest("#selectionBar")) return;
      if (STATE.kind === "epub") return;
      if (!window.getSelection || !window.getSelection().toString().trim()) hideSelection();
    });
  });
})();
