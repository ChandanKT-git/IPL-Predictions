# IPL Match Prediction System - Architecture Documentation

## Table of Contents
1. [System Overview](#system-overview)
2. [Architecture Diagram](#architecture-diagram)
3. [Component Architecture](#component-architecture)
4. [Data Flow](#data-flow)
5. [Technology Stack](#technology-stack)
6. [Design Patterns](#design-patterns)
7. [Scalability & Performance](#scalability--performance)

## System Overview

The IPL Match Prediction System is a full-stack web application that predicts IPL cricket match outcomes using machine learning. The system integrates real-time data from Cricbuzz API, historical match data, and advanced ML models to provide accurate predictions with confidence intervals.

### Key Capabilities
- **Real-time Integration**: Fetches live match data from Cricbuzz API
- **ML-Powered Predictions**: Uses calibrated Random Forest models with quantile regression
- **Interactive UI**: Modern React frontend with real-time updates
- **Intelligent Caching**: Redis-based caching with graceful fallbacks
- **Observability**: Structured logging and request tracking
- **Prediction Storage**: MongoDB for prediction history and analytics

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                          CLIENT LAYER                                │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │          React Frontend (Port 3000)                           │  │
│  │  • Team Selection    • Player Picker    • Live Match Picker  │  │
│  │  • Prediction Display • Form Guide     • Match History       │  │
│  └───────────────────────────────────────────────────────────────┘  │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ HTTP/REST API
                           │ (Axios Client)
┌──────────────────────────▼──────────────────────────────────────────┐
│                       API GATEWAY LAYER                              │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │     FastAPI Server (Port 8000)                                │  │
│  │  • CORS Middleware    • Request ID Tracking                   │  │
│  │  • Error Handling     • Structured Logging                    │  │
│  └───────────────────────────────────────────────────────────────┘  │
└──────────────┬────────────────────────┬───────────────┬─────────────┘
               │                        │               │
     ┌─────────▼─────────┐   ┌─────────▼────────┐     │
     │  ML Service Layer │   │  Data Layer      │     │
     │                   │   │                  │     │
     │  • Predictor      │   │  • Data Manager  │     │
     │  • Features       │   │  • ID Mapper     │     │
     │  • Model Pipeline │   │  • Data Resolver │     │
     └───────────────────┘   └──────────────────┘     │
                                                       │
┌──────────────────────────────────────────────────────▼─────────────┐
│                    EXTERNAL SERVICES LAYER                          │
│  ┌────────────────┐  ┌──────────────┐  ┌───────────────────────┐  │
│  │ Cricbuzz API   │  │ Cache Layer  │  │  MongoDB              │  │
│  │ (RapidAPI)     │  │ (Redis)      │  │  (Predictions DB)     │  │
│  │                │  │              │  │                       │  │
│  │ • Live Matches │  │ • TTL Cache  │  │ • Prediction History  │  │
│  │ • Player Data  │  │ • Fallback   │  │ • Calibration Metrics │  │
│  │ • Team Info    │  │ • Source Tag │  │ • User Favorites      │  │
│  └────────────────┘  └──────────────┘  └───────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                               │
                   ┌───────────▼────────────┐
                   │   DATA SOURCES         │
                   │                        │
                   │  • IPL.csv (283K rows) │
                   │  • models.joblib       │
                   │  • models_metrics.json │
                   └────────────────────────┘
```

## Component Architecture

### 1. Frontend Architecture (React)

```
frontend/
├── src/
│   ├── components/          # React Components
│   │   ├── LiveMatchPicker.jsx      # Fetch & display live matches
│   │   ├── TeamSelect.jsx           # Team selection UI
│   │   ├── PlayerPicker.jsx         # XI selection with images
│   │   ├── MatchConditions.jsx      # Venue, pitch, weather
│   │   ├── PredictionResult.jsx     # Display predictions
│   │   ├── FormGuide.jsx            # Recent team performance
│   │   ├── MatchHistory.jsx         # H2H statistics
│   │   ├── TeamLogo.jsx             # Team branding
│   │   └── PlayerAvatar.jsx         # Player images
│   │
│   ├── lib/                 # Utilities
│   │   └── api.js                   # API client & helpers
│   │
│   ├── components/ui/       # Reusable UI Components
│   │   ├── select.jsx               # Dropdown component
│   │   ├── slider.jsx               # Range slider
│   │   └── ...                      # Other UI primitives
│   │
│   ├── App.js               # Main application component
│   └── index.js             # React entry point
│
└── public/                  # Static assets
    └── index.html           # HTML template
```

**Design Principles:**
- **Component Composition**: Small, reusable components
- **Separation of Concerns**: UI logic separate from business logic
- **State Management**: React hooks (useState, useEffect)
- **API Integration**: Centralized API client
- **Error Boundaries**: Graceful error handling

### 2. Backend Architecture (FastAPI)

```
backend/
├── server.py                # FastAPI application & routes
├── predictor.py             # ML prediction service
├── features.py              # Feature engineering
├── train_model.py           # Model training pipeline
│
├── Data Layer
│   ├── data_manager.py      # Historical data loading
│   ├── ipl_data.py          # IPL dataset interface
│   ├── data_resolver.py     # Cricbuzz ↔ Internal mapping
│   └── id_mapper.py         # ID translation
│
├── Integration Layer
│   ├── cricbuzz_service.py  # Cricbuzz API client
│   ├── cache_layer.py       # Redis caching
│   └── observability.py     # Logging & monitoring
│
├── tests/                   # Test suite
│   ├── test_predict.py
│   ├── test_features.py
│   ├── test_data_manager.py
│   └── test_routes_*.py
│
└── data/
    └── IPL.csv              # Historical match data (283K rows)
```

**Design Principles:**
- **Layered Architecture**: Separation of concerns (API, Business, Data)
- **Dependency Injection**: Services passed through constructors
- **Async/Await**: Non-blocking I/O operations
- **Type Hints**: Python type annotations for clarity
- **Error Handling**: Try-except with structured logging

### 3. ML Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    TRAINING PIPELINE                        │
│                                                             │
│  1. Data Loading (IPL.csv)                                 │
│       ↓                                                     │
│  2. Feature Engineering (features.py)                      │
│       • Team strength (batting/bowling)                    │
│       • Recent form (last 5 matches)                       │
│       • Toss impact                                        │
│       • H2H win share                                      │
│       • Venue effect                                       │
│       • Pitch/weather modifiers                            │
│       ↓                                                     │
│  3. Chronological Train/Test Split                         │
│       • Train: ≤ 2023                                      │
│       • Validation: 2024                                   │
│       • Test: 2025+                                        │
│       ↓                                                     │
│  4. Model Training                                         │
│       • Score Predictor: RandomForestRegressor             │
│       • Win Classifier: CalibratedClassifierCV             │
│       • Quantile Regressors: P10, P90                      │
│       ↓                                                     │
│  5. Calibration & Evaluation                               │
│       • Isotonic regression for win probability            │
│       • Prediction interval coverage                       │
│       • MAE, Brier score metrics                           │
│       ↓                                                     │
│  6. Model Persistence                                      │
│       • Save to models.joblib                              │
│       • Save metrics to models_metrics.json                │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                   INFERENCE PIPELINE                        │
│                                                             │
│  1. Input Validation                                        │
│       • Teams, venue, pitch, weather                       │
│       • Playing XI (11 players each)                       │
│       • Toss winner, batting team                          │
│       ↓                                                     │
│  2. Feature Computation                                    │
│       • Real-time feature calculation                      │
│       • H2H lookup from historical data                    │
│       • Batter-bowler matchup retrieval                    │
│       ↓                                                     │
│  3. Model Prediction                                       │
│       • Score prediction (P10, P50, P90)                   │
│       • Win probability (calibrated)                       │
│       • Phase breakdown (PP, Middle, Death)                │
│       ↓                                                     │
│  4. Post-Processing                                        │
│       • Feature importance (SHAP-style)                    │
│       • Confidence intervals                               │
│       • Prediction ID generation                           │
│       ↓                                                     │
│  5. Response Enrichment                                    │
│       • H2H statistics                                     │
│       • Top batter-bowler matchups                         │
│       • Model metadata                                     │
│       ↓                                                     │
│  6. Storage & Delivery                                     │
│       • Save to MongoDB                                    │
│       • Return to client                                   │
└─────────────────────────────────────────────────────────────┘
```

## Data Flow

### Prediction Request Flow

```
┌──────────┐     1. Select Teams     ┌──────────────┐
│  User    │────────────────────────▶│   Frontend   │
└──────────┘                         └──────┬───────┘
                                            │
                 2. Fetch Players           │
                    GET /api/teams/{id}/players
                                            │
                                            ▼
┌──────────────────────────────────────────────────┐
│              FastAPI Server                       │
│  ┌────────────────────────────────────────────┐  │
│  │  1. Check Cache (Redis)                    │  │
│  │     • Hit: Return cached data              │  │
│  │     • Miss: Fetch from Cricbuzz            │  │
│  └────────────────────────────────────────────┘  │
└────────────┬─────────────────────────────────────┘
             │
             │ 3. Cricbuzz API Call (if cache miss)
             ▼
┌──────────────────────────┐
│   CricbuzzService        │
│  • GET /teams            │◀─── RapidAPI
│  • GET /players          │
└──────────┬───────────────┘
           │
           │ 4. Map IDs
           ▼
┌──────────────────────────┐
│   DataResolver           │
│  • Cricbuzz ID → Team ID │
│  • Player names → IDs    │
└──────────┬───────────────┘
           │
           │ 5. Cache & Return
           ▼
     ┌─────────────┐
     │   Redis     │
     │  (5 min TTL)│
     └─────────────┘
           │
           ▼
     Response to Frontend
```

### Prediction Generation Flow

```
Frontend                 Backend                    ML Pipeline
   │                        │                            │
   │  POST /api/predict     │                            │
   │ ──────────────────────▶│                            │
   │                        │                            │
   │                        │  1. Validate Input         │
   │                        │ ───────────────────────▶   │
   │                        │                            │
   │                        │  2. Extract Features       │
   │                        │ ───────────────────────▶   │
   │                        │     • Team stats           │
   │                        │     • Recent form          │
   │                        │     • H2H history          │
   │                        │     • Venue effect         │
   │                        │                            │
   │                        │  3. Model Inference        │
   │                        │ ───────────────────────▶   │
   │                        │     • Score prediction     │
   │                        │     • Win probability      │
   │                        │     • Quantiles (P10/P90)  │
   │                        │                            │
   │                        │  4. Post-process           │
   │                        │ ◀───────────────────────   │
   │                        │     • Feature importance   │
   │                        │     • Matchups             │
   │                        │                            │
   │                        │  5. Enrich Response        │
   │                        │     • H2H stats            │
   │                        │     • Season breakdown     │
   │                        │                            │
   │                        │  6. Save to MongoDB        │
   │                        │ ─────────▶ ┌──────────┐   │
   │                        │            │ MongoDB  │   │
   │                        │            └──────────┘   │
   │                        │                            │
   │  ◀────── Response ─────│                            │
   │  {                     │                            │
   │    predicted_score,    │                            │
   │    win_probability,    │                            │
   │    contributions,      │                            │
   │    matchups,           │                            │
   │    h2h                 │                            │
   │  }                     │                            │
```

## Technology Stack

### Frontend
```yaml
Core:
  - React 18.x: UI framework
  - JavaScript (ES6+): Programming language
  - Axios: HTTP client

UI Components:
  - Tailwind CSS: Utility-first CSS
  - Lucide Icons: Icon library
  - Custom UI components: Modals, dropdowns, sliders

Build Tools:
  - Create React App (CRACO): Build configuration
  - Webpack: Module bundler
  - Babel: JavaScript transpiler

Development:
  - ESLint: Code linting
  - Prettier: Code formatting
```

### Backend
```yaml
Core:
  - Python 3.9+: Programming language
  - FastAPI: Web framework
  - Uvicorn: ASGI server
  - Pydantic: Data validation

Machine Learning:
  - scikit-learn 1.3+: ML algorithms
  - pandas: Data manipulation
  - numpy: Numerical computing

Data Storage:
  - MongoDB (motor): NoSQL database (async)
  - Redis: Caching layer

External APIs:
  - Cricbuzz (RapidAPI): Live cricket data
  - httpx: Async HTTP client

Observability:
  - Python logging: Structured JSON logs
  - Request ID tracking: Distributed tracing

Testing:
  - pytest: Testing framework
  - FastAPI TestClient: API testing
```

### Infrastructure
```yaml
Databases:
  - MongoDB 6.0+: Document store
  - Redis 7.0+: In-memory cache

Deployment:
  - Docker: Containerization (optional)
  - Environment variables: Configuration

Monitoring:
  - Structured logging: JSON format
  - Request tracking: UUID-based
```

## Design Patterns

### 1. Repository Pattern (Data Layer)
```python
# Abstraction for data access
class IPLDataManager:
    def __init__(self, csv_path):
        self.df = pd.read_csv(csv_path)
    
    def get_match_outcomes(self):
        """Encapsulates data retrieval logic"""
        return self.df.groupby(['match_id', 'team'])...
```

### 2. Service Layer Pattern (Business Logic)
```python
# Business logic separated from API layer
class Predictor:
    def predict(self, team_a, team_b, ...):
        """Encapsulates prediction logic"""
        features = self._build_features(...)
        score = self.score_model.predict(features)
        win_prob = self.win_model.predict_proba(features)
        return PredictionResult(...)
```

### 3. Dependency Injection
```python
# Dependencies passed through constructors
app = FastAPI()

@app.on_event("startup")
async def startup():
    app.state.predictor = Predictor(bundle_path="models.joblib")
    app.state.data_manager = IPLDataManager(csv_path="data/IPL.csv")
    app.state.cricbuzz = CricbuzzService(api_key=...)
```

### 4. Strategy Pattern (Caching)
```python
# Multiple fallback strategies
class CacheLayer:
    async def get(self, key):
        # Strategy 1: Redis
        if self.redis_available:
            return await self.redis.get(key)
        
        # Strategy 2: In-memory
        return self.memory_cache.get(key)
```

### 5. Factory Pattern (Feature Engineering)
```python
# Feature creation encapsulated
class FeatureBuilder:
    @staticmethod
    def build_features(match_context, historical_data):
        return {
            'team_strength': TeamStrength.compute(...),
            'recent_form': RecentForm.compute(...),
            'h2h_stats': H2HStats.compute(...),
            ...
        }
```

### 6. Observer Pattern (Real-time Updates)
```python
# SSE for live score streaming
@app.get("/api/live-match-score/{match_id}/stream")
async def stream_live_score(match_id: str):
    async def event_generator():
        while True:
            score = await fetch_live_score(match_id)
            yield f"data: {json.dumps(score)}\n\n"
            await asyncio.sleep(10)
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

## Scalability & Performance

### Caching Strategy
```
┌────────────────────────────────────────────────────┐
│              Cache TTL Strategy                    │
├────────────────────────────────────────────────────┤
│  Teams:          24 hours (stable data)            │
│  Players:        12 hours (roster changes rare)    │
│  Venues:         7 days (rarely change)            │
│  Live Matches:   5 minutes (frequent updates)      │
│  Match XI:       30 minutes (changes pre-match)    │
│  Predictions:    Permanent (MongoDB)               │
└────────────────────────────────────────────────────┘
```

### Performance Optimizations

1. **Async I/O**
   - All external API calls are async
   - MongoDB operations use motor (async driver)
   - Redis operations non-blocking

2. **Connection Pooling**
   - HTTP client reuses connections
   - Database connection pool (MongoDB)
   - Redis connection pool

3. **Lazy Loading**
   - Models loaded once at startup
   - Historical data cached in memory
   - Feature computation on-demand

4. **Frontend Optimization**
   - Code splitting (React.lazy)
   - Image lazy loading
   - API response caching
   - Debounced user inputs

### Horizontal Scaling

```
┌─────────────┐
│ Load        │
│ Balancer    │
└──────┬──────┘
       │
       ├─────────┬─────────┬─────────┐
       │         │         │         │
   ┌───▼───┐ ┌──▼────┐ ┌──▼────┐ ┌──▼────┐
   │ API 1 │ │ API 2 │ │ API 3 │ │ API N │
   └───┬───┘ └───┬───┘ └───┬───┘ └───┬───┘
       │         │         │         │
       └─────────┴─────────┴─────────┘
                    │
         ┌──────────┴───────────┐
         │                      │
    ┌────▼─────┐         ┌─────▼────┐
    │  Redis   │         │ MongoDB  │
    │ (Shared) │         │ (Shared) │
    └──────────┘         └──────────┘
```

### Monitoring Points

1. **Request Metrics**
   - Request duration
   - Error rates
   - Cache hit/miss ratio

2. **Model Metrics**
   - Prediction latency
   - Feature computation time
   - Model version tracking

3. **External Service Health**
   - Cricbuzz API availability
   - Redis connectivity
   - MongoDB performance

## Security Considerations

### API Security
- API key authentication (Cricbuzz)
- CORS configuration
- Input validation (Pydantic)
- Rate limiting (recommended)

### Data Security
- Environment variables for secrets
- .env files gitignored
- MongoDB authentication
- Redis password protection

### Frontend Security
- XSS prevention (React auto-escaping)
- HTTPS for production
- CSP headers (recommended)
- Secure cookies (if auth added)

## Deployment Architecture

### Development
```
localhost:3000 (React Dev Server)
     │
     └──► localhost:8000 (FastAPI)
              │
              ├──► MongoDB (localhost:27017)
              ├──► Redis (localhost:6379)
              └──► Cricbuzz API (RapidAPI)
```

### Production (Recommended)
```
nginx (Reverse Proxy)
  ├──► Static Files (React Build)
  └──► /api/* → Uvicorn Workers (4+)
                    │
                    ├──► MongoDB (Replica Set)
                    ├──► Redis (Sentinel/Cluster)
                    └──► Cricbuzz API
```

## Future Architecture Considerations

### Microservices Evolution
```
API Gateway
  ├──► Prediction Service
  ├──► Data Service
  ├──► Cricbuzz Integration Service
  └──► Analytics Service
```

### Message Queue Integration
```
FastAPI → RabbitMQ/Kafka → Workers
  • Async prediction processing
  • Batch data updates
  • Real-time notifications
```

### Model Serving
```
API → Model Server (TensorFlow Serving / MLflow)
  • A/B testing
  • Model versioning
  • Canary deployments
```

---

**Document Version:** 1.0  
**Last Updated:** 2026-06-13  
**Maintained By:** IPL Predictions Team
