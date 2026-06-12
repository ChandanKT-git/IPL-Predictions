# IPL Match Prediction System

> 🏏 A full-stack machine learning application that predicts IPL cricket match outcomes using real-time data integration, advanced ML models, and intelligent caching strategies.

[![Model Version](https://img.shields.io/badge/model-v5.0--chronological--calibrated-blue)](docs/MODEL_DOCUMENTATION.md)
[![Test MAE](https://img.shields.io/badge/test%20MAE-38.5%20runs-green)](docs/MODEL_DOCUMENTATION.md#evaluation-metrics)
[![API Docs](https://img.shields.io/badge/API-documented-orange)](docs/API_REFERENCE.md)
[![Python](https://img.shields.io/badge/python-3.9+-blue)](https://python.org)
[![React](https://img.shields.io/badge/react-18-blue)](https://react.dev)

## 📚 Documentation

**Comprehensive documentation is available in the `/docs` folder:**

- **[📖 Architecture](docs/ARCHITECTURE.md)** - System design, data flow, component architecture
- **[🤖 Model Documentation](docs/MODEL_DOCUMENTATION.md)** - ML pipeline, feature engineering, model decisions
- **[🔌 API Reference](docs/API_REFERENCE.md)** - Complete API endpoint documentation
- **[💻 Development Guide](docs/DEVELOPMENT_GUIDE.md)** - Setup, workflow, testing, contributing

---

## 🚀 Quick Start

### Prerequisites
- Python 3.9+
- Node.js 16+
- MongoDB 6.0+
- Redis 7.0+

### Installation

1. **Clone & Setup**
```bash
git clone https://github.com/yourusername/ipl-predictions.git
cd ipl-predictions
```

2. **Backend Setup**
```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys
```

3. **Frontend Setup**
```bash
cd frontend

# Install dependencies
npm install

# Configure environment
cp .env.example .env
```

4. **Start Services**
```bash
# Start MongoDB
mongod --dbpath ./data/db

# Start Redis
redis-server

# Start Backend (Terminal 1)
cd backend
python -m uvicorn server:app --reload --port 8000

# Start Frontend (Terminal 2)
cd frontend
npm start
```

5. **Access Application**
- 🌐 **Frontend:** http://localhost:3000
- 🔌 **API:** http://localhost:8000
- 📖 **API Docs:** http://localhost:8000/docs

---

## ✨ Key Features

### 🎯 **Advanced ML Predictions**
- **Score Prediction** with 80% confidence intervals (P10-P90 quantiles)
- **Win Probability** with calibrated probabilities (Brier score: 0.21)
- **Phase Breakdown**: Powerplay, Middle overs, Death overs
- **Model Version:** 5.0-chronological-calibrated

### 📊 **Feature Engineering**
- Team strength ratings (batting/bowling)
- Recent form (last 5 matches)
- Head-to-head statistics
- Toss impact analysis
- Venue effects
- Pitch & weather modifiers
- **21 engineered features** from 283K historical rows

### 🔄 **Real-time Integration**
- Live IPL match data from **Cricbuzz API**
- Auto-fill match details (teams, venue, playing XI)
- Live score updates via **Server-Sent Events (SSE)**
- Upcoming match schedule

### 💾 **Intelligent Caching**
- **Redis-based caching** with TTL strategy
- **In-memory fallback** when Redis unavailable
- **Graceful degradation** (live → cache → fallback)
- Source tracking (`X-Data-Source` header)

### 📈 **Analytics & Insights**
- **Feature Contributions** (SHAP-style importance)
- **Batter-Bowler Matchups** from historical data
- **H2H Analysis** (season-wise, venue-specific)
- **Form Guide** (recent performance trends)
- **Model Calibration** metrics

### 🎨 **Modern UI/UX**
- **React 18** with Tailwind CSS
- **Live Match Picker** (auto-fill from current matches)
- **Team Logos** (official IPL branding)
- **Player Avatars** (with fallback to team-colored initials)
- **What-If Scenarios** (slider-based exploration)
- **Responsive Design** (mobile-friendly)

### 🔍 **Observability**
- Structured JSON logging
- Request ID tracking (distributed tracing)
- Performance monitoring
- Health checks (`/api/health`)

---

## 🏗️ Architecture Overview

```
┌─────────────┐
│   React     │  ← Tailwind CSS, Axios, React Query
│  Frontend   │
└──────┬──────┘
       │ HTTP/REST
       ▼
┌─────────────┐
│   FastAPI   │  ← CORS, Middleware, Async
│   Backend   │
└──────┬──────┘
       │
  ┌────┴─────┬──────────┬──────────┐
  ▼          ▼          ▼          ▼
┌────┐   ┌──────┐   ┌──────┐   ┌────────┐
│ ML │   │Redis │   │Mongo │   │Cricbuzz│
│Model│   │Cache │   │  DB  │   │  API   │
└────┘   └──────┘   └──────┘   └────────┘
```

**For detailed architecture, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**

---

## 🤖 Machine Learning Pipeline

### Model Architecture

```
Input Features (21-dim)
         ↓
    Preprocessing
    (Scaling + Encoding)
         ↓
    ┌────┴─────┐
    ▼          ▼
Score Model  Win Model
(RF Regressor) (Calibrated)
    │          │
    ▼          ▼
P10/P50/P90   Win Prob
Quantiles     (0-100%)
```

### Training Strategy

- **Chronological Split**: Train ≤2023, Val 2024, Test 2025+
- **No Data Leakage**: Respects temporal ordering
- **574 Training Matches**: IPL seasons 2008-2023
- **Test MAE**: 38.5 runs (±2 overs)

### Key Features

| Feature | Importance | Description |
|---------|-----------|-------------|
| Team Batting Rating | 0.28 | Last 20 matches batting performance |
| Recent Form | 0.22 | Win rate in last 5 matches |
| Toss Won by Batting | 0.18 | Strategic advantage |
| Venue Effect | 0.15 | Ground characteristics |
| H2H Win Share | 0.12 | Historical dominance |

**For complete model details, see [docs/MODEL_DOCUMENTATION.md](docs/MODEL_DOCUMENTATION.md)**

---

## 📡 API Endpoints

### Core Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | System health check |
| `GET` | `/api/teams` | List all IPL teams |
| `GET` | `/api/teams/{id}/players` | Team players |
| `GET` | `/api/venues` | List venues |
| `POST` | `/api/predict` | Generate prediction |
| `GET` | `/api/live-matches` | Current IPL matches |
| `GET` | `/api/head-to-head/{a}/{b}` | H2H statistics |

**For complete API documentation, see [docs/API_REFERENCE.md](docs/API_REFERENCE.md)**

### Example: Prediction Request

```bash
curl -X POST http://localhost:8000/api/predict \
  -H "Content-Type: application/json" \
  -d '{
    "team_a": "mi",
    "team_b": "csk",
    "batting_team": "mi",
    "toss_winner": "mi",
    "venue": "wankhede",
    "pitch": "batting",
    "weather": "clear",
    "playing_xi_a": ["Rohit Sharma", "Ishan Kishan", ...],
    "playing_xi_b": ["Ruturaj Gaikwad", "Devon Conway", ...]
  }'
```

### Example: Prediction Response

```json
{
  "id": "15d1f59f-a410-464b-8623-f69f293e431e",
  "predicted_score": 175,
  "score_range_low": 145,
  "score_range_high": 205,
  "win_probability_batting": 65,
  "win_probability_bowling": 35,
  "phase_breakdown": {
    "powerplay_runs": 48,
    "middle_overs_runs": 72,
    "death_overs_runs": 55
  },
  "model_version": "5.0-chronological-calibrated",
  "contributions": [...],
  "h2h": {...},
  "matchups": [...]
}
```

---

## 🧪 Testing

### Backend Tests

```bash
cd backend

# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Run specific test
pytest tests/test_predict.py -v
```

### Frontend Tests

```bash
cd frontend

# Run tests
npm test

# Run with coverage
npm test -- --coverage
```

### Test Coverage

- **Backend**: 85% coverage
- **Frontend**: 72% coverage
- **Integration Tests**: API routes, prediction flow, data resolution

---

## 🔧 Configuration

### Environment Variables

#### Backend (`.env`)
```bash
# Cricbuzz API (RapidAPI)
CRICBUZZ_API_KEY=your_api_key_here
RAPIDAPI_HOST=cricbuzz-cricket.p.rapidapi.com

# Database
MONGO_URL=mongodb://localhost:27017
DB_NAME=ipl_predictions
REDIS_URL=redis://localhost:6379

# Optional: AI Analysis
GROQ_API_KEY=your_groq_key_here
```

#### Frontend (`.env`)
```bash
REACT_APP_BACKEND_URL=http://localhost:8000
```

---

## 📊 Model Performance

### Metrics Summary

| Metric | Value | Interpretation |
|--------|-------|----------------|
| **Test MAE** | 38.5 runs | Average error ≈ 2 overs |
| **Test RMSE** | 48.2 runs | Penalizes large errors |
| **R² Score** | 0.48 | Explains 48% of variance |
| **Win Accuracy** | 65.2% | Better than baseline (50%) |
| **Brier Score** | 0.21 | Well-calibrated probabilities |
| **Coverage (80%)** | 78.5% | Close to target |

### Model Versioning

| Version | Date | Test MAE | Notes |
|---------|------|----------|-------|
| 1.0-heuristic | 2024-01 | 58.2 | Rule-based baseline |
| 2.0-random-split | 2024-03 | 25.4 | ❌ Data leakage |
| 3.0-chronological | 2024-06 | 41.8 | ✅ Honest metrics |
| 4.0-calibrated | 2024-09 | 39.2 | ✅ Better probabilities |
| **5.0-chronological-calibrated** | **2024-12** | **38.5** | **✅ Current (with quantiles)** |

---

## 🛠️ Tech Stack

### Backend
- **Framework**: FastAPI 0.104+
- **ML**: scikit-learn 1.3+, pandas, numpy
- **Database**: MongoDB (motor), Redis
- **API Client**: httpx (async)
- **Testing**: pytest
- **Logging**: Python logging (JSON format)

### Frontend
- **Framework**: React 18
- **Styling**: Tailwind CSS
- **HTTP Client**: Axios
- **State Management**: React Query
- **Icons**: Lucide React
- **Build**: Create React App (CRACO)

### Infrastructure
- **Server**: Uvicorn (ASGI)
- **Database**: MongoDB 6.0+
- **Cache**: Redis 7.0+
- **Deployment**: Docker (optional)

---

## 🔐 Security

- ✅ Environment variables for secrets
- ✅ `.env` files gitignored
- ✅ Input validation (Pydantic)
- ✅ CORS configuration
- ✅ MongoDB authentication
- ✅ Redis password protection
- ⚠️ Rate limiting (recommended for production)

---

## 📈 Future Enhancements

### High Priority 🔴
- [ ] **Separate Chase Model** - Model RRR and pressure situations
- [ ] **Conformal Prediction Intervals** - Guaranteed coverage
- [ ] **Player-Level Features** - Individual form and matchups in model

### Medium Priority 🟡
- [ ] **SHAP Explainability** - Interactive feature importance
- [ ] **Online Learning** - Update model after each match
- [ ] **A/B Testing** - Compare model versions

### Low Priority 🟢
- [ ] **Neural Network Ensemble** - Marginal performance gains
- [ ] **WebSocket Support** - Bidirectional real-time updates
- [ ] **Mobile App** - React Native implementation

---

## 🤝 Contributing

We welcome contributions! Please see [DEVELOPMENT_GUIDE.md](docs/DEVELOPMENT_GUIDE.md) for:
- Development workflow
- Code style guidelines
- Testing requirements
- Pull request process

### Quick Contribution Guide

1. Fork the repository
2. Create feature branch (`git checkout -b feature/your-feature`)
3. Make changes with tests
4. Commit (`git commit -m 'feat: add feature'`)
5. Push (`git push origin feature/your-feature`)
6. Create Pull Request

---

## 📝 License

This project is licensed under the MIT License - see [LICENSE](LICENSE) file for details.

---

## 👥 Authors

- **Your Name** - Initial work

---

## 🙏 Acknowledgments

- **Cricsheet** - Historical ball-by-ball data
- **Cricbuzz API** - Live match data (via RapidAPI)
- **IPL** - Logo and branding assets
- **scikit-learn** - ML framework
- **FastAPI** - Web framework
- **React** - UI library

---

## 📞 Support

- 📧 Email: your-email@example.com
- 🐛 Issues: [GitHub Issues](https://github.com/yourusername/ipl-predictions/issues)
- 💬 Discussions: [GitHub Discussions](https://github.com/yourusername/ipl-predictions/discussions)

---

## 🔗 Links

- [Live Demo](https://your-demo-url.com) (if deployed)
- [API Documentation](http://localhost:8000/docs) (when running locally)
- [Model Card](docs/MODEL_DOCUMENTATION.md)
- [Architecture Diagram](docs/ARCHITECTURE.md)

---

## ⭐ Star History

If you find this project useful, please consider giving it a star! ⭐

---

**Made with ❤️ for Cricket Analytics**

*Last Updated: 2026-06-13*  
*Model Version: 5.0-chronological-calibrated*  
*Documentation Version: 1.0*
