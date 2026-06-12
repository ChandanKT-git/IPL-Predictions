import React, { useEffect, useMemo, useRef, useState } from "react";
import { fetchAnalysis, whatIfPredict } from "../lib/api";
import { TeamLogo } from "./TeamLogo";
import { AnimatedCounter } from "./AnimatedCounter";
import { Slider } from "../components/ui/slider";
import { WhyPanel } from "./WhyPanel";
import useLiveScoreStream from "../hooks/useLiveScoreStream";
import { toast } from "sonner";
import {
  Sparkles,
  RefreshCcw,
  ArrowLeft,
  Activity,
  TrendingUp,
  Loader2,
  Radio,
  Share2,
  Target,
} from "lucide-react";

const LiveScoreTicker = ({ matchId }) => {
  const { score, status } = useLiveScoreStream(matchId);

  if (!matchId || !score) return null;

  return (
    <div className="flex items-center gap-3 px-4 py-2 bg-[#FF3B30]/10 border border-[#FF3B30]/20 rounded-full animate-fade-in">
      <Radio
        className={`w-3 h-3 text-[#FF3B30] ${status === "open" ? "animate-pulse" : "opacity-50"}`}
      />
      <span className="text-[10px] font-heading uppercase tracking-widest text-[#FF3B30]">
        {status === "open" ? "Live Score" : "Last Known"}
      </span>
      <div className="flex items-center gap-2 text-xs font-mono">
        <span>{score.batTeamScore}</span>
        <span className="text-white/20">|</span>
        <span className="text-white/60">{score.status}</span>
      </div>
    </div>
  );
};

const StatCard = ({ label, value, suffix, decimals = 0, accent, testid, sublabel }) => (
  <div
    className="rounded-xl glass p-5 grain card-lift"
    style={{ borderTop: `2px solid ${accent || "rgba(255,255,255,0.15)"}` }}
    data-testid={testid}
  >
    <div className="text-[10px] tracking-[0.3em] uppercase text-white/45">
      {label}
    </div>
    <div className="mt-3 font-heading text-5xl tracking-tighter">
      <AnimatedCounter
        value={value || 0}
        decimals={decimals}
        suffix={suffix || ""}
      />
    </div>
    {sublabel && (
      <div className="mt-1 text-[10px] font-mono text-white/40">{sublabel}</div>
    )}
  </div>
);

const ProbabilityBar = ({ teamA, teamB, probA }) => (
  <div data-testid="prob-bar">
    <div className="flex items-center justify-between text-[10px] tracking-[0.3em] uppercase text-white/40">
      <span>{teamA.short_name}</span>
      <span>Win Probability</span>
      <span>{teamB.short_name}</span>
    </div>
    <div className="mt-3 h-3 rounded-full overflow-hidden bg-white/5 border border-white/10 flex">
      <div
        className="h-full transition-all duration-1000 ease-out"
        style={{ width: `${probA}%`, background: teamA.primary_color }}
      />
      <div
        className="h-full transition-all duration-1000 ease-out"
        style={{ width: `${100 - probA}%`, background: teamB.primary_color }}
      />
    </div>
    <div className="mt-2 flex items-center justify-between font-heading text-2xl tabular">
      <span style={{ color: teamA.primary_color }}>{probA}%</span>
      <span style={{ color: teamB.primary_color }}>{100 - probA}%</span>
    </div>
  </div>
);

const PhaseBar = ({ label, value, total, color }) => {
  const pct = Math.round((value / Math.max(1, total)) * 100);
  return (
    <div>
      <div className="flex items-center justify-between text-[10px] tracking-[0.3em] uppercase text-white/40">
        <span>{label}</span>
        <span className="font-mono text-white/70">{value} runs</span>
      </div>
      <div className="mt-2 h-2 rounded-full bg-white/5 overflow-hidden">
        <div
          className="h-full transition-all duration-1000 ease-out"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
    </div>
  );
};

