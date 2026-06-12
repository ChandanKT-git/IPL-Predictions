import React from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { PredictionResult } from "./PredictionResult";
import { Header } from "./Header";
import { Loader2, Home } from "lucide-react";
import {
  predictionQuery,
  teamsQuery,
  venuesQuery,
  pitchTypesQuery,
  weatherTypesQuery,
} from "../lib/queries";

export const SharedPrediction = () => {
  const { id } = useParams();
  const navigate = useNavigate();
  const predictionQ = useQuery(predictionQuery(id));
  const teamsQ = useQuery(teamsQuery());
  const venuesQ = useQuery(venuesQuery());
  const pitchesQ = useQuery(pitchTypesQuery());
  const weathersQ = useQuery(weatherTypesQuery());

  const loading =
    predictionQ.isLoading ||
    teamsQ.isLoading ||
    venuesQ.isLoading ||
    pitchesQ.isLoading ||
    weathersQ.isLoading;

  if (loading) {
    return (
      <div className="flex flex-col justify-center items-center min-h-screen text-white/60 bg-[#0A0A0A]">
        <Loader2 className="mb-4 w-8 h-8 animate-spin text-[#FF3B30]" />
        <p className="font-mono text-xs uppercase tracking-widest">
          Retrieving shared analysis...
        </p>
      </div>
    );
  }

  if (predictionQ.error || !predictionQ.data) {
    return (
      <div className="flex flex-col justify-center items-center min-h-screen text-white/60 bg-[#0A0A0A]">
        <p className="font-mono text-xs uppercase tracking-widest">
          Prediction not found
        </p>
        <button
          onClick={() => navigate("/")}
          className="mt-4 inline-flex items-center gap-2 px-3 py-1.5 rounded-md border border-white/15 hover:bg-white/5 text-xs uppercase tracking-widest"
        >
          <Home className="w-3 h-3" /> Back to predictor
        </button>
      </div>
    );
  }

  const data = predictionQ.data;
  const teams = teamsQ.data?.data ?? [];
  const venues = venuesQ.data?.data ?? [];
  const pitchTypes = pitchesQ.data ?? [];
  const weatherTypes = weathersQ.data ?? [];

  const teamA = teams.find((t) => t.id === data.input.team_a);
  const teamB = teams.find((t) => t.id === data.input.team_b);
  const venueName = venues.find((v) => v.id === data.input.venue)?.name || "";
  const pitchLabel = pitchTypes.find((p) => p.id === data.input.pitch)?.label || "";
  const weatherLabel = weatherTypes.find((w) => w.id === data.input.weather)?.label || "";

  if (!teamA || !teamB) return null;

  return (
    <div className="min-h-screen bg-[#0A0A0A] text-white">
      <Header step={4} version={data.output?.model_version} />
      <div className="px-6 pt-10 mx-auto max-w-7xl sm:px-8">
        <button
          onClick={() => navigate("/")}
          className="flex items-center gap-2 text-xs font-heading uppercase tracking-widest text-white/40 hover:text-white transition-colors"
        >
          <Home className="w-3 h-3" /> Back to Predictor
        </button>
      </div>
      <PredictionResult
        teamA={teamA}
        teamB={teamB}
        conditions={data.input}
        prediction={{ ...data.output, id: data.id }}
        venueName={venueName}
        pitchLabel={pitchLabel}
        weatherLabel={weatherLabel}
        onReset={() => navigate("/")}
        onBack={() => navigate("/")}
      />
    </div>
  );
};
