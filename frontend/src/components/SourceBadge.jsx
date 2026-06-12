import React from "react";
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "./ui/tooltip";

/**
 * SourceBadge — pure presentational badge for the catalog data provenance.
 *
 * Props:
 *   source: "live" | "cache" | "fallback" | "mixed"
 *
 * Visual mapping:
 *   live     → green dot, label "LIVE"     (tooltip: live Cricbuzz cached for up to 6 hours)
 *   cache    → green dot, label "CACHED"   (tooltip: live Cricbuzz cached for up to 6 hours)
 *   fallback → amber dot, label "OFFLINE"  (tooltip: showing offline data)
 *   mixed    → amber dot, label "PARTIAL"  (tooltip: some live, some offline)
 *
 * No new dependencies. Uses the existing shadcn Tooltip primitive.
 */
const SOURCE_CONFIG = {
    live: {
        label: "LIVE",
        dotClass: "bg-emerald-400",
        tooltip: "Cricbuzz live data (cached for up to 6 hours)",
    },
    cache: {
        label: "CACHED",
        dotClass: "bg-emerald-400",
        tooltip: "Cricbuzz live data (cached for up to 6 hours)",
    },
    fallback: {
        label: "OFFLINE",
        dotClass: "bg-amber-400",
        tooltip:
            "Showing offline data \u2014 live Cricbuzz data is currently unavailable",
    },
    mixed: {
        label: "PARTIAL",
        dotClass: "bg-amber-400",
        tooltip: "Some data live, some offline",
    },
};

export const SourceBadge = ({ source }) => {
    const config = SOURCE_CONFIG[source];
    if (!config) return null;

    return (
        <TooltipProvider delayDuration={150}>
            <Tooltip>
                <TooltipTrigger asChild>
                    <span
                        role="status"
                        aria-label={`Data source: ${config.label}`}
                        data-testid={`source-badge-${source}`}
                        tabIndex={0}
                        className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] font-mono tracking-[0.2em] uppercase text-white/70 cursor-default focus:outline-none focus:ring-1 focus:ring-white/20"
                    >
                        <span
                            aria-hidden="true"
                            className={`w-1.5 h-1.5 rounded-full ${config.dotClass}`}
                        />
                        <span>{config.label}</span>
                    </span>
                </TooltipTrigger>
                <TooltipContent side="bottom">{config.tooltip}</TooltipContent>
            </Tooltip>
        </TooltipProvider>
    );
};

export default SourceBadge;
