import { lazy, Suspense, type ReactNode } from "react";
import { BrowserRouter, HashRouter, Route, Routes } from "react-router-dom";

import ErrorBoundary from "@/components/common/ErrorBoundary";
import RouteLoading from "@/components/common/RouteLoading";
import Sidebar from "@/components/sidebar/Sidebar";
import WorkspacePicker from "@/components/workspace/WorkspacePicker";
import Dashboard from "@/pages/Dashboard";
import Session from "@/pages/Session";

// 非核心路由懒加载，缩小首屏 bundle；会话页（/ 与 /session/*）保持同步加载。
const Hooks = lazy(() => import("@/pages/Hooks"));
const Knowledge = lazy(() => import("@/pages/Knowledge"));
const Logs = lazy(() => import("@/pages/Logs"));
const Metrics = lazy(() => import("@/pages/Metrics"));
const Settings = lazy(() => import("@/pages/Settings"));

// 每个路由页各包一层局部边界：单页崩溃不拖垮侧栏与其他路由
const guard = (page: ReactNode): ReactNode => <ErrorBoundary>{page}</ErrorBoundary>;

export default function App() {
  const Router = window.location.protocol === "file:" ? HashRouter : BrowserRouter;

  return (
    <ErrorBoundary>
      <Router>
        <div className="flex h-screen bg-[var(--as-bg)] text-[var(--as-text)]">
          <Sidebar />
          <main className="min-w-0 flex-1 overflow-hidden bg-[var(--as-bg)]">
            <Suspense fallback={<RouteLoading />}>
              <Routes>
                <Route path="/" element={guard(<Dashboard />)} />
                <Route path="/hooks" element={guard(<Hooks />)} />
                <Route path="/knowledge" element={guard(<Knowledge />)} />
                <Route path="/metrics" element={guard(<Metrics />)} />
                <Route path="/logs" element={guard(<Logs />)} />
                <Route path="/session/:id" element={guard(<Session />)} />
                <Route path="/settings" element={guard(<Settings />)} />
              </Routes>
            </Suspense>
          </main>
          <WorkspacePicker />
        </div>
      </Router>
    </ErrorBoundary>
  );
}
