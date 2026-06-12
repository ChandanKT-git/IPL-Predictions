import React, { useEffect, useState } from "react";
import { useQueries } from "@tanstack/react-query";
import { playersQuery } from "../lib/queries";
import { PlayerAvatar } from "./PlayerAvatar";
import { TeamLogo } from "./TeamLogo";
import { Check, Loader2 } from "lucide-react";

const ROLE_BADGE = {
  Batsman: "bg-amber-500/15 text-amber-300 border-amber-400/30",
  Bowler: "bg-sky-500/15 text-sky-300 border-sky-400/30",
  "All-rounder": "bg-emerald-500/15 text-emerald-300 border-emerald-400/30",
  "Wicket-keeper": "bg-fuchsia-500/15 text-fuchsia-300 border-fuchsia-400/30",
};

const PlayerCard = ({ player, team, selected, onToggle, disabled }) => (
  <button
    onClick={() => onToggle(player)}
    disabled={disabled && !selected}
    data-testid={`player-card-${team.id}-${player.name.replace(/\s/g, "-")}`}
    className={`group relative text-left p-3 rounded-xl card-lift overflow-hidden ${selected
        ? "bg-[#1A1A1A] border-2"
        : "bg-[#141414] border border-white/10 hover:border-white/25"
      } ${disabled && !selected ? "opacity-40 cursor-not-allowed" : ""}`}
    style={selected ? { borderColor: team.primary_color } : undefined}
  >
    {selected && (
      <div
        className="absolute top-2 right-2 w-6 h-6 rounded-full grid place-items-center"
        style={{ background: team.primary_color }}
      >
        <Check className="w-4 h-4 text-white" strokeWidth={3} />
      </div>
    )}
    <div className="flex items-center gap-3">
      <PlayerAvatar player={player} team={team} size={56} />
      <div className="flex-1 min-w-0">
        <div className="font-heading text-sm uppercase tracking-wide truncate">
          {player.name}
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-1">
          <span
            className={`text-[9px] px-1.5 py-0.5 rounded border tracking-widest uppercase ${ROLE_BADGE[player.role] || "bg-white/5 text-white/60 border-white/10"
              }`}
          >
            {player.role}
          </span>
          <span className="text-[9px] text-white/40 font-mono uppercase">
            {player.country}
          </span>
        </div>
      </div>
    </div>
    <div className="mt-3 grid grid-cols-2 gap-1 text-[10px] font-mono text-white/55">
      <span>{player.batting_avg > 0 ? `BAT ${player.batting_avg.toFixed(1)}` : "BAT —"}</span>
      <span>{player.strike_rate > 0 ? `SR ${player.strike_rate.toFixed(0)}` : "SR —"}</span>
      <span>{player.wickets > 0 ? `WKT ${player.wickets}` : "WKT —"}</span>
      <span>{player.economy > 0 ? `ECN ${player.economy.toFixed(1)}` : "ECN —"}</span>
    </div>
  </button>
);

const TeamPanel = ({ team, players, selected, onToggle }) => {
  const max = 11;
  const full = selected.size >= max;
  return (
    <div className="rounded-xl glass p-4 sm:p-6 grain relative overflow-hidden">
      <div
        className="absolute -top-10 -right-10 w-44 h-44 rounded-full blur-3xl opacity-30"
        style={{ background: team.primary_color }}
      />
      <div className="relative flex items-center gap-3 mb-5">
        <TeamLogo team={team} size={48} />
        <div className="flex-1">
          <h3 className="font-heading text-lg uppercase tracking-wider truncate">
            {team.name}
          </h3>
          <span className="text-[10px] tracking-[0.3em] uppercase text-white/40">
            Squad · pick 11
          </span>
        </div>
        <div
          className="font-heading text-lg px-3 py-1.5 rounded-md tabular"
          style={{ background: `${team.primary_color}33`, color: team.secondary_color }}
          data-testid={`xi-count-${team.id}`}
        >
          {selected.size}/{max}
        </div>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {players.map((p) => (
          <PlayerCard
            key={p.name}
            player={p}
            team={team}
            selected={selected.has(p.name)}
            onToggle={onToggle}
            disabled={full}
          />
        ))}
      </div>
    </div>
  );
};

