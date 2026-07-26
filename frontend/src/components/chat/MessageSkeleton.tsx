// 会话详情拉取中的消息骨架：占住消息区，消灭“刷新已有会话先闪一屏空状态建议卡再蹦出消息”。
// 布局对齐 MessageList 的 max-w-[760px] 容器；右对齐窄块模拟用户消息、左侧宽块模拟助手回复。
const BLOCKS: { align: "start" | "end"; width: string; height: string }[] = [
  { align: "end", width: "w-2/5", height: "h-10" },
  { align: "start", width: "w-4/5", height: "h-24" },
  { align: "end", width: "w-1/3", height: "h-10" },
  { align: "start", width: "w-3/5", height: "h-16" },
];

export default function MessageSkeleton() {
  return (
    <main aria-hidden className="min-h-0 flex-1 overflow-hidden px-6 pb-40 pt-8">
      <div className="mx-auto flex w-full max-w-[760px] animate-pulse flex-col gap-4">
        {BLOCKS.map((block, index) => (
          <div
            key={index}
            className={`${block.height} ${block.width} rounded-2xl bg-[var(--as-surface-low)] ${block.align === "end" ? "self-end" : "self-start"}`}
          />
        ))}
      </div>
    </main>
  );
}
