import {
    fetchTeams,
    fetchVenues,
    fetchPitchTypes,
    fetchWeatherTypes,
    fetchPlayers,
    fetchH2H,
    fetchPrediction,
    fetchRecentPredictions,
} from "./api";

export const teamsQuery = () => ({
    queryKey: ["teams"],
    queryFn: fetchTeams,
    staleTime: 6 * 60 * 60 * 1000,
});

export const venuesQuery = () => ({
    queryKey: ["venues"],
    queryFn: fetchVenues,
    staleTime: 6 * 60 * 60 * 1000,
});

export const pitchTypesQuery = () => ({
    queryKey: ["pitch-types"],
    queryFn: fetchPitchTypes,
    staleTime: 24 * 60 * 60 * 1000,
});

export const weatherTypesQuery = () => ({
    queryKey: ["weather-types"],
    queryFn: fetchWeatherTypes,
    staleTime: 24 * 60 * 60 * 1000,
});

export const playersQuery = (teamId) => ({
    queryKey: ["players", teamId],
    queryFn: () => fetchPlayers(teamId),
    enabled: Boolean(teamId),
    staleTime: 6 * 60 * 60 * 1000,
});

export const h2hQuery = (teamA, teamB) => ({
    queryKey: ["h2h", teamA, teamB],
    queryFn: () => fetchH2H(teamA, teamB),
    enabled: Boolean(teamA && teamB),
    staleTime: 6 * 60 * 60 * 1000,
});

export const predictionQuery = (id) => ({
    queryKey: ["prediction", id],
    queryFn: () => fetchPrediction(id),
    enabled: Boolean(id),
});

export const recentPredictionsQuery = (limit = 10) => ({
    queryKey: ["predictions", "recent", limit],
    queryFn: () => fetchRecentPredictions(limit),
});
