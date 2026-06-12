# API Reference

## Base URL
```
Development: http://localhost:8000
Production: https://your-domain.com
```

## Authentication
Currently no authentication required. Cricbuzz API key configured server-side.

## Common Headers
```http
Content-Type: application/json
Accept: application/json
```

## Response Headers
```http
X-Data-Source: live | cache | fallback | mixed
X-Request-ID: uuid
```

---

## Endpoints

### Health Check

#### `GET /api/health`
Check system health and component status.

**Response:**
```json
{
  "status": "ok",
  "subsystems": {
    "mongo": true,
    "cricbuzz_key_set": true,
    "model_loaded": true,
    "model_version": "5.0-chronological-calibrated",
    "csv_loaded": true,
    "cache_entries": 42
  }
}
```

---

### Team Endpoints

#### `GET /api/teams`
List all IPL teams with metadata.

**Response:**
```json
[
  {
    "id": "mi",
    "name": "Mumbai Indians",
    "short_name": "MI",
    "primary_color": "#004BA0",
    "secondary_color": "#D1AB3E",
    "home_venue_id": "wankhede",
    "captain": "Hardik Pandya",
    "titles": 5,
    "rating": 88,
    "cricbuzz_team_id": 58,
    "cricbuzz_squad_id": 971,
    "image_id": "18972",
    "source": "live"
  }
]
```

**Headers:**
- `X-Data-Source`: Indicates if data is from Cricbuzz API, cache, or fallback

#### `GET /api/teams/{team_id}/players`
Get players for a specific team.

**Parameters:**
- `team_id` (path): Team identifier (e.g., "mi", "csk")

**Response:**
```json
[
  {
    "name": "Rohit Sharma",
    "role": "Batsman",
    "country": "India",
    "batting_avg": 28.5,
    "strike_rate": 130.2,
    "wickets": 15,
    "economy": 7.5,
    "image_id": "8874",
    "source": "live"
  }
]
```

---

### Venue Endpoints

#### `GET /api/venues`
List all IPL venues.

**Response:**
```json
[
  {
    "id": "wankhede",
    "name": "Wankhede Stadium",
    "city": "Mumbai",
    "default_pitch": "batting",
    "avg_first_innings": 175.8
  }
]
```

---

### Match Condition Endpoints

#### `GET /api/pitch-types`
Get available pitch types.

**Response:**
```json
[
  {
    "id": "batting",
    "label": "Batting-friendly",
    "score_modifier": 18
  },
  {
    "id": "bowling",
    "label": "Bowling-friendly",
    "score_modifier": -15
  },
  {
    "id": "balanced",
    "label": "Balanced",
    "score_modifier": 0
  }
]
```

#### `GET /api/weather-types`
Get available weather conditions.

**Response:**
```json
[
  {
    "id": "clear",
    "label": "Clear/Sunny",
    "score_modifier": 5
  },
  {
    "id": "overcast",
    "label": "Overcast",
    "score_modifier": -8
  },
  {
    "id": "humid",
    "label": "Humid",
    "score_modifier": 3
  }
]
```

---

### Live Match Endpoints

#### `GET /api/live-matches`
Fetch current live IPL matches from Cricbuzz.

**Response:**
```json
{
  "typeMatches": [
    {
      "matchType": "League",
      "seriesMatches": [
        {
          "seriesAdWrapper": {
            "seriesId": 7607,
            "seriesName": "Indian Premier League 2026",
            "matches": [
              {
                "matchInfo": {
                  "matchId": 89734,
                  "seriesId": 7607,
                  "matchDesc": "23rd Match",
                  "matchFormat": "T20",
                  "startDate": "1781256600000",
                  "state": "In Progress",
                  "team1": {
                    "teamId": 58,
                    "teamName": "Mumbai Indians",
                    "teamSName": "MI"
                  },
                  "team2": {
                    "teamId": 59,
                    "teamName": "Chennai Super Kings",
                    "teamSName": "CSK"
                  },
                  "venueInfo": {
                    "ground": "Wankhede Stadium",
                    "city": "Mumbai"
                  }
                },
                "matchScore": {
                  "team1Score": {
                    "inngs1": {
                      "runs": 145,
                      "wickets": 3,
                      "overs": 15.2
                    }
                  }
                }
              }
            ]
          }
        }
      ]
    }
  ]
}
```

#### `GET /api/upcoming-matches`
Fetch upcoming IPL matches.

**Response:** Same structure as `/api/live-matches`

