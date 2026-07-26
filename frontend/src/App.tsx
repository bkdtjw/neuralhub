import type { ReactNode } from "react";
import { BrowserRouter, HashRouter, Route, Routes } from "react-router-dom";

import ErrorBoundary from "@/components/common/ErrorBoundary";
import Sidebar from "@/components/sidebar/Sidebar";
import WorkspacePicker from "@/components/workspace/WorkspacePicker";
import Dashboard from "@/pages/Dashboard";
import Hooks from "@/pages/Hooks";
import Knowledge from "@/pages/Knowledge";
import Logs from "@/pages/Logs";
import Metrics from "@/pages/Metrics";
import Session from "@/pages/Session";
import Settings from "@/pages/Settings";

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
            <Routes>
              <Route path="/" element={guard(<Dashboard />)} />
              <Route path="/hooks" element={guard(<Hooks />)} />
              <Route path="/knowledge" element={guard(<Knowledge />)} />
              <Route path="/metrics" element={guard(<Metrics />)} />
              <Route path="/logs" element={guard(<Logs />)} />
              <Route path="/session/:id" element={guard(<Session />)} />
              <Route path="/settings" element={guard(<Settings />)} />
            </Routes>
          </main>
          <WorkspacePicker />
        </div>
      </Router>
    </ErrorBoundary>
  );
}
