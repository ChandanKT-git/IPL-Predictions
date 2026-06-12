# IPL Score Predictor

FastAPI backend + React frontend for predicting IPL first-innings scores
and chase outcomes, with conformal prediction intervals, calibrated
win probabilities, and live what-if scenarios. Backed by sklearn
HistGradientBoosting pipelines trained chronologically over 19 seasons of
ball-by-ball data.

## Architecture

### Backend (`backend/`)

| Module | Role |
| --- | --- |
| `server.py`          | FastAPI app, routes, lifespan, request-id middleware, SSE stream. |
| `predictor.py`       | Loads `models.joblib`, runs first-innings or chase models, returns prediction intervals + per-feature contributions. |
| `features.py`        | Per-innings feature builder (training) + per-request feature builder (live). 21 features cover XI strength, recent form, H2H aggregates, batter-vs-bowler matchup history, home/away, pitch + weather. The matchup feature is computed **leakage-free** (each row only sees prior history). |
| `train_model.py`     | Trains six models with a chronological 70 / 15 / 15 split: first-innings score regressor, P10/P90 quantile regressors with split-conformal correction, calibrated win classifier, chase-only score regressor, calibrated chase-win classifier, per-over progression model. Reports MAE, RMSE, log loss, Brier, and conformal coverage on val and test folds. |
| `data_manager.py`    | H2H, season aggregates, venue records, batter-vs-bowler matchups (cricinfo-style names mapped onto roster names). |
| `data_resolver.py`   | Live/cache/fallback orchestration over Cricbuzz responses. |
| `cricbuzz_service.py`| Async RapidAPI client with 10s timeout, 60s 429 cooldown, never raises. |
| `cache_layer.py`     | In-process TTL cache. |
| `id_mapper.py`       | Cricbuzz → internal ID mapping. |
| `observability.py`   | JSON logging + `X-Request-Id` middleware. |

Public endpoints (all under `/api`):

- `GET /health` — Mongo + Cricbuzz key + model + CSV status.
- `GET /teams`, `GET /teams/{id}/players`, `GET /venues`, `GET /pitch-types`, `GET /weather-types`.
- `GET /live-matches`, `GET /upcoming-matches`, `GET /live-match-xi/{id}`, `GET /live-match-score/{id}`, `GET /live-match-score/{id}/stream` (SSE), `GET /image/{id}`.
- `POST /predict` (supports `target_score` for chase mode), `POST /whatif`, `POST /analysis`.
- `GET /predictions/recent`, `GET /predictions/{id}`, `POST /predictions/{id}/favorite`, `POST /predictions/{id}/reconcile`.
- `GET /head-to-head/{a}/{b}`, `GET /calibration`.
- `POST /admin/cache/clear`, `POST /admin/cache/refresh` (token-or-localhost gated).

### Frontend (`frontend/`)

- React 18 + react-router-dom + `@tanstack/react-query` for caching.
- `ErrorBoundary` per step in the wizard.
- Typed API client (JSDoc) with `withSource` helper that reads `X-Data-Source`.
- `WhyPanel` component renders the top contributions for each prediction
  with per-feature direction, z-score, and a magnitude bar.
- `useLiveScoreStream` hook subscribes to the SSE feed; `LiveScoreTicker`
  renders a "Live" / "Last Known" pill.
- `LiveMatchPicker` exposes both Live and Upcoming match tabs.
- Slim shadcn surface: only `card`, `badge`, `select`, `slider`, `tooltip`.

## Setup

### Backend

```cmd
cd backend
python -m pip install -r requirements.txt
copy .env.example .env
:: Edit .env to set CRICBUZZ_API_KEY and (optionally) GROQ_API_KEY
python train_model.py        :: writes models.joblib + models_metrics.json
uvicorn server:app --reload  :: serves on http://localhost:8000
```

### Frontend

```cmd
cd frontend
npm install
npm start                    :: serves on http://localhost:3000
```

### Tests

```cmd
cd backend
python -m pytest tests/ -q
```

122 tests cover catalog routes, image proxy, admin cache, resolver
live/cache/fallback paths, the predictor adapter, the `/api/predict` and
`/api/whatif` endpoints, the data manager H2H, the new feature
builders (matchup, chase mode), the upcoming-matches route, the
reconcile/calibration round-trip, and the SSE stream generator.

## Honest evaluation

`models_metrics.json` carries per-fold metrics. Current numbers (chronological
70/15/15 split):

| Metric | Train | Val | Test |
| --- | --- | --- | --- |
| First-innings MAE | 21.6 | 25.8 | **38.5** |
| First-innings RMSE | 27.1 | 32.1 | **42.6** |
| Win classifier Brier | 0.18 | 0.226 | **0.242** |
| Chase MAE | 11.4 | 16.8 | **19.1** |
| Chase win Brier | 0.13 | 0.149 | **0.172** |
| Conformal coverage | — | 80% target | **79.7%** observed |

The honest numbers are higher than they look in random-split papers
because future seasons drift. The chase model has roughly half the score
error of the first-innings model — confirmation that conditioning on
target shrinks the prediction problem materially.

## Operational notes

- `CRICBUZZ_API_KEY` rotates on RapidAPI; `.env` is gitignored. The
  committed key in earlier revisions was replaced with a placeholder —
  rotate it on RapidAPI before deploying.
- Catalog responses cache for 6 hours; live scorecards for 30 seconds;
  upcoming matches for 5 minutes; H2H aggregates for 6 hours.
- The predictor **never raises** for a validated request — any
  inference-time error demotes to the heuristic branch and the response
  carries `model_version: "1.0-heuristic"`.
- `/api/live-match-score/{id}/stream` pushes a fresh frame every 30s
  (configurable via `LIVE_SCORE_STREAM_INTERVAL`). Three consecutive
  upstream failures end the stream so a hung client doesn't pin a
  connection.
- All log lines are JSON with the `request_id` field set to the
  `X-Request-Id` header (generated if absent and echoed in the response).