#### `GET /api/live-match-xi/{match_id}`
Get playing XI for a live match.

**Parameters:**
- `match_id` (path): Cricbuzz match ID

**Response:**
```json
{
  "match_id": 89734,
  "team_a": {
    "team_id": "mi",
    "team_name": "Mumbai Indians",
    "players": [
      {
        "name": "Rohit Sharma",
        "role": "Batsman",
        "image_id": "8874"
      }
    ]
  },
  "team_b": {
    "team_id": "csk",
    "team_name": "Chennai Super Kings",
    "players": [...]
  }
}
```

#### `GET /api/live-match-score/{match_id}`
Get current score for a live match.

**Response:**
```json
{
  "match_id": 89734,
  "status": "In Progress",
  "batting_team": "Mumbai Indians",
  "score": "145/3",
  "overs": "15.2",
  "run_rate": "9.46",
  "last_updated": "2026-06-13T10:30:00Z"
}
```

#### `GET /api/live-match-score/{match_id}/stream`
Server-Sent Events stream for real-time score updates.

**Headers:**
- `Accept: text/event-stream`

**Response:** SSE stream with updates every 10 seconds

---

### Prediction Endpoints

#### `POST /api/predict`
Generate a match prediction.

**Request Body:**
```json
{
  "team_a": "mi",
  "team_b": "csk",
  "batting_team": "mi",
  "toss_winner": "mi",
  "venue": "wankhede",
  "pitch": "batting",
  "weather": "clear",
  "playing_xi_a": [
    "Rohit Sharma",
    "Ishan Kishan",
    "Suryakumar Yadav",
    "Tilak Varma",
    "Hardik Pandya",
    "Tim David",
    "Romario Shepherd",
    "Kumar Kartikeya",
    "Piyush Chawla",
    "Jasprit Bumrah",
    "Jason Behrendorff"
  ],
  "playing_xi_b": [
    "Ruturaj Gaikwad",
    "Devon Conway",
    "Ajinkya Rahane",
    "Shivam Dube",
    "Ravindra Jadeja",
    "MS Dhoni",
    "Moeen Ali",
    "Deepak Chahar",
    "Tushar Deshpande",
    "Matheesha Pathirana",
    "Maheesh Theekshana"
  ]
}
```

**Response:**
```json
{
  "id": "15d1f59f-a410-464b-8623-f69f293e431e",
  "predicted_score": 175,
  "score_range_low": 145,
  "score_range_high": 205,
  "expected_run_rate": 8.75,
  "win_probability_batting": 65,
  "win_probability_bowling": 35,
  "match_outcome": "MI favored — 65% win probability",
  "batting_team_strength": 88,
  "bowling_team_strength": 85,
  "phase_breakdown": {
    "powerplay_runs": 48,
    "middle_overs_runs": 72,
    "death_overs_runs": 55
  },
  "batting_team_id": "mi",
  "bowling_team_id": "csk",
  "model_version": "5.0-chronological-calibrated",
  "mode": "first-innings",
  "interval_coverage": 0.8,
  "contributions": [
    {
      "feature": "batting_team_strength",
      "label": "Batting team strength",
      "value": 88.0,
      "importance": 0.28,
      "magnitude": 0.28,
      "direction": 1,
      "z_score": 1.5
    }
  ],
  "h2h": {
    "teams": ["mi", "csk"],
    "last_5": [...],
    "win_count": {"mi": 15, "csk": 18},
    "total_matches": 33,
    "avg_score": 162.5
  },
  "matchups": [
    {
      "batter": "SA Yadav",
      "bowler": "RA Jadeja",
      "balls": 74,
      "runs": 71,
      "dismissals": 3,
      "strike_rate": 95.9
    }
  ]
}
```

**Validation Errors:**
```json
{
  "detail": [
    {
      "loc": ["body", "playing_xi_a"],
      "msg": "Playing XI must have exactly 11 players",
      "type": "value_error"
    }
  ]
}
```

#### `POST /api/whatif`
Scenario analysis - predict outcomes for different conditions.

**Request:** Same as `/api/predict`  
**Response:** Same as `/api/predict`

Used for slider-based "what-if" exploration in UI.

#### `POST /api/analysis`
Get AI-powered match analysis (requires GROQ_API_KEY).

**Request:** Same as `/api/predict`

**Response:**
```json
{
  "analysis": "Mumbai Indians have a slight advantage..."
}
```

---

### Prediction History Endpoints

