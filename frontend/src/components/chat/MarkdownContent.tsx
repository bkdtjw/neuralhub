import { memo, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import remarkGfm from "remark-gfm";

interface MarkdownContentProps {
  content: string;
}

interface CodeBlockProps {
  code: string;
  language: string;
}

function CodeBlock({ code, language }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);
  const label = language || "text";

  const copyCode = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="my-3 overflow-hidden rounded-lg border border-[var(--as-border-strong)] bg-[var(--as-code-bg)]">
      <div className="flex h-8 items-center justify-between border-b border-[var(--as-border)] bg-[var(--as-surface)] px-3">
        <span className="font-mono text-[11px] text-[var(--as-text-muted)]">{label}</span>
        <button
          type="button"
          onClick={copyCode}
          className="rounded-md px-2 py-1 text-[11px] text-[var(--as-text-secondary)] hover:bg-[var(--as-hover)] hover:text-[var(--as-text)]"
        >
          {copied ? "已复制" : "复制"}
        </button>
      </div>
      <SyntaxHighlighter
        language={label}
        style={oneDark}
        customStyle={{
          margin: 0,
          background: "var(--as-code-bg)",
          padding: "14px",
          fontSize: "12px",
          lineHeight: 1.65,
        }}
        codeTagProps={{ style: { fontFamily: "var(--as-font-mono)" } }}
      >
        {code}
      </SyntaxHighlighter>
    </div>
  );
}

const components: Components = {
  p: ({ children }) => <p className="my-3 leading-7 first:mt-0 last:mb-0">{children}</p>,
  strong: ({ children }) => <strong className="font-medium text-[var(--as-text-bright)]">{children}</strong>,
  h1: ({ children }) => <h1 className="mb-3 mt-5 text-xl font-medium text-[var(--as-text-bright)] first:mt-0">{children}</h1>,
  h2: ({ children }) => <h2 className="mb-2 mt-5 text-lg font-medium text-[var(--as-text-bright)] first:mt-0">{children}</h2>,
  h3: ({ children }) => <h3 className="mb-2 mt-4 text-base font-medium text-[var(--as-text-bright)] first:mt-0">{children}</h3>,
  ul: ({ children }) => <ul className="as-md-list my-3 space-y-1">{children}</ul>,
  ol: ({ children }) => <ol className="my-3 list-decimal space-y-1 pl-5 marker:text-[var(--as-accent)]">{children}</ol>,
  li: ({ children }) => <li className="leading-7">{children}</li>,
  a: ({ children, href }) => (
    <a href={href} target="_blank" rel="noreferrer" className="text-[var(--as-accent-soft)] underline-offset-4 hover:underline">
      {children}
    </a>
  ),
  blockquote: ({ children }) => <blockquote className="my-3 border-l-2 border-[var(--as-border-strong)] pl-3 text-[var(--as-text-secondary)]">{children}</blockquote>,
  pre: ({ children }) => <>{children}</>,
  code: ({ className, children }) => {
    const match = /language-([\w-]+)/.exec(className ?? "");
    const code = String(children).replace(/\n$/, "");
    if (match) return <CodeBlock language={match[1]} code={code} />;
    return (
      <code className="rounded-md border border-[var(--as-border-strong)] bg-[#0a0a0c] px-1.5 py-0.5 font-mono text-[0.86em] text-[#93c5fd]">
        {children}
      </code>
    );
  },
  table: ({ children }) => <div className="my-3 overflow-x-auto"><table className="w-full border-collapse text-sm">{children}</table></div>,
  th: ({ children }) => <th className="border border-[var(--as-border-strong)] bg-[var(--as-surface)] px-2 py-1 text-left font-medium text-[var(--as-text-bright)]">{children}</th>,
  td: ({ children }) => <td className="border border-[var(--as-border)] px-2 py-1 align-top">{children}</td>,
};

function MarkdownContent({ content }: MarkdownContentProps) {
  return (
    <div className="as-markdown text-sm leading-7 text-[var(--as-text)]">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}

// memo：历史气泡的 content 为稳定字符串，流式期间跳过整棵 ReactMarkdown/Prism 重渲。
export default memo(MarkdownContent);
