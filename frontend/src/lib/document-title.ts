// 浏览器标签标题唯一出口：useDocumentTitle 经 setBaseTitle 设基础标题；
// sessionStore 在后台收到 done/error 终态时 flagDone 加「✓ 已完成 」前缀，
// 回到前台（visibilitychange）自动 clearDone 恢复，避免两处直接写 document.title 打架。
const DONE_PREFIX = "✓ 已完成 ";
const DEFAULT_TITLE = "NeuralHub";

let baseTitle = DEFAULT_TITLE;
let doneFlagged = false;

const apply = () => {
  if (typeof document === "undefined") return;
  document.title = doneFlagged ? `${DONE_PREFIX}${baseTitle}` : baseTitle;
};

const onVisibilityChange = () => {
  if (typeof document === "undefined" || document.hidden) return;
  clearDone();
};

export function setBaseTitle(title: string): void {
  baseTitle = title.trim() || DEFAULT_TITLE;
  apply();
}

export function flagDone(): void {
  if (typeof document === "undefined" || doneFlagged) return;
  doneFlagged = true;
  document.addEventListener("visibilitychange", onVisibilityChange);
  apply();
}

export function clearDone(): void {
  if (typeof document === "undefined" || !doneFlagged) return;
  doneFlagged = false;
  document.removeEventListener("visibilitychange", onVisibilityChange);
  apply();
}
