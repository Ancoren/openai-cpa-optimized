# OpenAI Codex Manager — Optimized Edition

This is a refactored and optimized version of the [wenfxl/openai-cpa](https://github.com/wenfxl/openai-cpa) project.

## 🎯 What Was Optimized

### 1. Configuration Management (`app/config.py`)
**Before:** 80+ global variables, `reload_all_configs()` with 50+ `global` declarations, fragile string-based config access.

**After:** Pydantic Settings v2 with:
- Type-safe nested configs (CPA, Sub2API, Proxy, DB)
- Auto-validation and defaults
- Environment variable override (`APP_WEB_PASSWORD=xxx`)
- No global variable pollution

### 2. Database Layer (`models/database.py`)
**Before:** String replacement for SQLite↔MySQL (`?` → `%s`, `AUTOINCREMENT` → `AUTO_INCREMENT`), no connection pooling, new connection per query.

**After:** SQLAlchemy 2.0 with:
- Declarative ORM models
- Connection pooling (configurable pool_size / max_overflow)
- Automatic WAL mode for SQLite
- No SQL string manipulation
- Transaction safety via context managers

### 3. HTTP Client (`utils/http_client.py`)
**Before:** Scattered retry logic in `_post_form`, `_post_with_retry`, `upload_to_cpa_integrated`, etc. No circuit breaker.

**After:** Unified `HttpClient` with:
- Exponential backoff + jitter
- Per-domain circuit breaker
- Error classification (TRANSIENT / AUTH / RATE_LIMIT / CLIENT / NETWORK)
- Session reuse for connection pooling

### 4. Logging (`utils/logger.py`)
**Before:** `builtins.print = web_print` — global monkey-patching, log history in `deque` with manual management.

**After:** Loguru with:
- No monkey-patching
- Async-safe queue-based sinks
- File rotation (10MB / 7 days)
- Memory buffer for WebSocket streaming
- JSON format ready for log aggregation

### 5. Engine Architecture (`services/engine.py`)
**Before:** Monolithic `core_engine.py` with global `run_stats`, implicit state transitions.

**After:** State machine (`IDLE` → `RUNNING` → `STOPPING` → `IDLE`) with:
- Explicit `EngineState` enum
- `EngineStats` with atomic counters
- Pluggable mode handlers (Normal / CPA / Sub2API)
- Clean separation of concerns

### 6. API Routes (`api/routes.py`)
**Before:** 1200+ line single file, manual auth checks, ad-hoc response shapes.

**After:**
- Dependency injection (`Depends(verify_token)`)
- Pydantic v2 request/response models
- `/health` endpoint for Docker / K8s health checks
- ~1/3 the code size

### 7. Docker (`Dockerfile` + `docker-compose.yml`)
**Before:** Single-stage build, root user, no health check, mounts Docker socket.

**After:**
- Multi-stage build (smaller image)
- Non-root user (`appuser`)
- Built-in health check
- No Docker socket mount (security)
- `restart: unless-stopped`

## 📁 Project Structure

```
.
├── main.py                  # Entry point with lifespan management
├── app/
│   └── config.py            # Pydantic Settings config
├── api/
│   └── routes.py            # FastAPI routes
├── models/
│   └── database.py          # SQLAlchemy models + DB manager
├── services/
│   ├── engine.py            # RegEngine state machine
│   ├── registration.py      # Registration worker
│   ├── cpa_manager.py       # CPA mode (stub)
│   └── sub2api_manager.py   # Sub2API mode (stub)
├── utils/
│   ├── http_client.py       # Unified HTTP client
│   ├── logger.py            # Structured logging
│   └── ...                  # Other utilities
├── static/                  # Frontend assets
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## 🚀 Quick Start

```bash
# 1. Clone and enter
git clone https://github.com/Ancoren/openai-cpa-optimized.git
cd openai-cpa-optimized

# 2. Configure
cp config.example.yaml data/config.yaml
# Edit data/config.yaml with your settings

# 3. Run locally
pip install -r requirements.txt
python main.py

# 4. Or use Docker
docker-compose up -d
```

Web console: http://127.0.0.1:8000  
Default password: `admin` (change via `APP_WEB_PASSWORD`)

### Built-in Legacy Components

The following original components are **already included** in this repository:

- **`utils/email_providers/`** — All 10+ email backends (mail_service, luckmail, duckmail, tempmail, etc.)
- **`utils/integrations/`** — AI service, HeroSMS, Clash manager, Sub2API client, TG notifier
- **`utils/auth_core*.so`** — Compiled Sentinel challenge extension (Linux x86_64, aarch64, macOS)

No manual copying needed. The compatibility adapter (`services/email_adapter.py`) bridges them automatically.

## 🔧 Environment Variables

| Variable | Description | Default |
|---|---|---|
| `APP_WEB_PASSWORD` | Web UI password | `admin` |
| `APP_LOG_LEVEL` | Log level | `INFO` |
| `DB_TYPE` | Database type | `sqlite` |
| `DB_HOST` | MySQL host | `127.0.0.1` |
| `DB_PORT` | MySQL port | `3306` |
| `DB_USER` | MySQL user | `root` |
| `DB_PASS` | MySQL password | `` |
| `DB_NAME` | MySQL database | `wenfxl_manager` |

## 🚀 Auto-Push to Codex Hub

Newly registered accounts can be **automatically pushed** to [Codex Hub](https://github.com/Ancoren/codex-hub) in real-time.

### Configuration

Add to `data/config.yaml` (or use env vars):

```yaml
hub:
  enable: true
  url: "http://127.0.0.1:8080"      # Codex Hub address
  admin_password: "your-hub-admin"   # Hub admin password
  api_key: ""                        # Hub gateway API key (optional)
  auto_push_on_reg: true             # Push immediately after registration
  retry_times: 3
  retry_delay: 5
```

Or via environment variables:

```bash
APP_HUB__ENABLE=true
APP_HUB__URL=http://127.0.0.1:8080
APP_HUB__ADMIN_PASSWORD=your-hub-admin
```

### How It Works

1. Registration worker completes OAuth → gets `access_token` + `refresh_token`
2. `db.save_account()` saves to local SQLite
3. **Fire-and-forget** background thread enqueues the account to Hub
4. Hub Pusher logs in, obtains admin token, and `POST /admin/accounts`
5. If Hub is down or push fails, it retries silently — **never blocks registration**

### Manual Import (Fallback)

If auto-push is disabled or you have historical accounts, use Codex Hub's `/admin/import/sqlite` endpoint:

```bash
curl -X POST http://localhost:8080/admin/import/sqlite \
  -H "Authorization: Bearer YOUR_HUB_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"db_path": "/path/to/cpa/data/data.db", "skip_reg_only": true}'
```

| Metric | Before | After |
|---|---|---|
| Config reload | 400+ lines, error-prone | Type-safe, validated |
| DB connection | Per-query create/close | Pooled, reusable |
| HTTP retry | Inline, duplicated | Unified with circuit breaker |
| Image size | ~500MB+ | ~150MB (multi-stage) |
| Log handling | Monkey-patched print | Structured, async-safe |
| Startup time | Slow (yaml string ops) | Fast (pydantic parsing) |

## 🧪 Testing

```bash
pytest tests/
```

## ⚠️ Disclaimer

This optimized version maintains the original project's license and disclaimers. Use responsibly and in compliance with all applicable laws and platform Terms of Service.
