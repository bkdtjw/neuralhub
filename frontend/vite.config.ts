import { fileURLToPath, URL } from "node:url";

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// ===== vendor 拆包 =====
// 大依赖按生态拆独立 chunk：内容哈希互不干扰，改业务代码不会击穿 vendor 缓存；
// 分组只列 package.json 里真实存在的包及其传递依赖，跨组共享的小模块由 Rollup
// 自动落到先声明的组并以 chunk 间 import 复用，不会重复打包。
const REACT_PKGS = new Set(["react", "react-dom", "scheduler", "react-router", "react-router-dom"]);
const HIGHLIGHT_PKGS = new Set([
  "react-syntax-highlighter",
  "refractor",
  "prismjs",
  "highlight.js",
  "highlightjs-vue",
  "lowlight",
  "fault",
  "format",
]);
const DIFF_PKGS = new Set(["diff2html", "diff", "@profoundlogic/hogan"]);
const MARKDOWN_PKGS = new Set([
  "react-markdown",
  "unified",
  "hastscript",
  "bail",
  "trough",
  "zwitch",
  "devlop",
  "ccount",
  "markdown-table",
  "longest-streak",
  "escape-string-regexp",
  "decode-named-character-reference",
  "property-information",
  "space-separated-tokens",
  "comma-separated-tokens",
  "estree-util-is-identifier-name",
  "style-to-js",
  "style-to-object",
  "inline-style-parser",
  "html-url-attributes",
  "trim-lines",
]);
const MARKDOWN_PREFIXES = ["remark", "micromark", "mdast-util", "unist-util", "hast-util", "vfile", "character-entities"];

function packageName(id: string): string | undefined {
  const marker = "node_modules/";
  const start = id.lastIndexOf(marker);
  if (start === -1) return undefined;
  const rest = id.slice(start + marker.length);
  const parts = rest.split("/");
  return parts[0].startsWith("@") ? `${parts[0]}/${parts[1]}` : parts[0];
}

function manualChunks(id: string): string | undefined {
  const pkg = packageName(id);
  if (!pkg) return undefined;
  if (REACT_PKGS.has(pkg)) return "vendor-react";
  if (HIGHLIGHT_PKGS.has(pkg)) return "vendor-highlight";
  if (DIFF_PKGS.has(pkg)) return "vendor-diff";
  if (MARKDOWN_PKGS.has(pkg) || MARKDOWN_PREFIXES.some((prefix) => pkg.startsWith(prefix))) {
    return "vendor-markdown";
  }
  return undefined;
}

export default defineConfig({
  base: "/",
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  build: {
    outDir: "../dist/frontend",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks,
      },
    },
  },
  server: {
    proxy: {
      "/v1": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/ws": {
        target: "http://localhost:8000",
        changeOrigin: true,
        ws: true,
      },
    },
  },
});
