# CineTracker — Indian & Malayalam Box Office Monorepo

A clean monorepo separating the Python Box Office Data Engine (`/scraper`) and the Real-Time React + TypeScript PWA (`/web`), backed by Supabase (`movies` & `daily_collections`) and scheduled via GitHub Actions (`.github/workflows/scrape_pipeline.yml`).

```text
.
├── .github/workflows/scrape_pipeline.yml   # Hourly automated scrape & sync
├── api/                                    # FastAPI orchestrator & cached REST API
│   ├── main.py                             # /health, /api/scrape/*, /api/movies
│   ├── Dockerfile                          # Koyeb/Render production container
│   └── requirements.txt
├── scraper/                                # Python scraping, reconciliation & Supabase sync engine
│   ├── config/                             # settings.py & sources.yaml
│   ├── database/                           # schema.sql & supabase_sync.py
│   ├── enrichment/                         # tmdb_client.py + JSON cache
│   ├── scrapers/                           # BaseScraper, Sacnilk, Koimoi, XTracker, Aggregator
│   ├── tests/                              # pytest unit tests
│   ├── utils/                              # currency_parser, tweet_parser, title_matcher, models
│   ├── main.py                             # CLI entry point
│   └── requirements.txt
└── web/                                    # React 18 + TypeScript + Vite + Tailwind PWA
    ├── public/icons/                       # PWA icons
    ├── src/                                # Supabase Realtime UI, Recharts, Compare, /admin
    ├── index.html
    ├── package.json
    └── vite.config.ts
```

---

## 1. Database Setup (Supabase)

Run [`scraper/database/schema.sql`](scraper/database/schema.sql) in your Supabase SQL Editor. It provisions:
- `public.movies` & `public.daily_collections` tables, indexes, and `set_updated_at()` triggers
- Row Level Security policies (`anon`/`authenticated` read, `authenticated` admin overrides, `service_role` scraper sync)
- `supabase_realtime` publication membership for `public.movies`

---

## 2. Running `/api` (FastAPI Backend)

```bash
pip install -r api/requirements.txt

# Start FastAPI dev server from repo root
uvicorn api.main:app --reload --port 8000
```

- `GET /health` — Server uptime, scraper state (`idle` / `running`), and `last_run_at`
- `POST /api/scrape/trigger` — Authenticated background scrape trigger (accepts Supabase Admin JWT or `ADMIN_API_SECRET`)
- `GET /api/scrape/status` — Live job state, `last_run_report.json` summary, and recent logs
- `GET /api/movies` — TTL-cached Supabase query endpoint (`?language=...&verdict=...`)
- Deployable to Koyeb or Render directly with [`api/Dockerfile`](api/Dockerfile).

---

## 3. Running `/scraper` (Python Data Engine)

```bash
cd scraper
cp .env.example .env   # Fill SUPABASE_URL, SUPABASE_KEY (service_role), TMDB_API_KEY

python -m venv venv
# Windows: venv\Scripts\activate  |  macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium

# Dry-run without writing to Supabase
python main.py --dry-run --lang malayalam --limit 10

# Live sync (or from repo root: python scraper/main.py)
python main.py

# Unit tests
python -m pytest -v
```

---

## 4. Running `/web` (React + Vite PWA)

```bash
cd web
cp .env.example .env   # Fill VITE_SUPABASE_URL, VITE_SUPABASE_ANON_KEY, VITE_TMDB_API_KEY, VITE_API_BASE_URL

npm install
npm run dev            # Start local dev server
npm run build          # TypeScript check (tsc -b) + production Vite & PWA build
npm run preview        # Preview production dist/ bundle
```

### Frontend Routes
- `/` — Trending Hero Spotlight, Language Filter Pills, Live Movie Grid, and Deep-Dive Analytics Modal (Day-by-Day Chart, India vs. Overseas Donut, ROI Meter, PNG Report Card).
- `/compare` — Side-by-side milestone comparison (`Day 1`, `Weekend 1`, `Week 1`) and overlaid trajectory chart for any 2 movies.
- `/admin` — Supabase Auth-protected Admin Override Console with conflict highlighting (`variance_flag`), financial column editor, `manual_override` lock toggle, and TMDB-assisted manual movie creation.
