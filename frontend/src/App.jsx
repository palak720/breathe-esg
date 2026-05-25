import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider, useAuth } from "./AuthContext";
import LoginPage from "./pages/Login";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import ReviewPage from "./pages/Review";
import UploadPage from "./pages/Upload";
import JobsPage from "./pages/Jobs";

const qc = new QueryClient({ defaultOptions: { queries: { staleTime: 30_000 } } });

function RequireAuth({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="flex h-screen items-center justify-center text-gray-400">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/" element={<RequireAuth><Layout /></RequireAuth>}>
              <Route index element={<Dashboard />} />
              <Route path="review" element={<ReviewPage />} />
              <Route path="upload" element={<UploadPage />} />
              <Route path="jobs" element={<JobsPage />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
}
