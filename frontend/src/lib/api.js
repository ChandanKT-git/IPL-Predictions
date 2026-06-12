import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "http://localhost:8000";
export const API = `${BACKEND_URL}/api`;

export const api = axios.create({
  baseURL: API,
  headers: { "Content-Type": "application/json" },
  timeout: 30000,
});

/**
 * @typedef {{ id: string, name: string, short_name: string, primary_color: string,
 *            secondary_color: string, rating: number, captain: string,
 *            titles: number, image_id?: string|null, source?: string }} Team
 *
 * @typedef {{ name: string, role: string, country: string, batting_avg: number,
 *             strike_rate: number, wickets: number, economy: number,
 *             image_id?: string|null }} Player
 *
 * @typedef {{ id: string, name: string, city: string,
 *             default_pitch: string, avg_first_innings: number }} Venue
 *
 * @typedef {{ id: string, label: string, score_modifier: number }} TypedOption
 *
 * @typedef {"live"|"cache"|"fallback"|"mixed"} Source
 *
 * @typedef {{ data: any[], source: Source }} SourcedResponse
 */

const VALID_SOURCES = new Set(["live", "cache", "fallback", "mixed"]);

const withSource = (response) => {
  const headerSource = response.headers && response.headers["x-data-source"];
  const source = VALID_SOURCES.has(headerSource) ? headerSource : "fallback";
  return { data: response.data, source };
};

export const fetchTeams = () => api.get("/teams").then(withSource);
export const fetchPlayers = (teamId) =>
  api.get(`/teams/${teamId}/players`).then(withSource);
export const fetchVenues = () => api.get("/venues").then(withSource);
export const fetchPitchTypes = () => api.get("/pitch-types").then((r) => r.data);
export const fetchWeatherTypes = () => api.get("/weather-types").then((r) => r.data);

export const predictMatch = (payload) =>
  api.post("/predict", payload).then((r) => r.data);
export const whatIfPredict = (payload) =>
  api.post("/whatif", payload).then((r) => r.data);
export const fetchAnalysis = (payload) =>
  api.post("/analysis", payload).then((r) => r.data);

export const fetchLiveMatches = () => api.get("/live-matches").then((r) => r.data);
export const fetchUpcomingMatches = () =>
  api.get("/upcoming-matches").then((r) => r.data);
export const fetchLiveMatchXI = (matchId) =>
  api.get(`/live-match-xi/${matchId}`).then((r) => r.data);
export const fetchLiveMatchScore = (matchId) =>
  api.get(`/live-match-score/${matchId}`).then((r) => r.data);

export const fetchPrediction = (id) =>
  api.get(`/predictions/${id}`).then((r) => r.data);
export const fetchRecentPredictions = (limit = 10) =>
  api.get(`/predictions/recent?limit=${limit}`).then((r) => r.data);
export const toggleFavorite = (id) =>
  api.post(`/predictions/${id}/favorite`).then((r) => r.data);
export const reconcilePrediction = (id, payload) =>
  api.post(`/predictions/${id}/reconcile`, payload).then((r) => r.data);
export const fetchCalibration = () => api.get("/calibration").then((r) => r.data);
export const fetchH2H = (teamA, teamB) =>
  api.get(`/head-to-head/${teamA}/${teamB}`).then((r) => r.data);

export const fetchHealth = () => api.get("/health").then((r) => r.data);

/** Build the SSE URL for a live match score stream. */
export const liveScoreStreamUrl = (matchId) =>
  `${API}/live-match-score/${matchId}/stream`;

export const getImageUrl = (imageId, size = "thumb") =>
  `${API}/image/${imageId}?p=${size}`;

/**
 * Normalise an axios error into a single string suitable for a toast.
 * FastAPI surfaces validation errors as `detail: [{loc, msg, ...}, ...]`,
 * which would otherwise render as "[object Object]".
 *
 * @param {unknown} error
 * @param {string} fallback
 * @returns {string}
 */
export const errorMessage = (error, fallback = "Request failed") => {
  const detail = error && error.response && error.response.data && error.response.data.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        if (!d || typeof d !== "object") return String(d);
        const field = Array.isArray(d.loc) ? d.loc.slice(1).join(".") : "";
        return field ? `${field}: ${d.msg}` : d.msg || JSON.stringify(d);
      })
      .join("; ");
  }
  if (error && error.message) return error.message;
  return fallback;
};
