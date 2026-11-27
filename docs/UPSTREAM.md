# 上游参考与复用边界

## 当前版本

EPUB 阅读内核使用 foliate-js（MIT），从 Readest 的 foliate-js 复刻仓库引入并做了最小适配；其余模块仍为独立实现。

| 项目 | 复用内容 | 许可证 | 上游 |
|---|---|---|---|
| Readest / foliate-js | EPUB 解析、分页排版、CFI、标注、搜索内核 | MIT | https://github.com/readest/foliate-js 、 https://github.com/johnfactotum/foliate-js |
| Calibre | 仅参考 Windows 路径净化规则、字段级非空优先与来源优先级思路、元数据测试样例约定 | GPL-3.0 | https://github.com/kovidgoyal/calibre |
| Koodo Reader | 仅参考空书库引导、设置说明组织方式、扫描前语义提示等交互 | AGPL-3.0 | https://github.com/koodo-reader/koodo-reader |

## foliate-js 引入记录

- 来源：`readest/foliate-js`，`main` 分支，获取日期 2026-11-25；原始项目 `johnfactotum/foliate-js`（MIT）。
- 位置：`app/reader/assets/vendor/foliate-js/`。
- 运行时文件：`foliate.bundle.js` 由 esbuild 以内联方式打包，包含 `view.js`、`paginator.js`、`epub.js`、`epubcfi.js`、`overlayer.js`、`search.js` 等模块与 `vendor/zip.js`、`vendor/fflate.js`；同时保留源码便于审计与重建。
- 修改：仅把 `view.js` 的 `fetchFile` 从 `fetch()` 改为 `XMLHttpRequest`，以支持 Qt WebEngine 从 `file://` 阅读页读取本地书籍；`@pdfjs/pdf.min.mjs` 保持外部引用，本项目 PDF 仍由 pdf.js 承担，不经过 foliate-js。
- 重新打包：在含 `esbuild` 与 `construct-style-sheets-polyfill` 的目录中执行
  `npx esbuild entry.js --bundle --format=iife --global-name=Foliate --target=chrome108 --minify --external:@pdfjs/pdf.min.mjs --outfile=foliate.bundle.js`，
  入口为 `import './view.js'; export { Overlayer } from './overlayer.js'`。
- 许可证：MIT，允许与 GPL-3.0-or-later 组合分发；原始版权声明见同目录 `LICENSE`，已随安装包分发。

## 将来移植代码时

1. 先确认目标文件的许可证与 GPL-3.0-or-later 兼容，并记录来源 URL、上游版本或 commit。
2. 保留原版权和许可证头，在移植文件中追加 `Ported into BookShelf` 及修改说明。
3. 将第三方许可证放入安装包的 `licenses` 目录，并同步更新本文件与 NOTICE。
4. 未经过上述审查，不把上游代码、资源或依赖直接加入仓库。
