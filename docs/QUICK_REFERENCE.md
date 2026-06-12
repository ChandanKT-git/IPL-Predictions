# Quick Reference Guide

> 📌 This is a condensed cheat sheet for common tasks. For detailed information, see the other documentation files.

## 🚀 Quick Start Commands

### Start Everything
```bash
# Terminal 1: MongoDB
mongod --dbpath ./data/db

# Terminal 2: Redis
redis-server

# Terminal 3: Backend
cd backend && python -m uvicorn server:app --reload --port 8000

# Terminal 4: Frontend
cd frontend && npm start
```

### URLs
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs

---

## 📁 File Locations

| What | Where |
|------|-------|
| Model file | `backend/models.joblib` |
| Model metrics | `backend/models_metrics.json` |
| Historical data | `backend/data/IPL.csv` |
| Environment config | `backend/.env`, `frontend/.env` |
| API routes | `backend/server.py` |
| ML training | `backend/train_model.py` |
| Feature engineering | `backend/features.py` |
| React components | `frontend/src/components/` |

---

## 🔌 Common API Calls

### Get Teams
```bash
curl http://localhost:8000/api/teams
```

### Get Players
```bash
curl http://localhost:8000/api/teams/mi/players
```

### Make Prediction
```bash
curl -X POST http://localhost:8000/api/predict \
  -H "Content-Type: application/json" \
  -d @prediction_payload.json
```

### Get Live Matches
```bash
curl http://localhost:8000/api/live-matches
```

### Check Health
```bash
curl http://localhost:8000/api/health
```

---

## 🧪 Testing Commands

```bash
# Backend: Run all tests
cd backend && pytest

# Backend: With coverage
pytest --cov=. --cov-report=html

# Backend: Specific test
pytest tests/test_predict.py::test_name -v

# Frontend: Run tests
cd frontend && npm test

# Frontend: With coverage
npm test -- --coverage
```

---

## 🔧 Common Issues & Fixes

### Port Already in Use
```bash
# Find process on port 8000
netstat -ano | findstr :8000

# Kill process (Windows)
taskkill /PID <PID> /F

# Kill process (Linux/Mac)
kill -9 <PID>
```

### MongoDB Not Starting
```bash
# Check MongoDB status
mongo --eval "db.runCommand({ ping: 1 })"

# Start MongoDB
mongod --dbpath ./data/db

# Check if port 27017 is in use
netstat -ano | findstr :27017
```

### Redis Not Starting
```bash
# Check Redis
redis-cli ping
# Should return: PONG

# Start Redis
redis-server

# Check if port 6379 is in use
netstat -ano | findstr :6379
```

### Model Not Loading
```bash
# Retrain model
cd backend
python train_model.py

# Check file exists
ls -la models.joblib

# Check file size (should be ~45MB)
du -sh models.joblib
```

### Frontend Build Errors
```bash
# Clear everything
rm -rf node_modules package-lock.json

# Reinstall
npm install

# Clear webpack cache
rm -rf .cache
```

---

## 📊 Model Information

### Current Model: v5.0-chronological-calibrated

- **Test MAE**: 38.5 runs
- **Win Accuracy**: 65.2%
- **Brier Score**: 0.21
- **Coverage (80%)**: 78.5%
- **Training Size**: 574 matches (≤2023)
- **Test Size**: 214 matches (≥2025)

### Feature Importance (Top 5)

1. **Team Batting Rating** (0.28)
2. **Recent Form** (0.22)
3. **Toss Won by Batting** (0.18)
4. **Venue** (0.15)
5. **H2H Win Share** (0.12)

---

## 🌐 Environment Variables

### Backend `.env`
```bash
CRICBUZZ_API_KEY=your_key
RAPIDAPI_HOST=cricbuzz-cricket.p.rapidapi.com
MONGO_URL=mongodb://localhost:27017
DB_NAME=ipl_predictions
REDIS_URL=redis://localhost:6379
GROQ_API_KEY=optional_key
```

### Frontend `.env`
```bash
REACT_APP_BACKEND_URL=http://localhost:8000
```

---

## 📝 Commit Message Format