export const PlayerPicker = ({
  teamA,
  teamB,
  selectedA,
  selectedB,
  playerImages,
  onChangeA,
  onChangeB,
  onSourceChange,
  onBack,
  onNext,
}) => {
  const results = useQueries({
    queries: [playersQuery(teamA.id), playersQuery(teamB.id)],
  });
  const [resA, resB] = results;
  const loading = resA.isLoading || resB.isLoading;

  const playersA = (resA.data?.data ?? []).map((p) => ({
    ...p,
    imageId: playerImages[p.name] || p.image_id,
  }));
  const playersB = (resB.data?.data ?? []).map((p) => ({
    ...p,
    imageId: playerImages[p.name] || p.image_id,
  }));

  useEffect(() => {
    if (!onSourceChange) return;
    const sources = [resA.data?.source, resB.data?.source].filter(Boolean);
    if (sources.length < 2) return;
    const merged = sources.includes("fallback")
      ? "fallback"
      : sources.includes("cache")
        ? "cache"
        : "live";
    onSourceChange(merged);
  }, [resA.data, resB.data, onSourceChange]);

  const toggle = (set, setter) => (player) => {
    const next = new Set(set);
    if (next.has(player.name)) next.delete(player.name);
    else if (next.size < 11) next.add(player.name);
    setter(next);
  };

  const autoFillA = () =>
    onChangeA(new Set(playersA.slice(0, 11).map((p) => p.name)));
  const autoFillB = () =>
    onChangeB(new Set(playersB.slice(0, 11).map((p) => p.name)));

  const ready = selectedA.size === 11 && selectedB.size === 11;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-32 text-white/60">
        <Loader2 className="w-6 h-6 animate-spin mr-2" /> Loading squads…
      </div>
    );
  }

  return (
    <section className="relative max-w-7xl mx-auto px-6 sm:px-8 py-10 sm:py-14">
      <div className="text-center mb-10">
        <span className="text-[10px] tracking-[0.4em] uppercase text-[#FF3B30]">
          Step 02
        </span>
        <h1 className="mt-3 font-heading text-5xl sm:text-6xl tracking-tighter uppercase">
          Pick the <span className="text-[#FF3B30]">XI</span>
        </h1>
        <p className="mt-3 text-white/60 max-w-2xl mx-auto">
          Tap players to lock in 11 per side. Tap again to deselect.
        </p>
        <div className="mt-5 flex justify-center gap-3">
          <button
            data-testid="autofill-a-btn"
            onClick={autoFillA}
            className="text-xs font-heading tracking-widest uppercase px-4 py-2 rounded-md border border-white/15 hover:bg-white/5"
          >
            Auto-fill {teamA.short_name}
          </button>
          <button
            data-testid="autofill-b-btn"
            onClick={autoFillB}
            className="text-xs font-heading tracking-widest uppercase px-4 py-2 rounded-md border border-white/15 hover:bg-white/5"
          >
            Auto-fill {teamB.short_name}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 stagger">
        <TeamPanel
          team={teamA}
          players={playersA}
          selected={selectedA}
          onToggle={toggle(selectedA, onChangeA)}
        />
        <TeamPanel
          team={teamB}
          players={playersB}
          selected={selectedB}
          onToggle={toggle(selectedB, onChangeB)}
        />
      </div>

      <div className="mt-10 flex flex-wrap items-center justify-between gap-3">
        <button
          onClick={onBack}
          data-testid="step2-back-btn"
          className="font-heading uppercase tracking-[0.25em] text-xs px-6 py-3 rounded-md border border-white/15 hover:bg-white/5"
        >
          ← Teams
        </button>
        <button
          disabled={!ready}
          onClick={onNext}
          data-testid="step2-next-btn"
          className="bg-[#FF3B30] disabled:bg-white/5 disabled:text-white/30 disabled:cursor-not-allowed text-white font-heading uppercase tracking-[0.25em] text-sm px-10 py-4 rounded-md hover:bg-[#FF645A] transition-all shadow-[0_8px_32px_rgba(255,59,48,0.25)]"
        >
          Set Conditions →
        </button>
      </div>
    </section>
  );
};

export default PlayerPicker;
