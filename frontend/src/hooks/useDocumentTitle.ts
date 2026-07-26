import { useEffect } from "react";

import { setBaseTitle } from "@/lib/document-title";

// 各页面统一设置标签页标题为「{页名} - NeuralHub」。
// 卸载时不强行还原：下一页挂载后会自行 setBaseTitle 覆盖。
export function useDocumentTitle(name: string): void {
  useEffect(() => {
    setBaseTitle(name.trim() ? `${name.trim()} - NeuralHub` : "NeuralHub");
  }, [name]);
}
