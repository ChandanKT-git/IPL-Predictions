import React from "react";
import { Activity } from "lucide-react";
import SourceBadge from "./SourceBadge";

export const Header = ({ step, source, version }) => (
  <header
    className="sticky top-0 z-40 glass border-b border-white/10"
    data-testid="app-header"
  >
    <div className="max-w-7xl mx-auto px-6 sm:px-8 py-4 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-md bg-[#FF3B30] flex items-center justify-center shadow-[0_0_24px_rgba(255,59,48,0.45)]">
          <Activity className="w-5 h-5 text-white" strokeWidth={2.5} />
        </div>
        <div className="flex flex-col leading-none">
          <span className="font-heading text-xl tracking-wider uppercase">
            Pitch<span className="text-[#FF3B30]">Pulse</span>
          </span>
          <span className="text-[10px] tracking-[0.3em] uppercase text-white/50 mt-1">
            IPL Match Predictor
          </span>
        </div>
      </div>
      <div className="hidden sm:flex items-center gap-6">
        <span className="text-[10px] tracking-[0.3em] uppercase text-white/40">
          Live model
        </span>
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          <span className="text-xs font-mono text-white/70">{version || "v1.0"}</span>
        </div>
        {source && <SourceBadge source={source} />}
      </div>
    </div>
    <div className="max-w-7xl mx-auto px-6 sm:px-8 pb-3">
      <div className="flex items-center gap-2 text-[10px] tracking-[0.25em] uppercase text-white/40">
        {[
          { id: 1, label: "Teams" },
          { id: 2, label: "Playing XI" },
          { id: 3, label: "Conditions" },
          { id: 4, label: "Prediction" },
        ].map((s, idx) => {
          const active = step === s.id;
          const done = step > s.id;
          return (
            <React.Fragment key={s.id}>
              <span
                className={`flex items-center gap-2 ${active ? "text-white" : done ? "text-emerald-400" : ""
                  }`}
                data-testid={`step-${s.id}`}
              >
                <span
                  className={`w-5 h-5 rounded-full grid place-items-center text-[10px] border ${active
                      ? "bg-[#FF3B30] border-[#FF3B30] text-white"
                      : done
                        ? "bg-emerald-500/20 border-emerald-400 text-emerald-300"
                        : "border-white/20"
                    }`}
                >
                  {done ? "✓" : s.id}
                </span>
                {s.label}
              </span>
              {idx < 3 && <span className="flex-1 h-px bg-white/10" />}
            </React.Fragment>
          );
        })}
      </div>
    </div>
  </header>
);

export default Header;
