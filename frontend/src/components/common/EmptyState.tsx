import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description: string;
  /** 可选 CTA 按钮，如「前往设置」「新建知识库」。 */
  action?: { label: string; onClick: () => void };
  /** 可选附加内容（如开场建议卡），渲染在说明/CTA 下方。 */
  children?: ReactNode;
}

/** 通用空态卡：玻璃风居中布局，lucide 图标 + 标题 + 一句说明 + 可选 CTA。 */
export default function EmptyState({ icon: Icon, title, description, action, children }: EmptyStateProps) {
  return (
    <div className="as-glass flex w-full flex-col items-center rounded-2xl px-8 py-10 text-center">
      <div className="as-glass-inset flex h-12 w-12 items-center justify-center rounded-2xl text-[var(--as-accent-soft)]">
        <Icon size={22} />
      </div>
      <h3 className="mt-4 text-base font-medium text-[var(--as-text-bright)]">{title}</h3>
      <p className="mt-1.5 text-[13px] leading-6 text-[var(--as-text-secondary)]">{description}</p>
      {action ? (
        <button type="button" onClick={action.onClick} className="as-glass-accent mt-5 rounded-lg px-4 py-2 text-sm">
          {action.label}
        </button>
      ) : null}
      {children}
    </div>
  );
}