```
<type>(<scope>): <subject>

Types: feat, fix, docs, style, refactor, test, chore
Examples:
  feat(backend): add player images
  fix(frontend): resolve logo display issue
  docs: update API reference
```

---

## 🐛 Debug Mode

### Backend
```python
# Add to code
import pdb; pdb.set_trace()

# Or use logging
from observability import get_logger
logger = get_logger(__name__)
logger.debug(f"Variable: {variable}")
```

### Frontend
```javascript
// Console debugging
console.log('Variable:', variable);
console.table(arrayOfObjects);

// React DevTools
// Install browser extension, then inspect components
```

---

## 💾 Database Operations

### MongoDB

```bash
# Connect to MongoDB
mongo

# Use database
use ipl_predictions

# Show collections
show collections

# Count predictions
db.predictions.countDocuments()

# Find recent predictions
db.predictions.find().sort({created_at: -1}).limit(5)

# Clear collection
db.predictions.deleteMany({})
```

### Redis

```bash
# Connect to Redis
redis-cli

# List all keys
KEYS *

# Get key value
GET key_name

# Delete key
DEL key_name

# Clear all
FLUSHALL

# Get cache stats
INFO stats
```

---

## 📦 Dependencies

### Update Backend Dependencies
```bash
cd backend
pip list --outdated
pip install --upgrade package_name
pip freeze > requirements.txt
```

### Update Frontend Dependencies
```bash
cd frontend
npm outdated
npm update package_name
npm audit fix
```

---

## 🚢 Deployment Checklist

- [ ] Update `.env` with production values
- [ ] Set `MONGO_URL` to production MongoDB
- [ ] Set `REDIS_URL` to production Redis
- [ ] Update `REACT_APP_BACKEND_URL` to production API URL
- [ ] Build frontend: `npm run build`
- [ ] Test API endpoints
- [ ] Run backend tests: `pytest`
- [ ] Enable HTTPS
- [ ] Set up monitoring
- [ ] Configure backups (MongoDB)
- [ ] Set up logging aggregation
- [ ] Configure rate limiting
- [ ] Update CORS origins

---

## 📚 Documentation Index

| Document | Description |
|----------|-------------|
| [README.md](../README.md) | Project overview |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture |
| [MODEL_DOCUMENTATION.md](MODEL_DOCUMENTATION.md) | ML model details |
| [API_REFERENCE.md](API_REFERENCE.md) | API endpoints |
| [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) | Development workflow |
| [QUICK_REFERENCE.md](QUICK_REFERENCE.md) | This document |

---

## 🔗 Useful Links

- **FastAPI Docs**: https://fastapi.tiangolo.com
- **React Docs**: https://react.dev
- **scikit-learn**: https://scikit-learn.org
- **MongoDB Manual**: https://docs.mongodb.com
- **Redis Commands**: https://redis.io/commands
- **Cricbuzz API**: https://rapidapi.com/cricbuzz/api/cricbuzz-cricket

---

## ⚡ Performance Tips

### Backend
- Use `--workers 4` for production (Uvicorn)
- Enable response compression
- Use connection pooling (MongoDB, Redis)
- Cache expensive computations
- Use async/await for I/O operations

### Frontend
- Use React.lazy() for code splitting
- Optimize images (WebP, lazy loading)
- Enable service worker for caching
- Minimize bundle size (`npm run build`)
- Use production build

---

## 🎯 Common Tasks

### Retrain Model
```bash
cd backend
python train_model.py
# Wait ~5 minutes
# Check models.joblib and models_metrics.json
```

### Add New Feature
1. Update `features.py` with new feature function
2. Update `train_model.py` to include new feature
3. Retrain model
4. Update tests

### Add New API Endpoint
1. Add route to `server.py`
2. Add function to `frontend/src/lib/api.js`
3. Use in React component
4. Write tests

### Update Team/Player Data
1. Modify `backend/data_resolver.py`
2. Update ID mappings in `id_mapper.py`
3. Restart backend
4. Clear cache: `curl -X POST http://localhost:8000/api/admin/cache/clear`

---

**Quick Reference Version:** 1.0  
**Last Updated:** 2026-06-13
