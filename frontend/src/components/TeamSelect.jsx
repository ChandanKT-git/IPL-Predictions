import React from "react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";
import { TeamLogo } from "./TeamLogo";
import { LiveMatchPicker } from "./LiveMatchPicker";
import { Trophy, Users } from "lucide-react";

const TeamCard = ({ team, label, side, onSelect, allTeams }) => (
  <div
    className="relative p-6 sm:p-8 rounded-xl card-lift glass overflow-hidden grain"
    style={{
      borderTop: `2px solid ${team ? team.primary_color : "rgba(255,255,255,0.1)"}`,
    }}
    data-testid={`team-card-${side}`}
  >
    {team && (
      <div
        className="absolute -top-24 -right-24 w-72 h-72 rounded-full opacity-25 blur-3xl"
        style={{ background: team.primary_color }}
      />
    )}
    <div className="relative">
      <div className="flex items-center justify-between">
        <span className="text-[10px] tracking-[0.3em] uppercase text-white/40">
          {label}
        </span>
        <span className="text-[10px] tracking-[0.3em] uppercase text-white/30">
          {side === "a" ? "Home" : "Away"}
        </span>
      </div>

      <div className="mt-6 flex items-center gap-5">
        {team ? (
          <TeamLogo team={team} size={88} />
        ) : (
          <div className="w-[88px] h-[88px] rounded-full border-2 border-dashed border-white/15 grid place-items-center">
            <Users className="w-7 h-7 text-white/25" />
          </div>
        )}
        <div className="flex-1 min-w-0">
          <h3 className="font-heading text-2xl sm:text-3xl uppercase leading-tight truncate">
            {team ? team.name : "Pick a Team"}
          </h3>
          {team && (
            <div className="mt-2 flex items-center gap-3 text-xs text-white/60">
              <span className="flex items-center gap-1">
                <Trophy className="w-3 h-3" /> {team.titles} titles
              </span>
              <span className="font-mono">RAT {team.rating}</span>
              <span className="hidden sm:inline">• {team.captain}</span>
            </div>
          )}
        </div>
      </div>

      <div className="mt-6">
        <Select
          value={team?.id || ""}
          onValueChange={(val) => onSelect(allTeams.find((t) => t.id === val))}
        >
          <SelectTrigger
            data-testid={`team-select-${side}`}
            className="bg-[#141414] border-white/10 h-12 font-heading uppercase tracking-widest text-sm"
          >
            <SelectValue placeholder="Select team" />
          </SelectTrigger>
          <SelectContent className="bg-[#0A0A0A] border-white/10">
            {allTeams.map((t) => (
              <SelectItem key={t.id} value={t.id} data-testid={`team-option-${side}-${t.id}`}>
                <div className="flex items-center gap-2">
                  <span
                    className="w-2.5 h-2.5 rounded-full"
                    style={{ background: t.primary_color }}
                  />
                  <span className="font-heading uppercase tracking-wide">
                    {t.short_name}
                  </span>
                  <span className="text-white/50 text-xs">{t.name}</span>
                </div>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  </div>
);

export const TeamSelect = ({ teams, teamA, teamB, onChangeA, onChangeB, onLiveMatchSelect, onNext }) => {
  const ready = teamA && teamB && teamA.id !== teamB.id;
  const teamsA = teams.filter((t) => !teamB || t.id !== teamB.id);
  const teamsB = teams.filter((t) => !teamA || t.id !== teamA.id);

  return (
    <section className="relative max-w-7xl mx-auto px-6 sm:px-8 py-10 sm:py-14">
      <div className="text-center mb-12 stagger">
        <span className="text-[10px] tracking-[0.4em] uppercase text-[#FF3B30]">
          Step 01
        </span>
        <h1 className="mt-3 font-heading text-5xl sm:text-6xl tracking-tighter uppercase">
          Set the <span className="text-[#FF3B30]">Battle</span>
        </h1>
        <p className="mt-3 text-white/60 max-w-2xl mx-auto">
          Pick the two IPL franchises stepping onto the pitch tonight.
        </p>
      </div>

      <LiveMatchPicker onSelectMatch={onLiveMatchSelect} />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 sm:gap-8 stagger">
        <TeamCard
          team={teamA}
          allTeams={teamsA}
          side="a"
          label="Team Alpha"
          onSelect={onChangeA}
        />
        <TeamCard
          team={teamB}
          allTeams={teamsB}
          side="b"
          label="Team Bravo"
          onSelect={onChangeB}
        />
      </div>

      {teamA && teamB && (
        <div className="mt-10 flex items-center justify-center gap-6 animate-fade-up">
          <span className="font-heading text-2xl text-white/70">
            {teamA.short_name}
          </span>
          <span
            className="font-heading text-3xl tracking-widest text-white/40"
            aria-hidden
          >
            VS
          </span>
          <span className="font-heading text-2xl text-white/70">
            {teamB.short_name}
          </span>
        </div>
      )}

      <div className="mt-10 flex justify-center">
        <button
          onClick={onNext}
          disabled={!ready}
          data-testid="step1-next-btn"
          className="bg-[#FF3B30] disabled:bg-white/5 disabled:text-white/30 disabled:cursor-not-allowed text-white font-heading uppercase tracking-[0.25em] text-sm px-10 py-4 rounded-md hover:bg-[#FF645A] transition-all shadow-[0_8px_32px_rgba(255,59,48,0.25)]"
        >
          Pick Playing XI →
        </button>
      </div>
    </section>
  );
};

export default TeamSelect;