#### `GET /api/predictions/recent?limit=10`
Get recent predictions.

**Query Parameters:**
- `limit` (optional): Number of predictions to return (default: 10)

**Response:**
```json
[
  {
    "id": "15d1f59f-a410-464b-8623-f69f293e431e",
    "created_at": "2026-06-13T10:00:00Z",
    "teams": ["mi", "csk"],
    "predicted_score": 175,
    "win_probability_batting": 65,
    "is_favorite": false
  }
]
```

#### `GET /api/predictions/{prediction_id}`
Get a specific prediction by ID.

**Response:** Full prediction object (same as POST /api/predict response)

#### `POST /api/predictions/{prediction_id}/favorite`
Toggle favorite status for a prediction.

**Response:**
```json
{
  "id": "15d1f59f-a410-464b-8623-f69f293e431e",
  "is_favorite": true
}
```

#### `POST /api/predictions/{prediction_id}/reconcile`
Update prediction with actual match outcome.

**Request Body:**
```json
{
  "actual_score": 178,
  "actual_winner": "mi",
  "actual_margin": "15 runs"
}
```

**Response:**
```json
{
  "id": "15d1f59f-a410-464b-8623-f69f293e431e",
  "predicted_score": 175,
  "actual_score": 178,
  "prediction_error": 3,
  "win_prediction_correct": true
}
```

---

### Analytics Endpoints

#### `GET /api/calibration`
Get model calibration metrics.

**Response:**
```json
{
  "model_version": "5.0-chronological-calibrated",
  "total_predictions": 214,
  "avg_prediction_error": 38.5,
  "calibration_buckets": [
    {
      "predicted_prob_range": [0.5, 0.6],
      "actual_win_rate": 0.58,
      "count": 45
    }
  ],
  "brier_score": 0.21,
  "coverage_80": 0.785
}
```

#### `GET /api/head-to-head/{team_a}/{team_b}`
Get head-to-head statistics between two teams.

**Response:**
```json
{
  "teams": ["mi", "csk"],
  "total_matches": 33,
  "team_a_wins": 15,
  "team_b_wins": 18,
  "last_5": [
    {
      "year": 2025,
      "winner": "mi",
      "margin": "9 wickets",
      "venue": "Wankhede Stadium"
    }
  ],
  "avg_score": 162.5,
  "season_aggregates": [...]
}
```

---

### Admin Endpoints

#### `POST /api/admin/cache/clear`
Clear application cache (requires admin auth in production).

**Response:**
```json
{
  "status": "ok",
  "cleared_keys": 42
}
```

#### `GET /api/image/{image_id}?p=thumb`
Proxy Cricbuzz images to avoid CORS issues.

**Query Parameters:**
- `p` (optional): Image size ("thumb", "medium", "large")

**Response:** Image binary data

---

## Error Responses

### 400 Bad Request
```json
{
  "detail": "Playing XI must have exactly 11 players"
}
```

### 404 Not Found
```json
{
  "detail": "Prediction not found"
}
```

### 500 Internal Server Error
```json
{
  "detail": "Model prediction failed"
}
```

---

## Rate Limiting

Currently no rate limiting. Recommended for production:
- 100 requests/minute per IP
- 1000 requests/hour per IP

---

## Pagination

Currently not implemented. All list endpoints return complete results.

For future:
```
GET /api/predictions/recent?page=1&limit=20
```

---

## Webhooks

Not currently supported. Future feature for prediction updates.

---

## SDK / Client Libraries

### JavaScript (Axios)
```javascript
import axios from 'axios';

const api = axios.create({
  baseURL: 'http://localhost:8000/api',
  timeout: 30000
});

const prediction = await api.post('/predict', {
  team_a: 'mi',
  team_b: 'csk',
  // ...
});
```

### Python (httpx)
```python
import httpx

async with httpx.AsyncClient(base_url='http://localhost:8000/api') as client:
    response = await client.post('/predict', json={
        'team_a': 'mi',
        'team_b': 'csk',
        # ...
    })
    prediction = response.json()
```

---

## WebSocket / Server-Sent Events

### Live Score Stream
```javascript
const eventSource = new EventSource('http://localhost:8000/api/live-match-score/89734/stream');

eventSource.onmessage = (event) => {
  const score = JSON.parse(event.data);
  console.log('Score update:', score);
};
```

---

**API Version:** 1.0  
**Last Updated:** 2026-06-13  
**OpenAPI Spec:** Available at `/docs` (Swagger UI)
