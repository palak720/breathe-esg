import { Outlet, NavLink } from "react-router-dom";
import { useAuth } from "../AuthContext";
import { LayoutDashboard, Upload, ClipboardList, List, LogOut } from "lucide-react";
import clsx from "clsx";

const nav = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/review", label: "Review Records", icon: ClipboardList },
  { to: "/upload", label: "Upload Data", icon: Upload },
  { to: "/jobs", label: "Ingestion Jobs", icon: List },
];

export default function Layout() {
  const { user, logout } = useAuth();
  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <aside className="w-56 flex-none bg-brand-800 text-white flex flex-col">
        <div className="px-5 py-5 border-b border-brand-700">
          <div className="text-lg font-semibold tracking-tight">Breathe ESG</div>
          <div className="text-xs text-brand-200 mt-0.5">Data Review Portal</div>
        </div>
        <nav className="flex-1 px-3 py-4 space-y-1">
          {nav.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) => clsx(
                "flex items-center gap-2.5 px-3 py-2 rounded-md text-sm font-medium transition-colors",
                isActive
                  ? "bg-brand-700 text-white"
                  : "text-brand-100 hover:bg-brand-700/60"
              )}
            >
              <Icon size={16} />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="px-4 py-4 border-t border-brand-700">
          <div className="text-xs text-brand-200 mb-1">{user?.org?.name}</div>
          <div className="text-sm font-medium">{user?.username}</div>
          <div className="text-xs text-brand-300 capitalize">{user?.role?.toLowerCase()}</div>
          <button
            onClick={logout}
            className="mt-3 flex items-center gap-1.5 text-xs text-brand-300 hover:text-white transition-colors"
          >
            <LogOut size={13} /> Sign out
          </button>
        </div>
      </aside>
      {/* Main */}
      <main className="flex-1 overflow-auto bg-gray-50">
        <Outlet />
      </main>
    </div>
  );
}
