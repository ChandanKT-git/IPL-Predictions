import React from "react";

const ResultDot = ({ result }) => {
  const colors = {
    W: "bg-green-500 shadow-[0_0_10px_rgba(34,197,94,0.4)]",
    L: "bg-red-500 shadow-[0_0_10px_rgba(239,68,68,0.4)]",
    NR: "bg-gray-500 shadow-[0_0_10px_rgba(107,114,128,0.4)]",
    D: "bg-yellow-500 shadow-[0_0_10px_rgba(234,179,8,0.4)]",
  };
  return (
    <div
      className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold text-white ${colors[result] || "bg-gray-500"
        }`}
    >
      {result}
    </div>
  );
};

export const FormGuide = ({ teamName, form }) => {
  if (!form || form.length === 0) return null;
  return (
    <div className="flex items-center gap-3">
      <span className="text-[10px] tracking-widest uppercase text-white/40 font-mono w-12">
        {teamName}
      </span>
      <div className="flex gap-1.5">
        {form.map((r, i) => (
          <ResultDot key={i} result={r} />
        ))}
      </div>
    </div>
  );
};

export const H2HStats = ({ data, teamA, teamB }) => {
  if (!data || !data.total_matches) return null;
  const seasonRows = data.season_aggregates || [];
  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center text-[10px] tracking-[0.2em] uppercase text-white/40 mb-2">
        <span>Head-to-Head</span>
        <span>Last 5 Matches</span>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="bg-white/5 rounded-lg p-3 border border-white/10 text-center">
          <div className="text-2xl font-heading text-white">
            {data.win_count?.[teamA.id] ?? 0}
          </div>
          <div className="text-[8px] uppercase tracking-widest text-white/40">
            {teamA.short_name} Wins
          </div>
        </div>
        <div className="bg-white/5 rounded-lg p-3 border border-white/10 text-center">
          <div className="text-2xl font-heading text-white">
            {data.win_count?.[teamB.id] ?? 0}
          </div>
          <div className="text-[8px] uppercase tracking-widest text-white/40">
            {teamB.short_name} Wins
          </div>
        </div>
      </div>

      <div className="space-y-2">
        {(data.last_5 || []).map((m, i) => (
          <div
            key={i}
            className="flex justify-between items-center text-[10px] py-1 border-b border-white/5 last:border-0"
          >
            <span className="text-white/40">{m.year}</span>
            <span
              className="font-bold uppercase"
              style={{
                color: m.winner === teamA.id ? teamA.primary_color : teamB.primary_color,
              }}
            >
              {m.winner === teamA.id ? teamA.short_name : teamB.short_name}
            </span>
            <span className="text-white/40 italic">{m.margin}</span>
          </div>
        ))}
      </div>

      {seasonRows.length > 0 && (
        <div className="pt-3 border-t border-white/10">
          <div className="text-[10px] tracking-[0.2em] uppercase text-white/40 mb-2">
            Season Aggregates
          </div>
          <div className="max-h-32 overflow-y-auto space-y-1">
            {seasonRows.slice(0, 6).map((s) => (
              <div key={s.season} className="flex justify-between text-[10px] font-mono">
                <span className="text-white/50">{s.season}</span>
                <span className="text-white/70">{s.matches} m</span>
                <span style={{ color: teamA.primary_color }}>{s.team_a_wins}</span>
                <span className="text-white/30">–</span>
                <span style={{ color: teamB.primary_color }}>{s.team_b_wins}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
