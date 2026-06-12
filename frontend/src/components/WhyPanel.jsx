import React from "react";
import { Compass } from "lucide-react";

const ARROWS = {
    "-1": "↓",
    "0": "·",
    "1": "↑",
};

const formatValue = (value) => {
    if (value === null || value === undefined) return "—";
    if (typeof value === "string") return value;
    if (typeof value === "number") {
        if (Math.abs(value) >= 100) return value.toFixed(0);
        if (Math.abs(value) >= 10) return value.toFixed(1);
        return value.toFixed(2);
    }
    return String(value);
};

/**
 * "Why this prediction" panel.
 *
 * Renders the top contributions returned by /api/predict — each one a
 * feature name with a label, the row's value, and a direction (+/-) that
 * tells the user whether that feature pushed the prediction up or down
 * relative to the historical mean.
 *
 * @param {{contributions: Array<{feature:string,label:string,value:number|string|null,importance:number,magnitude:number,direction:-1|0|1,z_score:number}>}} props
 */
export const WhyPanel = ({ contributions }) => {
    if (!contributions || contributions.length === 0) return null;
    const max = Math.max(...contributions.map((c) => c.magnitude || 0)) || 1;

    return (
        <div className="rounded-xl glass p-6 sm:p-8 grain mt-6">
            <div className="flex items-center gap-2 text-[10px] tracking-[0.3em] uppercase text-white/45 mb-4">
                <Compass className="w-3 h-3 text-[#FF3B30]" /> Why this prediction
            </div>
            <p className="text-xs text-white/50 mb-6">
                These features moved the model's projection most for this matchup.
                Arrows show whether the value pushed the score above (↑) or below (↓)
                the league-average baseline.
            </p>
            <div className="space-y-4" data-testid="why-panel">
                {contributions.map((c) => {
                    const magnitudePct = Math.round(((c.magnitude || 0) / max) * 100);
                    const arrow = ARROWS[String(c.direction ?? 0)];
                    const tone =
                        c.direction > 0
                            ? "text-emerald-400 border-emerald-400/40 bg-emerald-400/10"
                            : c.direction < 0
                                ? "text-red-400 border-red-400/40 bg-red-400/10"
                                : "text-white/50 border-white/10 bg-white/5";
                    return (
                        <div key={c.feature} className="space-y-2">
                            <div className="flex justify-between items-center text-xs">
                                <span className="text-white/80 font-heading uppercase tracking-wider">
                                    {c.label}
                                </span>
                                <span className="flex items-center gap-2">
                                    <span className={`px-2 py-0.5 rounded-full border text-[10px] ${tone}`}>
                                        {arrow} {Math.abs(c.z_score || 0).toFixed(1)}σ
                                    </span>
                                    <span className="font-mono text-white/50">
                                        {formatValue(c.value)}
                                    </span>
                                </span>
                            </div>
                            <div className="h-1.5 rounded-full bg-white/5 overflow-hidden">
                                <div
                                    className="h-full transition-all duration-700"
                                    style={{
                                        width: `${magnitudePct}%`,
                                        background:
                                            c.direction > 0
                                                ? "linear-gradient(90deg,#10B981,#34D399)"
                                                : c.direction < 0
                                                    ? "linear-gradient(90deg,#EF4444,#F87171)"
                                                    : "rgba(255,255,255,0.25)",
                                    }}
                                />
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
};

export default WhyPanel;
