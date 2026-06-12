import React from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";
import { TeamLogo } from "./TeamLogo";
import { FormGuide, H2HStats } from "./FormGuide";
import { CloudSun, MapPin, Coins, Loader2, Info } from "lucide-react";
import {
  venuesQuery,
  pitchTypesQuery,
  weatherTypesQuery,
  h2hQuery,
} from "../lib/queries";

const Field = ({ label, icon, children, testid }) => (
  <div className="space-y-2" data-testid={testid}>
    <label className="text-[10px] tracking-[0.3em] uppercase text-white/45 flex items-center gap-2">
      {icon}
      {label}
    </label>
    {children}
  </div>
);

const TeamPickButton = ({ team, active, onClick, testid }) => (
  <button
    onClick={onClick}
    data-testid={testid}
    className={`flex items-center gap-3 p-3 rounded-md border w-full transition-all ${active
        ? "bg-[#1A1A1A] border-2"
        : "bg-[#141414] border-white/10 hover:border-white/25"
      }`}
    style={active ? { borderColor: team.primary_color } : undefined}
  >
    <TeamLogo team={team} size={36} />
    <div className="text-left">
      <div className="font-heading text-sm uppercase tracking-wider">
        {team.short_name}
      </div>
      <div className="text-[10px] text-white/50 truncate">{team.name}</div>
    </div>
  </button>
);

