import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";
import { AlertTriangle, RefreshCw, RotateCcw } from "lucide-react";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

/** 渲染错误边界：局部包裹单页路由时，单页崩溃不拖垮侧栏与其他路由。 */
export default class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("ErrorBoundary caught", error, info.componentStack);
  }

  handleRetry = (): void => {
    this.setState({ error: null });
  };

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="flex h-full min-h-[220px] w-full items-center justify-center overflow-hidden p-6">
        <div className="as-glass w-full max-w-md rounded-2xl p-6 text-center">
          <div className="as-glass-inset mx-auto mb-3 grid h-10 w-10 place-items-center rounded-xl text-[var(--as-danger)]">
            <AlertTriangle size={18} />
          </div>
          <h2 className="text-base font-medium text-[var(--as-text-bright)]">页面出错了</h2>
          <p className="mx-auto mt-2 max-w-full truncate text-xs text-[var(--as-text-secondary)]" title={error.message}>
            {error.message || "未知错误"}
          </p>
          <div className="mt-4 flex items-center justify-center gap-2">
            <button
              type="button"
              onClick={this.handleRetry}
              className="as-glass-btn flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs"
            >
              <RotateCcw size={13} />
              重试
            </button>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="as-glass-accent flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs"
            >
              <RefreshCw size={13} />
              重新加载
            </button>
          </div>
        </div>
      </div>
    );
  }
}
