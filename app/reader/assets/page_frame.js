/* 书格阅读 · 页框尺寸计算（T16 固定页框的纯逻辑，单测来源）。
 *
 * 这是一个零依赖、可在浏览器与 Node 中运行的 UMD 模块：
 *   - 浏览器：挂到 window.BSPageFrame
 *   - Node：module.exports = BSPageFrame
 *
 * 职责：给定「视口尺寸」与「reader prefs」，算出当前书页矩形的宽高与摊开状态。
 * 关键约定（对应 docs/书格-1.1.6-阅读界面v3-给TRAE.md §二/§四）：
 *   1) 页高 = 视口高（固定页框），字号/行距变化只重新分页，不拉长书页；
 *   2) fixed_page_width=true（默认）：页宽钉在 page_width，不随窗口变宽而拉长；
 *      fixed_page_width=false：流式放宽到 max_column_width；
 *   3) 摊开（spread）需要两页 + 中缝余量，按单页宽度计。
 */
(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    root.BSPageFrame = api;
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  function num(value, fallback) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  function isTruthyFixed(value) {
    // 仅当显式置为假值时才视为「不固定」；缺省 = 固定（保持旧行为）。
    if (value === false) return false;
    if (value === 0) return false;
    if (typeof value === "string" && value.toLowerCase() === "false") return false;
    return true;
  }

  /**
   * @param {{width:number,height:number}} viewport 画布内尺寸（已剔除 padding）
   * @param {object} prefs reader prefs
   * @param {"epub"|"pdf"|string} kind
   * @returns {{width:number,height:number,spread:boolean,pageWidth:number,
   *           desired:number,fixed:boolean,maxColumnCount:number,widthCap:number,usable:number}}
   */
  function computeFrame(viewport, prefs, kind) {
    prefs = prefs || {};
    kind = kind || "epub";
    const pageW = Math.max(320, num(prefs.page_width, 560));
    const maxCol = Math.max(320, num(prefs.max_column_width, 920));
    const desired = Math.min(pageW, maxCol);

    const vw = Math.max(0, num(viewport && viewport.width, 0));
    const vh = Math.max(0, num(viewport && viewport.height, 0));
    const height = Math.max(320, vh || 640);

    let spread = false;
    let pageWidth;
    let widthCap;
    let usable;

    if (kind !== "epub") {
      // PDF 等非 epub：维持旧逻辑——按 max_column_width 取宽，不扣水平页边距。
      usable = Math.max(320, vw || maxCol);
      widthCap = maxCol;
      pageWidth = Math.max(320, Math.min(maxCol, vw || maxCol));
    } else {
      const legacy = num(prefs.margin_px, 64);
      const hMargin =
        Math.max(0, num(prefs.margin_left, legacy)) +
        Math.max(0, num(prefs.margin_right, legacy));
      usable = Math.max(320, (vw || desired) - hMargin);
      const fixed = isTruthyFixed(prefs.fixed_page_width);
      // 固定：钉在 page_width；流式：放宽到 max_column_width。
      widthCap = fixed ? desired : maxCol;
      const wantSpread = String(prefs.page_mode) === "spread";
      spread = wantSpread && usable >= desired * 2 + 48; // 48 给中缝与余量
      pageWidth = spread
        ? Math.min(widthCap, Math.max(320, Math.floor(usable / 2)))
        : Math.min(widthCap, usable);
    }

    return {
      width: pageWidth, // foliate max-inline-size / CSS --page-max
      height: height, // foliate max-block-size（固定 = 视口高）
      spread: spread,
      pageWidth: pageWidth,
      desired: desired,
      fixed: kind === "epub" && isTruthyFixed(prefs.fixed_page_width),
      maxColumnCount: spread ? 2 : 1,
      widthCap: widthCap,
      usable: usable,
    };
  }

  return {
    computeFrame: computeFrame,
    num: num,
    isTruthyFixed: isTruthyFixed,
  };
});
