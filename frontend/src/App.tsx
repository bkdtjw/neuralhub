import { lazy, Suspense } from "react";
import { BrowserRouter, HashRouter, Route, Routes } from "react-router-dom";

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

export default function App() {
  const Router = window.location.protocol === "file:" ? HashRouter : BrowserRouter;

  return (
    <Router>
      <div className="flex h-screen bg-[var(--as-bg)] text-[var(--as-text)]">
        <Sidebar />
        <main className="min-w-0 flex-1 overflow-hidden bg-[var(--as-bg)]">
          <Suspense fallback={<RouteLoading />}>
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/hooks" element={<Hooks />} />
              <Route path="/knowledge" element={<Knowledge />} />
              <Route path="/metrics" element={<Metrics />} />
              <Route path="/logs" element={<Logs />} />
              <Route path="/session/:id" element={<Session />} />
              <Route path="/settings" element={<Settings />} />
            </Routes>
          </Suspense>
        </main>
        <WorkspacePicker />
      </div>
    </Router>
  );
}
