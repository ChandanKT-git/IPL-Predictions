# Development Guide

## Table of Contents
1. [Getting Started](#getting-started)
2. [Project Structure](#project-structure)
3. [Development Workflow](#development-workflow)
4. [Testing](#testing)
5. [Debugging](#debugging)
6. [Contributing](#contributing)

## Getting Started

### Prerequisites
- Python 3.9+
- Node.js 16+
- MongoDB 6.0+
- Redis 7.0+
- Git

### Initial Setup

1. **Clone Repository**
```bash
git clone https://github.com/yourusername/ipl-predictions.git
cd ipl-predictions
```

2. **Backend Setup**
```bash
cd backend

# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Activate (Linux/Mac)
source venv/bin/activate

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

4. **Database Setup**
```bash
# Start MongoDB
mongod --dbpath ./data/db

# Start Redis
redis-server
```

5. **Train Model** (Optional - pre-trained model included)
```bash
cd backend
python train_model.py
```

6. **Run Application**
```bash
# Terminal 1: Backend
cd backend
python -m uvicorn server:app --reload --host 127.0.0.1 --port 8000

# Terminal 2: Frontend
cd frontend
npm start
```

7. **Access Application**
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs

## Project Structure

```
ipl-predictions/
│
├── backend/                 # Python FastAPI backend
│   ├── server.py           # Main API server
│   ├── predictor.py        # ML prediction service
│   ├── features.py         # Feature engineering
│   ├── train_model.py      # Model training script
│   ├── data_manager.py     # Data loading & processing
│   ├── cricbuzz_service.py # External API integration
│   ├── cache_layer.py      # Redis caching
│   ├── observability.py    # Logging & monitoring
│   ├── tests/              # Test suite
│   ├── data/               # Historical data
│   │   └── IPL.csv
│   ├── models.joblib       # Trained model
│   └── requirements.txt    # Python dependencies
│
├── frontend/               # React frontend
│   ├── public/            # Static assets
│   ├── src/
│   │   ├── components/    # React components
│   │   ├── lib/          # Utilities
│   │   ├── App.js        # Main app
│   │   └── index.js      # Entry point
│   ├── package.json      # Node dependencies
│   └── craco.config.js   # Build configuration
│
├── docs/                  # Documentation
│   ├── ARCHITECTURE.md
│   ├── MODEL_DOCUMENTATION.md
│   ├── API_REFERENCE.md
│   └── DEVELOPMENT_GUIDE.md
│
└── README.md             # Project overview
```

## Development Workflow

### Backend Development

#### Adding a New Feature

1. **Create Feature Branch**
```bash
git checkout -b feature/your-feature-name
```

2. **Implement Feature**
```python
# backend/your_feature.py

async def your_feature_function():
    """
    Add docstring explaining what this does.
    """
    # Implementation
    pass
```

3. **Add Route to server.py**
```python
@app.get("/api/your-endpoint")
async def your_endpoint():
    result = await your_feature_function()
    return result
```

4. **Write Tests**
```python
# backend/tests/test_your_feature.py

def test_your_feature():
    result = your_feature_function()
    assert result == expected_value
```

5. **Run Tests**
```bash
pytest backend/tests/test_your_feature.py -v
```

6. **Commit & Push**
```bash
git add .
git commit -m "feat: add your feature description"
git push origin feature/your-feature-name
```

#### Code Style

**Backend follows PEP 8:**
```python
# Good
def calculate_team_strength(team_id: str) -> float:
    """Calculate batting and bowling strength for a team."""
    rating = get_team_rating(team_id)
    return rating

# Bad
def calc_strength(t):
    r=get_rating(t)
    return r
```

**Use type hints:**
```python
from typing import List, Dict, Optional

def get_players(team_id: str) -> List[Dict[str, str]]:
    pass
```

**Format with Black:**
```bash
pip install black
black backend/*.py
```

### Frontend Development

#### Adding a New Component

1. **Create Component File**
```javascript
// frontend/src/components/YourComponent.jsx

import React from 'react';

export const YourComponent = ({ prop1, prop2 }) => {
  return (
    <div className="your-styles">
      {/* Your JSX */}
    </div>
  );
};
```

2. **Import and Use**
```javascript
// frontend/src/App.js

import { YourComponent } from './components/YourComponent';

function App() {
  return (
    <YourComponent prop1="value" prop2={42} />
  );
}
```

#### Code Style

**Use functional components with hooks:**
```javascript
// Good
import React, { useState, useEffect } from 'react';

const MyComponent = () => {
  const [data, setData] = useState([]);
  
  useEffect(() => {
    fetchData().then(setData);
  }, []);
  
  return <div>{data}</div>;
};

// Avoid class components unless necessary
```

**Format with Prettier:**
```bash
npm install --save-dev prettier
npm run format
```

### Database Migrations

**MongoDB is schemaless**, but for consistency:

```javascript
// Example: Adding a new field to predictions
db.predictions.updateMany(
  { new_field: { $exists: false } },
  { $set: { new_field: default_value } }
);
```

### Environment Variables

**Never commit secrets!**

```bash
# .env (gitignored)
CRICBUZZ_API_KEY=your_actual_key
MONGO_URL=mongodb://localhost:27017
```

```bash
# .env.example (committed)
CRICBUZZ_API_KEY=your_cricbuzz_api_key_here
MONGO_URL=mongodb://localhost:27017
```

## Testing

### Backend Tests

**Run all tests:**
```bash
cd backend
pytest
```

**Run specific test:**
```bash
pytest tests/test_predict.py::test_predict_returns_expected_keys
```

**Run with coverage:**
```bash
pytest --cov=. --cov-report=html
```

**Test structure:**
```python
# tests/test_feature.py

import unittest
from your_module import your_function

class TestYourFeature(unittest.TestCase):
    
    def setUp(self):
        """Runs before each test"""
        self.test_data = {...}
    
    def test_feature_returns_correct_type(self):
        result = your_function(self.test_data)
        self.assertIsInstance(result, dict)
    
    def test_feature_handles_edge_case(self):
        result = your_function(None)
        self.assertIsNone(result)
```

### Frontend Tests

**Run tests:**
```bash
cd frontend
npm test
```

**Test structure:**
```javascript
// src/components/__tests__/YourComponent.test.js

import { render, screen } from '@testing-library/react';
import { YourComponent } from '../YourComponent';

test('renders component correctly', () => {
  render(<YourComponent />);
  const element = screen.getByText(/expected text/i);
  expect(element).toBeInTheDocument();
});
```

### Integration Tests

**Test full API flow:**
```python
# tests/test_integration.py

from fastapi.testclient import TestClient
from server import app

client = TestClient(app)

def test_full_prediction_flow():
    # 1. Get teams
    teams_response = client.get("/api/teams")
    assert teams_response.status_code == 200
    
    # 2. Get players
    players_response = client.get("/api/teams/mi/players")
    assert players_response.status_code == 200
    
    # 3. Make prediction
    prediction_response = client.post("/api/predict", json={
        "team_a": "mi",
        "team_b": "csk",
        # ...
    })
    assert prediction_response.status_code == 200
    assert "predicted_score" in prediction_response.json()
```

## Debugging

### Backend Debugging

**Add logging:**
```python
from observability import get_logger

logger = get_logger(__name__)

def your_function():
    logger.info("Starting function")
    logger.debug(f"Variable value: {variable}")
    logger.error("Something went wrong", exc_info=True)
```

**Use debugger:**
```python
import pdb

def your_function():
    pdb.set_trace()  # Execution will pause here
    # Use 'n' to step, 'c' to continue, 'p variable' to print
```

**VS Code launch.json:**
```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Python: FastAPI",
      "type": "python",
      "request": "launch",
      "module": "uvicorn",
      "args": [
        "server:app",
        "--reload",
        "--port",
        "8000"
      ],
      "jinja": true
    }
  ]
}
```

### Frontend Debugging

**Use React DevTools:**
- Install extension: [React DevTools](https://react.dev/learn/react-developer-tools)
- Inspect component state and props

**Console debugging:**
```javascript
console.log('Variable:', variable);
console.table(arrayOfObjects);
console.error('Error occurred:', error);
```

**Network debugging:**
- Open Browser DevTools (F12)
- Go to Network tab
- Filter by "Fetch/XHR"
- Inspect API requests/responses

### Common Issues

#### Backend won't start
```bash
# Check if port is in use
netstat -ano | findstr :8000

