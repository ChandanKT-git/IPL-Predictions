import React, { useEffect, useMemo, useState } from "react";
import { fetchLiveMatches, fetchUpcomingMatches } from "../lib/api";
import { RadioTower, Loader2, ChevronRight, Calendar } from "lucide-react";
import { toast } from "sonner";

const flattenIplMatches = (data) => {
  const out = [];
  data?.typeMatches?.forEach((tm) => {
    tm.seriesMatches?.forEach((sm) => {
      sm.seriesAdWrapper?.matches?.forEach((m) => {
        if (m.matchInfo?.seriesName?.includes("Indian Premier League")) {
          out.push(m);
        }
      });
    });
  });
  return out;
};

const formatStartTime = (rawMillis) => {
  const ms = Number(rawMillis);
  if (!ms) return "TBD";
  const date = new Date(ms);
  if (Number.isNaN(date.getTime())) return "TBD";
  return date.toLocaleString(undefined, {
    weekday: "short",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
};

export const LiveMatchPicker = ({ onSelectMatch }) => {
  const [tab, setTab] = useState("live");
  const [liveMatches, setLiveMatches] = useState([]);
  const [upcomingMatches, setUpcomingMatches] = useState([]);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (!expanded) return undefined;
    let active = true;
    setLoading(true);
    const fetcher = tab === "upcoming" ? fetchUpcomingMatches : fetchLiveMatches;
    fetcher()
      .then((data) => {
        if (!active) return;
        const matches = flattenIplMatches(data);
        if (tab === "upcoming") setUpcomingMatches(matches);
        else setLiveMatches(matches);
      })
      .catch(() =>
        toast.error(`Could not fetch ${tab === "upcoming" ? "upcoming" : "live"} IPL matches.`),
      )
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [expanded, tab]);

  const matches = tab === "upcoming" ? upcomingMatches : liveMatches;

  const renderMatchRow = useMemo(
    () => (m) => (
      <button
        key={m.matchInfo.matchId}
        onClick={() => onSelectMatch(m, tab)}
        className="w-full flex items-center justify-between p-4 rounded-xl glass border border-white/5 hover:border-[#FF3B30]/40 hover:bg-[#FF3B30]/5 transition-all text-left group"
      >
        <div>
          <div className="text-[10px] text-white/40 uppercase tracking-widest mb-1">
            {m.matchInfo.venueInfo?.ground}, {m.matchInfo.venueInfo?.city}
          </div>
          <div className="flex gap-3 items-center text-sm uppercase font-heading">
            <span>{m.matchInfo.team1?.teamName}</span>
            <span className="text-white/20">VS</span>
            <span>{m.matchInfo.team2?.teamName}</span>
          </div>
          {tab === "live" && m.matchScore && (
            <div className="mt-1 text-xs font-mono text-[#FF3B30]">
              {m.matchScore.team1Score?.inngs1?.runs || 0}/
              {m.matchScore.team1Score?.inngs1?.wickets || 0} (
              {m.matchScore.team1Score?.inngs1?.overs || 0}) vs{" "}
              {m.matchScore.team2Score?.inngs1?.runs || 0}/
              {m.matchScore.team2Score?.inngs1?.wickets || 0} (
              {m.matchScore.team2Score?.inngs1?.overs || 0})
            </div>
          )}
          {tab === "upcoming" && (
            <div className="mt-1 font-mono text-xs text-white/50">
              {formatStartTime(m.matchInfo.startDate)}
            </div>
          )}
        </div>
        <ChevronRight className="w-4 h-4 text-white/20 group-hover:text-[#FF3B30] transition-colors" />
      </button>
    ),
    [tab, onSelectMatch],
  );

  return (
    <div className="mb-8">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 px-4 py-2 rounded-full border border-[#FF3B30]/30 bg-[#FF3B30]/10 text-[#FF3B30] text-xs font-heading uppercase tracking-widest hover:bg-[#FF3B30]/20 transition-all mx-auto"
      >
        <RadioTower className={`w-3.5 h-3.5 ${loading ? "animate-pulse" : ""}`} />
        {expanded ? "Close Match Picker" : "Auto-fill from IPL Match"}
      </button>

      {expanded && (
        <div className="mx-auto mt-4 space-y-3 max-w-xl animate-fade-down">
          <div className="flex gap-2 justify-center mb-2">
            {[
              { id: "live", icon: <RadioTower className="w-3 h-3" />, label: "Live" },
              { id: "upcoming", icon: <Calendar className="w-3 h-3" />, label: "Upcoming" },
            ].map(({ id, icon, label }) => (
              <button
                key={id}
                onClick={() => setTab(id)}
                className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-[10px] font-heading uppercase tracking-widest transition-all ${tab === id
                    ? "bg-[#FF3B30]/20 border border-[#FF3B30]/40 text-[#FF3B30]"
                    : "border border-white/10 text-white/50 hover:text-white"
                  }`}
              >
                {icon}
                {label}
              </button>
            ))}
          </div>

          {loading ? (
            <div className="flex justify-center items-center py-8 font-mono text-xs text-white/40">
              <Loader2 className="mr-2 w-4 h-4 animate-spin" /> SCANNING AIRWAVES...
            </div>
          ) : matches.length === 0 ? (
            <div className="py-8 font-mono text-xs text-center rounded-xl border border-dashed text-white/40 border-white/10">
              {tab === "upcoming"
                ? "NO UPCOMING IPL MATCHES SCHEDULED."
                : "NO LIVE IPL MATCHES DETECTED RIGHT NOW."}
            </div>
          ) : (
            matches.map(renderMatchRow)
          )}
        </div>
      )}
    </div>
  );
};
