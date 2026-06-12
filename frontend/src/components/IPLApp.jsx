import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Toaster, toast } from "sonner";
import { Loader2 } from "lucide-react";

import {
  teamsQuery,
  venuesQuery,
  pitchTypesQuery,
  weatherTypesQuery,
} from "../lib/queries";
import {
  errorMessage,
  fetchLiveMatchXI,
  fetchPlayers,
  predictMatch,
} from "../lib/api";
import { Header } from "./Header";
import { TeamSelect } from "./TeamSelect";
import { LiveMatchPicker } from "./LiveMatchPicker";
import { PlayerPicker } from "./PlayerPicker";
import { MatchConditions } from "./MatchConditions";
import { PredictionResult } from "./PredictionResult";
import { MatchHistory } from "./MatchHistory";
import ErrorBoundary from "./ErrorBoundary";

const Hero = ({ onStart }) => (
  <section className="isolate overflow-hidden relative">
    <div className="absolute inset-0 stadium-hero -z-10" />
    <div className="absolute inset-0 grain -z-10" />
    <div className="px-6 pt-16 pb-24 mx-auto max-w-7xl sm:px-8 sm:pt-24 sm:pb-32">
      <span className="text-[10px] tracking-[0.4em] uppercase text-[#FF3B30]">
        Cricket Intelligence
      </span>
      <h1 className="mt-4 max-w-4xl text-5xl tracking-tighter uppercase font-heading sm:text-7xl">
        Predict the next IPL <span className="text-[#FF3B30]">storm</span>
      </h1>
      <p className="mt-5 max-w-2xl text-base sm:text-lg text-white/70">
        Build the matchup, lock the playing XI, dial in the pitch &amp; weather.
        The model projects the first innings score, prediction interval and live
        what-if scenarios in real time.
      </p>
      <div className="flex gap-4 items-center mt-8">
        <button
          onClick={onStart}
          data-testid="hero-start-btn"
          className="bg-[#FF3B30] text-white font-heading uppercase tracking-[0.25em] text-sm px-10 py-4 rounded-md hover:bg-[#FF645A] transition-all shadow-[0_8px_32px_rgba(255,59,48,0.4)] animate-pulse-glow"
        >
          Start Predicting →
        </button>
        <span className="font-mono text-xs text-white/50">
          10 teams · 150+ players · live what-if
        </span>
      </div>
    </div>
  </section>
);

const computeOverallSource = ({ teams, venues, players }) => {
  const vals = [teams, venues, players];
  if (vals.some((v) => v === "fallback")) return "fallback";
  if (vals.every((v) => v === "live")) return "live";
  if (vals.every((v) => v === "cache")) return "cache";
  return "mixed";
};