export const MatchConditions = ({
  teamA,
  teamB,
  conditions,
  onChange,
  onBack,
  onPredict,
  predicting,
}) => {
  const venuesQ = useQuery(venuesQuery());
  const pitchesQ = useQuery(pitchTypesQuery());
  const weathersQ = useQuery(weatherTypesQuery());
  const h2hQ = useQuery(h2hQuery(teamA.id, teamB.id));

  const venues = venuesQ.data?.data ?? [];
  const pitches = pitchesQ.data ?? [];
  const weathers = weathersQ.data ?? [];

  const set = (k, v) => onChange({ ...conditions, [k]: v });
  const ready =
    conditions.venue &&
    conditions.pitch &&
    conditions.weather &&
    conditions.toss_winner &&
    conditions.batting_team;

  if (venuesQ.isLoading || pitchesQ.isLoading || weathersQ.isLoading) {
    return (
      <div className="flex items-center justify-center py-32 text-white/60">
        <Loader2 className="w-6 h-6 animate-spin mr-2" /> Loading conditions…
      </div>
    );
  }

  return (
    <section className="relative max-w-5xl mx-auto px-6 sm:px-8 py-10 sm:py-14">
      <div className="text-center mb-10 stagger">
        <span className="text-[10px] tracking-[0.4em] uppercase text-[#FF3B30]">
          Step 03
        </span>
        <h1 className="mt-3 font-heading text-5xl sm:text-6xl tracking-tighter uppercase">
          Match <span className="text-[#FF3B30]">Conditions</span>
        </h1>
        <p className="mt-3 text-white/60">
          The pitch report decides the personality of the night.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 items-start">
        <div className="lg:col-span-2 rounded-xl glass p-6 sm:p-8 grid grid-cols-1 md:grid-cols-2 gap-6 stagger">
          <Field
            testid="field-venue"
            label="Venue"
            icon={<MapPin className="w-3 h-3" />}
          >
            <Select value={conditions.venue || ""} onValueChange={(v) => set("venue", v)}>
              <SelectTrigger
                data-testid="venue-select"
                className="bg-[#141414] border-white/10 h-12"
              >
                <SelectValue placeholder="Choose stadium" />
              </SelectTrigger>
              <SelectContent className="bg-[#0A0A0A] border-white/10">
                {venues.map((v) => (
                  <SelectItem key={v.id} value={v.id} data-testid={`venue-option-${v.id}`}>
                    <span className="font-heading uppercase tracking-wider">{v.name}</span>
                    <span className="text-white/40 text-xs ml-2">{v.city}</span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>

          <Field
            testid="field-pitch"
            label="Pitch Type"
            icon={<span className="text-[10px]">◐</span>}
          >
            <Select value={conditions.pitch || ""} onValueChange={(v) => set("pitch", v)}>
              <SelectTrigger
                data-testid="pitch-select"
                className="bg-[#141414] border-white/10 h-12"
              >
                <SelectValue placeholder="Pitch behaviour" />
              </SelectTrigger>
              <SelectContent className="bg-[#0A0A0A] border-white/10">
                {pitches.map((p) => (
                  <SelectItem key={p.id} value={p.id} data-testid={`pitch-option-${p.id}`}>
                    {p.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>

          <Field
            testid="field-weather"
            label="Weather"
            icon={<CloudSun className="w-3 h-3" />}
          >
            <Select value={conditions.weather || ""} onValueChange={(v) => set("weather", v)}>
              <SelectTrigger
                data-testid="weather-select"
                className="bg-[#141414] border-white/10 h-12"
              >
                <SelectValue placeholder="Weather conditions" />
              </SelectTrigger>
              <SelectContent className="bg-[#0A0A0A] border-white/10">
                {weathers.map((w) => (
                  <SelectItem key={w.id} value={w.id} data-testid={`weather-option-${w.id}`}>
                    {w.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>

          <Field
            testid="field-toss"
            label="Toss Winner"
            icon={<Coins className="w-3 h-3" />}
          >
            <div className="grid grid-cols-2 gap-3">
              <TeamPickButton
                team={teamA}
                active={conditions.toss_winner === teamA.id}
                onClick={() => set("toss_winner", teamA.id)}
                testid="toss-a-btn"
              />
              <TeamPickButton
                team={teamB}
                active={conditions.toss_winner === teamB.id}
                onClick={() => set("toss_winner", teamB.id)}
                testid="toss-b-btn"
              />
            </div>
          </Field>

          <div className="md:col-span-2">
            <Field
              testid="field-batting"
              label="Batting First"
              icon={<span className="text-[10px]">⚏</span>}
            >
              <div className="grid grid-cols-2 gap-3">
                <TeamPickButton
                  team={teamA}
                  active={conditions.batting_team === teamA.id}
                  onClick={() => set("batting_team", teamA.id)}
                  testid="batting-a-btn"
                />
                <TeamPickButton
                  team={teamB}
                  active={conditions.batting_team === teamB.id}
                  onClick={() => set("batting_team", teamB.id)}
                  testid="batting-b-btn"
                />
              </div>
            </Field>
          </div>
        </div>

        <div className="space-y-6 stagger">
          <div className="rounded-xl glass p-6 grain">
            <div className="flex items-center gap-2 text-[10px] tracking-[0.3em] uppercase text-white/45 mb-4">
              <Info className="w-3 h-3 text-[#FF3B30]" />
              Form Guide
            </div>
            <div className="space-y-4">
              <FormGuide
                teamName={teamA.short_name}
                form={h2hQ.data?.form_guide?.[teamA.id]}
              />
              <FormGuide
                teamName={teamB.short_name}
                form={h2hQ.data?.form_guide?.[teamB.id]}
              />
            </div>
          </div>

          <div className="rounded-xl glass p-6 grain">
            <H2HStats data={h2hQ.data} teamA={teamA} teamB={teamB} />
          </div>
        </div>
      </div>

      <div className="mt-10 flex flex-wrap items-center justify-between gap-3">
        <button
          onClick={onBack}
          data-testid="step3-back-btn"
          className="font-heading uppercase tracking-[0.25em] text-xs px-6 py-3 rounded-md border border-white/15 hover:bg-white/5"
        >
          ← Playing XI
        </button>
        <button
          onClick={onPredict}
          disabled={!ready || predicting}
          data-testid="predict-btn"
          className="bg-[#FF3B30] disabled:bg-white/5 disabled:text-white/30 disabled:cursor-not-allowed text-white font-heading uppercase tracking-[0.25em] text-sm px-10 py-4 rounded-md hover:bg-[#FF645A] transition-all shadow-[0_8px_32px_rgba(255,59,48,0.25)] animate-pulse-glow"
        >
          {predicting ? (
            <span className="flex items-center gap-2">
              <Loader2 className="w-4 h-4 animate-spin" /> Crunching numbers…
            </span>
          ) : (
            "Predict Match →"
          )}
        </button>
      </div>
    </section>
  );
};

export default MatchConditions;
