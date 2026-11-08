import React from 'react';
import { LayoutDashboard, Star, Briefcase, History, Newspaper, Sparkles, TrendingUp, ShieldCheck } from 'lucide-react';

interface SidebarNavProps {
  currentView: 'dashboard' | 'watchlist' | 'portfolio' | 'orders' | 'news' | 'research';
  onNavigate: (view: 'dashboard' | 'watchlist' | 'portfolio' | 'orders' | 'news' | 'research') => void;
}

export const SidebarNav: React.FC<SidebarNavProps> = ({ currentView, onNavigate }) => {
  const navItems = [
    { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { id: 'watchlist', label: 'Watchlist', icon: Star },
    { id: 'portfolio', label: 'Portfolio', icon: Briefcase },
    { id: 'orders', label: 'Orders & Activity', icon: History },
    { id: 'news', label: 'Market News', icon: Newspaper },
    { id: 'research', label: 'AI Research', icon: Sparkles },
  ] as const;

  return (
    <aside className="w-64 bg-slate-950/70 border-r border-slate-800/80 p-4 flex flex-col justify-between shrink-0">
      <div className="space-y-6">
        <div>
          <div className="text-[10px] uppercase font-bold text-slate-500 px-3 mb-2 tracking-wider">
            Workspace
          </div>
          <nav className="space-y-1">
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = currentView === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => onNavigate(item.id)}
                  className={`w-full flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-xs font-semibold transition-all ${
                    isActive
                      ? 'bg-gradient-to-r from-indigo-600/90 to-indigo-700 text-white shadow-lg shadow-indigo-900/30 font-bold'
                      : 'text-slate-400 hover:text-white hover:bg-slate-900/80'
                  }`}
                >
                  <Icon
                    className={`w-4 h-4 ${isActive ? 'text-white' : 'text-slate-400'}`}
                  />
                  <span>{item.label}</span>
                </button>
              );
            })}
          </nav>
        </div>

        {/* Market Status Card */}
        <div className="p-3.5 bg-slate-900/90 rounded-2xl border border-slate-800/80 space-y-2">
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-slate-400 font-medium">Market Status</span>
            <span className="flex items-center gap-1.5 text-emerald-400 font-bold text-[10px]">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" />
              OPEN (SIM)
            </span>
          </div>
          <div className="text-[10px] text-slate-500 leading-relaxed">
            Paper execution engine active. Market orders match against local quote cache.
          </div>
        </div>
      </div>

      {/* Footer Info */}
      <div className="pt-4 border-t border-slate-800/80 text-[11px] text-slate-500 flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <ShieldCheck className="w-3.5 h-3.5 text-indigo-400" />
          <span>Demo Trading</span>
        </div>
        <span className="text-[10px] text-slate-600">v2.0</span>
      </div>
    </aside>
  );
};