# Kill process on port
taskkill /PID <PID> /F

# Check MongoDB is running
mongo --eval "db.runCommand({ ping: 1 })"

# Check Redis is running
redis-cli ping
```

#### Frontend build errors
```bash
# Clear cache
rm -rf node_modules package-lock.json
npm install

# Clear webpack cache
rm -rf .cache
```

#### Model not loading
```bash
# Retrain model
cd backend
python train_model.py

# Check file exists
ls -la models.joblib
```

## Contributing

### Git Workflow

1. **Fork repository** (if external contributor)

2. **Create feature branch**
```bash
git checkout -b feature/your-feature
```

3. **Make changes** with atomic commits
```bash
git add specific_file.py
git commit -m "feat: add feature X"

git add another_file.py
git commit -m "fix: resolve bug Y"
```

4. **Keep branch updated**
```bash
git fetch origin
git rebase origin/main
```

5. **Push and create PR**
```bash
git push origin feature/your-feature
```

### Commit Message Convention

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style (formatting, no logic change)
- `refactor`: Code refactoring
- `test`: Adding/updating tests
- `chore`: Maintenance tasks

**Examples:**
```
feat(backend): add player images to API response

Add image_id field to player objects fetched from Cricbuzz.
Falls back to null if no image available.

Closes #42
```

```
fix(frontend): resolve team logo not displaying

Team logos were not loading due to incorrect image URL.
Updated TeamLogo component to use correct API endpoint.
```

### Code Review Checklist

Before submitting PR:

- [ ] Code follows project style guide
- [ ] All tests pass
- [ ] New features have tests
- [ ] Documentation updated (if needed)
- [ ] No console.log() or print() statements
- [ ] No secrets in code
- [ ] Commit messages follow convention
- [ ] Branch is up-to-date with main

### Pull Request Template

```markdown
## Description
Brief description of what this PR does.

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
How was this tested?
- [ ] Unit tests
- [ ] Integration tests
- [ ] Manual testing

## Screenshots (if UI changes)
[Add screenshots here]

## Checklist
- [ ] Code follows style guide
- [ ] Tests pass
- [ ] Documentation updated
```

---

**Document Version:** 1.0  
**Last Updated:** 2026-06-13  
**Maintained By:** IPL Predictions Team
