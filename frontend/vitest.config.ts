import { defineConfig, mergeConfig } from "vitest/config";

import viteConfig from "./vite.config";

// 复用 vite.config 的 @ 别名等；仅为单元测试补测试环境。
// environment: jsdom —— 提供 window/localStorage/WebSocket，使 store 及其依赖可被 import。
// 不含 @testing-library/react，只做纯逻辑单测（事件归一化、store action）。
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: "jsdom",
      globals: true,
      include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    },
  }),
);