export const IPLApp = () => {
  const [step, setStep] = useState(0);
  const teamsQ = useQuery(teamsQuery());
  const venuesQ = useQuery(venuesQuery());
  const pitchesQ = useQuery(pitchTypesQuery());
  const weathersQ = useQuery(weatherTypesQuery());

  const [teamA, setTeamA] = useState(null);
  const [teamB, setTeamB] = useState(null);
  const [xiA, setXiA] = useState(new Set());
  const [xiB, setXiB] = useState(new Set());
  const [playerImages, setPlayerImages] = useState({});
  const [teamImages, setTeamImages] = useState({});
  const [liveMatchId, setLiveMatchId] = useState(null);
  const [conditions, setConditions] = useState({
    venue: "",
    pitch: "",
    weather: "",
    toss_winner: "",
    batting_team: "",
  });
  const [predicting, setPredicting] = useState(false);
  const [prediction, setPrediction] = useState(null);
  const [playersSource, setPlayersSource] = useState("fallback");

  const teams = teamsQ.data?.data ?? [];
  const venues = venuesQ.data?.data ?? [];
  const pitchTypes = pitchesQ.data ?? [];
  const weatherTypes = weathersQ.data ?? [];

  const overallSource = useMemo(
    () =>
      computeOverallSource({
        teams: teamsQ.data?.source ?? "fallback",
        venues: venuesQ.data?.source ?? "fallback",
        players: playersSource,
      }),
    [teamsQ.data, venuesQ.data, playersSource],
  );

  const handlePlayersSourceChange = useCallback(
    (next) => setPlayersSource((prev) => (prev === next ? prev : next)),
    [],
  );

  useEffect(() => {
    if (teamsQ.error || venuesQ.error || pitchesQ.error || weathersQ.error) {
      toast.error("Failed to load IPL data. Falling back to offline catalog.");
    }
  }, [teamsQ.error, venuesQ.error, pitchesQ.error, weathersQ.error]);

  const handleSelectA = (team) => {
    setTeamA(team);
    setXiA(new Set());
    if (
      conditions.batting_team !== teamB?.id &&
      conditions.batting_team !== team?.id
    ) {
      setConditions((c) => ({ ...c, batting_team: "" }));
    }
  };
  const handleSelectB = (team) => {
    setTeamB(team);
    setXiB(new Set());
  };

  const handleLiveMatchSelect = async (match) => {
    const t1Name = match.matchInfo.team1.teamName;
    const t2Name = match.matchInfo.team2.teamName;
    const foundA = teams.find(
      (t) => t.name.includes(t1Name) || t1Name.includes(t.short_name),
    );
    const foundB = teams.find(
      (t) => t.name.includes(t2Name) || t2Name.includes(t.short_name),
    );
    if (!foundA || !foundB) {
      toast.error("Could not map live teams to internal data.");
      return;
    }

    setTeamA(foundA);
    setTeamB(foundB);
    setLiveMatchId(match.matchInfo.matchId);
    setTeamImages({
      [foundA.id]: match.matchInfo.team1.imageId,
      [foundB.id]: match.matchInfo.team2.imageId,
    });

    toast.promise(fetchLiveMatchXI(match.matchInfo.matchId), {
      loading: "Fetching live Playing XI...",
      success: (data) => {
        const loadSquads = async () => {
          try {
            const [rosterA, rosterB] = await Promise.all([
              fetchPlayers(foundA.id),
              fetchPlayers(foundB.id),
            ]);
            const xiANames = [];
            const xiBNames = [];
            const images = {};
            if (data.scoreCard) {
              const team1SC = data.scoreCard.find(
                (sc) => sc.batTeamDetails.teamId === match.matchInfo.team1.teamId,
              );
              const team2SC = data.scoreCard.find(
                (sc) => sc.batTeamDetails.teamId === match.matchInfo.team2.teamId,
              );
              if (team1SC) {
                Object.values(team1SC.batTeamDetails.playersData).forEach((p) => {
                  xiANames.push(p.shortName);
                  if (p.faceImageId) images[p.shortName] = p.faceImageId;
                });
              }
              if (team2SC) {
                Object.values(team2SC.batTeamDetails.playersData).forEach((p) => {
                  xiBNames.push(p.shortName);
                  if (p.faceImageId) images[p.shortName] = p.faceImageId;
                });
              }
            }
            const mapXI = (names, roster) => {
              const set = new Set();
              const mappedImages = {};
              names.forEach((name) => {
                const p = roster.find(
                  (rp) =>
                    rp.name.includes(name) ||
                    name.includes(rp.name.split(" ").pop()),
                );
                if (p) {
                  set.add(p.name);
                  if (images[name]) mappedImages[p.name] = images[name];
                }
              });
              return { set, mappedImages };
            };
            const resA = mapXI(xiANames, rosterA.data);
            const resB = mapXI(xiBNames, rosterB.data);
            setXiA(resA.set);
            setXiB(resB.set);
            setPlayerImages((prev) => ({
              ...prev,
              ...resA.mappedImages,
              ...resB.mappedImages,
            }));
            setConditions((c) => ({
              ...c,
              venue:
                venues.find((v) =>
                  v.name.includes(match.matchInfo.venueInfo.ground),
                )?.id || c.venue,
              batting_team: foundA.id,
            }));
            setStep(2);
          } catch (e) {
            toast.error("Failed to map live squads to internal rosters.");
          }
        };
        loadSquads();
        return "Live match data synchronized.";
      },
      error: "Failed to fetch live Playing XI.",
    });
  };

  const runPrediction = async () => {
    setPredicting(true);
    try {
      const res = await predictMatch({
        team_a: teamA.id,
        team_b: teamB.id,
        batting_team: conditions.batting_team,
        toss_winner: conditions.toss_winner,
        venue: conditions.venue,
        pitch: conditions.pitch,
        weather: conditions.weather,
        playing_xi_a: Array.from(xiA),
        playing_xi_b: Array.from(xiB),
      });
      setPrediction(res);
      setStep(4);
    } catch (e) {
      toast.error(errorMessage(e, "Prediction failed"));
    } finally {
      setPredicting(false);
    }
  };

  const reset = () => {
    setTeamA(null);
    setTeamB(null);
    setXiA(new Set());
    setXiB(new Set());
    setConditions({
      venue: "",
      pitch: "",
      weather: "",
      toss_winner: "",
      batting_team: "",
    });
    setPrediction(null);
    setStep(0);
  };

  const handleHistorySelect = (p) => {
    setTeamA(teams.find((t) => t.id === p.input.team_a));
    setTeamB(teams.find((t) => t.id === p.input.team_b));
    setConditions(p.input);
    setXiA(new Set(p.input.playing_xi_a));
    setXiB(new Set(p.input.playing_xi_b));
    setPrediction(p.output);
    setStep(4);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const venueName = useMemo(
    () => venues.find((v) => v.id === conditions.venue)?.name || "",
    [venues, conditions.venue],
  );
  const pitchLabel = useMemo(
    () => pitchTypes.find((p) => p.id === conditions.pitch)?.label || "",
    [pitchTypes, conditions.pitch],
  );
  const weatherLabel = useMemo(
    () => weatherTypes.find((w) => w.id === conditions.weather)?.label || "",
    [weatherTypes, conditions.weather],
  );

  const bootstrapping =
    teamsQ.isLoading ||
    venuesQ.isLoading ||
    pitchesQ.isLoading ||
    weathersQ.isLoading;

  if (bootstrapping) {
    return (
      <div className="flex justify-center items-center min-h-screen text-white/60">
        <Loader2 className="mr-2 w-6 h-6 animate-spin" /> Booting up the dugout…
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0A0A0A] text-white">
      <Toaster theme="dark" position="top-center" richColors />
      {step > 0 && <Header step={step} source={overallSource} version={prediction?.model_version} />}

      {step === 0 && (
        <>
          <Hero onStart={() => setStep(1)} />
          <ErrorBoundary label="match history">
            <MatchHistory onSelect={handleHistorySelect} />
          </ErrorBoundary>
        </>
      )}

      {step === 1 && (
        <ErrorBoundary label="team selection">
          <TeamSelect
            teams={teams.map((t) => ({
              ...t,
              imageId: teamImages[t.id] || t.image_id,
            }))}
            teamA={teamA ? { ...teamA, imageId: teamImages[teamA.id] || teamA.image_id } : null}
            teamB={teamB ? { ...teamB, imageId: teamImages[teamB.id] || teamB.image_id } : null}
            onChangeA={handleSelectA}
            onChangeB={handleSelectB}
            onLiveMatchSelect={handleLiveMatchSelect}
            onNext={() => setStep(2)}
          />
        </ErrorBoundary>
      )}

      {step === 2 && teamA && teamB && (
        <ErrorBoundary label="player selection">
          <PlayerPicker
            teamA={{ ...teamA, imageId: teamImages[teamA.id] || teamA.image_id }}
            teamB={{ ...teamB, imageId: teamImages[teamB.id] || teamB.image_id }}
            selectedA={xiA}
            selectedB={xiB}
            playerImages={playerImages}
            onChangeA={setXiA}
            onChangeB={setXiB}
            onSourceChange={handlePlayersSourceChange}
            onBack={() => setStep(1)}
            onNext={() => setStep(3)}
          />
        </ErrorBoundary>
      )}

      {step === 3 && teamA && teamB && (
        <ErrorBoundary label="match conditions">
          <MatchConditions
            teamA={teamA}
            teamB={teamB}
            conditions={conditions}
            onChange={setConditions}
            onBack={() => setStep(2)}
            onPredict={runPrediction}
            predicting={predicting}
          />
        </ErrorBoundary>
      )}

      {step === 4 && prediction && (
        <ErrorBoundary label="prediction result">
          <PredictionResult
            teamA={teamA}
            teamB={teamB}
            conditions={conditions}
            prediction={prediction}
            venueName={venueName}
            pitchLabel={pitchLabel}
            weatherLabel={weatherLabel}
            liveMatchId={liveMatchId}
            onReset={reset}
            onBack={() => setStep(3)}
          />
        </ErrorBoundary>
      )}

      <footer className="mt-16 border-t border-white/5">
        <div className="flex flex-wrap gap-3 justify-between items-center px-6 py-8 mx-auto max-w-7xl font-mono text-xs sm:px-8 text-white/40">
          <span>© PitchPulse · Stats-driven IPL match modelling</span>
          <span>Educational predictions · not betting advice</span>
        </div>
      </footer>
    </div>
  );
};

export default IPLApp;
