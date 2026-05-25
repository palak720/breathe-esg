# Breathe ESG — Data Ingestion & Review Prototype

A Django REST + React application that ingests emissions data from three enterprise source types, normalizes it, and surfaces a review dashboard where analysts can approve rows before they're locked for audit.

**Live demo:** _[your deployed URL here]_

**Credentials:**
- Admin: `admin` / `breathe2024`
- Analyst: `analyst` / `breathe2024`

---

## Architecture

```
backend/                    Django REST API
  apps/
    core/                   Organization, User, auth
    ingestion/              IngestionJob, ParseError, three parsers
      parsers/
        sap.py              SAP SE16/ALV flat file parser
        utility.py          Utility portal CSV parser
        travel.py           Concur/Navan travel CSV parser
    emissions/              EmissionRecord, review workflow

frontend/                   React (Vite + Tailwind)
  src/
    pages/
      Dashboard.jsx         Summary stats and CO2e by scope
      Review.jsx            Record-level approval workflow
      Upload.jsx            File upload for all three source types
      Jobs.jsx              Ingestion job history and lock
```

---

## Local Setup

### Backend

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up environment
cp .env.example .env
# Edit .env if needed (defaults work for local dev with SQLite)

# Run migrations
python manage.py migrate

# Load demo data (creates org, users, and sample records)
python manage.py seed

# Start server
python manage.py runserver
```

API will be at `http://localhost:8000`
Django admin at `http://localhost:8000/admin/`

### Frontend

```bash
cd frontend

# Install dependencies
npm install

# Start dev server (proxies /api to localhost:8000)
npm run dev
```

App will be at `http://localhost:5173`

---

## Deployment (Railway)

1. Push to GitHub
2. Create a new Railway project → "Deploy from GitHub repo"
3. Add a PostgreSQL plugin (Railway auto-sets `DATABASE_URL`)
4. Set environment variables:
   ```
   SECRET_KEY=<generate with: python -c "import secrets; print(secrets.token_hex(32))">
   DEBUG=False
   ALLOWED_HOSTS=your-app.railway.app
   ```
5. Railway picks up `railway.toml` and runs:
   ```
   python manage.py migrate && python manage.py seed && gunicorn breathe.wsgi
   ```

For the React frontend, either:
- **Option A:** Serve from Django — run `npm run build` in frontend/, copy `dist/` to `backend/staticfiles/`, and configure Django to serve it
- **Option B:** Deploy frontend separately on Vercel/Netlify, set `CORS_ALLOWED_ORIGINS` in backend env

---

## API Endpoints

```
POST   /api/auth/token/              Login → JWT
GET    /api/auth/me/                 Current user info

GET    /api/jobs/                    List ingestion jobs
POST   /api/jobs/upload/             Upload file for parsing
GET    /api/jobs/<id>/               Job detail + parse errors

GET    /api/records/                 List records (filterable)
GET    /api/records/summary/         Dashboard stats
POST   /api/records/bulk-review/     Approve/reject multiple records
POST   /api/records/lock/            Lock approved records for audit
GET    /api/records/<id>/            Record detail
PATCH  /api/records/<id>/            Edit normalized fields
POST   /api/records/<id>/review/     Approve / flag / reject
```

### Upload a file

```bash
curl -X POST http://localhost:8000/api/jobs/upload/ \
  -H "Authorization: Bearer <token>" \
  -F "source_type=SAP_FLAT_FILE" \
  -F "file=@your_sap_export.csv"
```

### Review a record

```bash
curl -X POST http://localhost:8000/api/records/<id>/review/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"action": "approve", "note": "Verified against source invoice"}'
```

---

## Documents

- `MODEL.md` — Data model design and rationale (the most important document)
- `DECISIONS.md` — Every ambiguity resolved and why
- `TRADEOFFS.md` — Three things deliberately not built
- `SOURCES.md` — Research behind each data source

---

## Running Tests (if added)

```bash
cd backend
python manage.py test
```