const MatchupTable = ({ matchups }) => {
  if (!matchups || matchups.length === 0) return null;
  return (
    <div className="rounded-xl glass p-6 grain mt-6">
      <div className="flex items-center gap-2 text-[10px] tracking-[0.3em] uppercase text-white/45 mb-4">
        <Target className="w-3 h-3 text-[#FF3B30]" /> Key Batter–Bowler Matchups
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-[10px] uppercase tracking-widest text-white/40">
            <tr>
              <th className="text-left py-2">Batter</th>
              <th className="text-left py-2">Bowler</th>
              <th className="text-right py-2">Balls</th>
              <th className="text-right py-2">Runs</th>
              <th className="text-right py-2">Wkts</th>
              <th className="text-right py-2">SR</th>
            </tr>
          </thead>
          <tbody className="font-mono text-white/80">
            {matchups.map((m, i) => (
              <tr key={i} className="border-t border-white/5">
                <td className="py-2">{m.batter}</td>
                <td className="py-2">{m.bowler}</td>
                <td className="py-2 text-right">{m.balls}</td>
                <td className="py-2 text-right">{m.runs}</td>
                <td className="py-2 text-right">{m.dismissals}</td>
                <td className="py-2 text-right">{m.strike_rate}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

const SliderRow = ({ label, value, max, step, onChange, hint, testid }) => (
  <div data-testid={testid}>
    <div className="flex items-center justify-between text-[10px] tracking-[0.3em] uppercase text-white/45">
      <span>{label}</span>
      <span className="font-mono text-white/70 normal-case tracking-normal">
        {hint}
      </span>
    </div>
    <div className="mt-3 flex items-center gap-4">
      <Slider
        value={[value]}
        max={max}
        step={step}
        onValueChange={(v) => onChange(Number(v[0]))}
        className="flex-1"
      />
      <span className="font-heading text-3xl tabular w-16 text-right">{value}</span>
    </div>
  </div>
);

export const PredictionResult = ({
  teamA,
  teamB,
  conditions,
  prediction,
  venueName,
  pitchLabel,
  weatherLabel,
  liveMatchId,
  onReset,
  onBack,
}) => {
  const battingTeam = conditions.batting_team === teamA.id ? teamA : teamB;
  const bowlingTeam = battingTeam.id === teamA.id ? teamB : teamA;

  const [analysis, setAnalysis] = useState({ text: "", loading: true, source: "" });
  const [whatIf, setWhatIf] = useState(null);
  const [whatIfLoading, setWhatIfLoading] = useState(false);
  const [overs, setOvers] = useState(0);
  const [wickets, setWickets] = useState(0);
  const [runs, setRuns] = useState(0);
  const userTouchedRunsRef = useRef(false);
  const { score: liveStreamScore } = useLiveScoreStream(liveMatchId);

  useEffect(() => {
    if (!liveStreamScore) return;
    setOvers(liveStreamScore.overs || 0);
    setWickets(liveStreamScore.wickets || 0);
    setRuns(liveStreamScore.runs || 0);
    userTouchedRunsRef.current = true;
  }, [liveStreamScore]);

  useEffect(() => {
    let active = true;
    setAnalysis((a) => ({ ...a, loading: true }));
    fetchAnalysis({
      team_a_name: teamA.name,
      team_b_name: teamB.name,
      batting_team_name: battingTeam.name,
      venue_name: venueName,
      pitch_label: pitchLabel,
      weather_label: weatherLabel,
      predicted_score: prediction.predicted_score,
      win_prob_batting: prediction.win_probability_batting,
    })
      .then((r) => active && setAnalysis({ text: r.analysis, loading: false, source: r.source }))
      .catch(
        () =>
          active &&
          setAnalysis({
            text: "Match preview unavailable — but the model is locked in on the projection.",
            loading: false,
            source: "error",
          }),
      );
    return () => {
      active = false;
    };
  }, [teamA, teamB, battingTeam, venueName, pitchLabel, weatherLabel, prediction]);

  useEffect(() => {
    if (overs === 0 && runs === 0 && wickets === 0) {
      setWhatIf(null);
      return undefined;
    }
    const t = setTimeout(() => {
      setWhatIfLoading(true);
      whatIfPredict({
        base_prediction: prediction,
        current_overs: overs,
        current_wickets: wickets,
        current_runs: runs,
        pitch: conditions.pitch,
        weather: conditions.weather,
        batting_team_rating: prediction.batting_team_strength || 80,
      })
        .then(setWhatIf)
        .finally(() => setWhatIfLoading(false));
    }, 200);
    return () => clearTimeout(t);
  }, [overs, wickets, runs, prediction, conditions.pitch, conditions.weather]);

  useEffect(() => {
    if (overs > 0 && !userTouchedRunsRef.current && runs === 0) {
      const baselinePerOver = prediction.predicted_score / 20;
      setRuns(Math.max(0, Math.round(baselinePerOver * overs)));
    }
  }, [overs, prediction.predicted_score, runs]);

  const projected = whatIf ? whatIf.projected_score : prediction.predicted_score;
  const probBatting = whatIf
    ? whatIf.win_probability_batting
    : prediction.win_probability_batting;
  const probA = battingTeam.id === teamA.id ? probBatting : 100 - probBatting;

  const phase = prediction.phase_breakdown || {
    powerplay_runs: 0,
    middle_overs_runs: 0,
    death_overs_runs: 0,
  };

  const accent = battingTeam.primary_color;
  const h2h = prediction.h2h;
  const matchups = prediction.matchups;

  const summaryCards = useMemo(
    () => [
      {
        label: "Projected Score",
        value: projected,
        accent,
        testid: "stat-score",
        sublabel: prediction.score_range_low
          ? `Range ${prediction.score_range_low}–${prediction.score_range_high}`
          : null,
      },
      {
        label: "Run Rate",
        value: prediction.expected_run_rate,
        decimals: 2,
        accent: bowlingTeam.primary_color,
        testid: "stat-rr",
      },
      {
        label: "Win Prob (Bat)",
        value: probBatting,
        suffix: "%",
        accent: "#10B981",
        testid: "stat-prob",
      },
      {
        label: "Upper P90",
        value: prediction.score_range_high,
        accent: "#F59E0B",
        testid: "stat-range",
      },
    ],
    [projected, prediction, probBatting, accent, bowlingTeam.primary_color],
  );

  const handleShare = () => {
    if (!prediction.id) {
      toast.error("Prediction ID missing");
      return;
    }
    const url = `${window.location.origin}/share/${prediction.id}`;
    navigator.clipboard.writeText(url);
    toast.success("Shareable link copied to clipboard.");
  };

  return (
    <section className="relative max-w-7xl mx-auto px-6 sm:px-8 py-10 sm:py-14">
      <div className="mb-6 flex justify-end">
        <button
          onClick={handleShare}
          className="flex items-center gap-2 px-4 py-2 rounded-full bg-[#FF3B30]/10 border border-[#FF3B30]/30 text-[#FF3B30] hover:bg-[#FF3B30]/20 transition-all text-xs font-heading uppercase tracking-widest"
        >
          <Share2 className="w-3 h-3" /> Share Prediction
        </button>
      </div>

      <div className="rounded-2xl overflow-hidden relative grain glass p-6 sm:p-10">
        <div
          className="absolute inset-0 opacity-30 blur-3xl"
          style={{
            background: `radial-gradient(circle at 20% 50%, ${teamA.primary_color}, transparent 50%), radial-gradient(circle at 80% 50%, ${teamB.primary_color}, transparent 50%)`,
          }}
        />
        <div className="relative grid grid-cols-3 items-center gap-4">
          <div className="flex items-center gap-4">
            <TeamLogo team={teamA} size={84} />
            <div className="hidden sm:block">
              <div className="text-[10px] tracking-[0.3em] uppercase text-white/40">
                Team A
              </div>
              <div className="font-heading text-2xl uppercase tracking-wider">
                {teamA.short_name}
              </div>
            </div>
          </div>
          <div className="text-center">
            <LiveScoreTicker matchId={liveMatchId} />
            <div className="text-[10px] tracking-[0.4em] uppercase text-white/40 mt-3">
              Match Preview
            </div>
            <div className="font-heading text-5xl sm:text-6xl tracking-tighter mt-1">
              VS
            </div>
            <div className="text-xs text-white/55 mt-1">
              {venueName} · {pitchLabel}
            </div>
          </div>
          <div className="flex items-center gap-4 justify-end">
            <div className="hidden sm:block text-right">
              <div className="text-[10px] tracking-[0.3em] uppercase text-white/40">
                Team B
              </div>
              <div className="font-heading text-2xl uppercase tracking-wider">
                {teamB.short_name}
              </div>
            </div>
            <TeamLogo team={teamB} size={84} />
          </div>
        </div>
      </div>

      <div className="mt-6 grid grid-cols-2 lg:grid-cols-4 gap-4 stagger">
        {summaryCards.map((c) => (
          <StatCard key={c.label} {...c} />
        ))}
      </div>

      <div className="mt-6 grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 rounded-xl glass p-6 sm:p-8 grain">
          <ProbabilityBar teamA={teamA} teamB={teamB} probA={probA} />

          {h2h && h2h.total_matches > 0 && (
            <div className="mt-8 rounded-2xl bg-white/5 p-6 border-l-4 border-[#FF3B30]">
              <div className="flex items-center gap-3 mb-6">
                <Activity className="w-5 h-5 text-[#FF3B30]" />
                <h3 className="font-heading text-xl uppercase tracking-tight">
                  Real Historical Insights
                </h3>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
                <div className="space-y-1">
                  <div className="text-[10px] tracking-widest uppercase text-white/40">
                    Total Encounters
                  </div>
                  <div className="text-3xl font-heading">{h2h.total_matches}</div>
                </div>
                <div className="space-y-1">
                  <div className="text-[10px] tracking-widest uppercase text-white/40">
                    Matchup Average
                  </div>
                  <div className="text-3xl font-heading">
                    {h2h.avg_score?.toFixed(1)}{" "}
                    <span className="text-xs text-white/40 font-mono uppercase tracking-normal">
                      runs
                    </span>
                  </div>
                </div>
                <div className="space-y-4">
                  <div className="text-[10px] tracking-widest uppercase text-white/40">
                    Recent History
                  </div>
                  <div className="flex gap-2">
                    {(h2h.last_5 || []).slice(0, 5).map((m, i) => {
                      const isA = m.winner === teamA.id;
                      return (
                        <div
                          key={i}
                          className={`w-8 h-8 rounded-lg flex items-center justify-center text-[10px] font-bold border ${isA
                            ? "bg-blue-500/20 border-blue-500/40 text-blue-400"
                            : "bg-orange-500/20 border-orange-500/40 text-orange-400"
                            }`}
                          title={`Winner: ${m.winner} (${m.year})`}
                        >
                          {isA ? teamA.short_name[0] : teamB.short_name[0]}
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
              {h2h.venue_record && (
                <div className="mt-6 pt-4 border-t border-white/10 text-xs text-white/60">
                  <span className="font-heading uppercase tracking-widest text-white/40">
                    {venueName} record:
                  </span>{" "}
                  {h2h.venue_record.matches} matches · {teamA.short_name}{" "}
                  {h2h.venue_record.team_a_wins} – {h2h.venue_record.team_b_wins}{" "}
                  {teamB.short_name} · avg {h2h.venue_record.avg_score} runs
                </div>
              )}
            </div>
          )}

          <div className="mt-6 grid grid-cols-1 sm:grid-cols-3 gap-4">
            <PhaseBar
              label="Powerplay (1-6)"
              value={phase.powerplay_runs}
              total={prediction.predicted_score}
              color={teamA.primary_color}
            />
            <PhaseBar
              label="Middle (7-15)"
              value={phase.middle_overs_runs}
              total={prediction.predicted_score}
              color="#F59E0B"
            />
            <PhaseBar
              label="Death (16-20)"
              value={phase.death_overs_runs}
              total={prediction.predicted_score}
              color="#FF3B30"
            />
          </div>
          <div
            className="mt-6 p-4 rounded-md bg-white/5 border border-white/10 font-heading text-sm uppercase tracking-widest"
            data-testid="match-outcome"
          >
            <span className="text-[#FF3B30] mr-2">▶</span>
            {prediction.match_outcome}
          </div>
          <div className="mt-3 text-[10px] font-mono text-white/30 text-right">
            model {prediction.model_version}
          </div>
        </div>

        <div className="rounded-xl glass p-6 sm:p-8 grain relative overflow-hidden">
          <div className="flex items-center gap-2 text-[10px] tracking-[0.3em] uppercase text-white/45">
            <Sparkles className="w-3 h-3 text-[#FF3B30]" />
            AI Match Preview
            {analysis.source === "fallback" && (
              <span className="ml-auto text-[9px] text-white/30">offline mode</span>
            )}
          </div>
          <div
            className="mt-4 text-sm leading-relaxed text-white/85 min-h-[140px]"
            data-testid="ai-analysis"
          >
            {analysis.loading ? (
              <span className="flex items-center gap-2 text-white/50">
                <Loader2 className="w-4 h-4 animate-spin" /> Drafting commentary…
              </span>
            ) : (
              analysis.text
            )}
          </div>
        </div>
      </div>

      <MatchupTable matchups={matchups} />

      <WhyPanel contributions={prediction.contributions} />

      <div className="mt-6 rounded-xl glass p-6 sm:p-8 grain">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-[10px] tracking-[0.3em] uppercase text-white/45">
              <Activity className="w-3 h-3 text-[#FF3B30]" /> Live What-If
            </div>
            <h3 className="mt-1 font-heading text-2xl uppercase tracking-tight">
              Simulate live match state
            </h3>
          </div>
          <div className="flex items-center gap-2 text-xs text-white/50">
            <TrendingUp className="w-4 h-4" />
            Slide to project {battingTeam.short_name}'s finish
          </div>
        </div>

        <div className="mt-6 grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-6">
            <SliderRow
              label="Overs Bowled"
              value={overs}
              max={20}
              step={0.5}
              onChange={setOvers}
              testid="slider-overs"
              hint={`${(20 - overs).toFixed(1)} overs left`}
            />
            <SliderRow
              label="Wickets Lost"
              value={wickets}
              max={10}
              step={1}
              onChange={setWickets}
              testid="slider-wickets"
              hint={`${10 - wickets} in hand`}
            />
            <SliderRow
              label="Runs Scored"
              value={runs}
              max={260}
              step={1}
              onChange={(v) => {
                userTouchedRunsRef.current = true;
                setRuns(v);
              }}
              testid="slider-runs"
              hint={overs > 0 ? `CRR ${(runs / overs).toFixed(2)}` : "Set overs first"}
            />
          </div>

          <div className="rounded-xl bg-[#0F0F0F] border border-white/10 p-5">
            <div className="text-[10px] tracking-[0.3em] uppercase text-white/40">
              Live Projection
            </div>
            <div
              className="mt-3 font-heading text-6xl tabular leading-none"
              style={{ color: accent }}
              data-testid="live-projection"
            >
              <AnimatedCounter value={projected} />
            </div>
            <div className="mt-3 text-xs text-white/55 font-mono">
              {whatIf ? (
                <>
                  RRR {whatIf.required_run_rate} · CRR {whatIf.current_run_rate}
                </>
              ) : (
                <>Match has not started — using base projection</>
              )}
            </div>
            <div className="mt-5 h-px bg-white/10" />
            <div className="mt-4 text-[10px] tracking-[0.3em] uppercase text-white/40">
              Updated Win Prob
            </div>
            <div className="mt-2 grid grid-cols-2 gap-2 font-heading text-2xl">
              <div
                className="rounded-md p-3 text-center"
                style={{ background: `${battingTeam.primary_color}22`, color: battingTeam.primary_color }}
              >
                {battingTeam.short_name} <br />
                <span className="text-3xl tabular">
                  <AnimatedCounter value={probBatting} suffix="%" />
                </span>
              </div>
              <div
                className="rounded-md p-3 text-center"
                style={{ background: `${bowlingTeam.primary_color}22`, color: bowlingTeam.primary_color }}
              >
                {bowlingTeam.short_name} <br />
                <span className="text-3xl tabular">
                  <AnimatedCounter value={100 - probBatting} suffix="%" />
                </span>
              </div>
            </div>
            {whatIfLoading && (
              <div className="mt-3 text-[10px] text-white/40 flex items-center gap-1">
                <Loader2 className="w-3 h-3 animate-spin" /> recomputing…
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="mt-10 flex flex-wrap items-center justify-between gap-3">
        <button
          onClick={onBack}
          data-testid="result-back-btn"
          className="font-heading uppercase tracking-[0.25em] text-xs px-6 py-3 rounded-md border border-white/15 hover:bg-white/5 flex items-center gap-2"
        >
          <ArrowLeft className="w-3 h-3" /> Edit Conditions
        </button>
        <button
          onClick={onReset}
          data-testid="result-reset-btn"
          className="font-heading uppercase tracking-[0.25em] text-xs px-6 py-3 rounded-md bg-white/5 hover:bg-white/10 flex items-center gap-2"
        >
          <RefreshCcw className="w-3 h-3" /> New Match
        </button>
      </div>
    </section>
  );
};

export default PredictionResult;
