# Anga — Weather for Kenya

**Anga** (Swahili for *sky*) shows current weather for Kenyan counties and towns.

The visible product is a calm, responsive weather page whose atmosphere reacts to the
actual conditions. The engineering underneath it is the real subject: a Django service
that sits between users and the [Weather-AI API](https://weather-ai.co/docs) and manages
upstream consumption through **server-side caching, request coalescing, rate-limit
awareness and graceful degradation**.

The governing idea:

> A user request does not have to become an upstream request.

---

## Table of contents

- [The problem](#the-problem)
- [What the Weather-AI docs actually say](#what-the-weather-ai-docs-actually-say)
- [Architecture](#architecture)
- [Request flows](#request-flows)
- [Caching strategy](#caching-strategy)
- [Choosing the TTL](#choosing-the-ttl-the-arithmetic)
- [Request coalescing](#request-coalescing)
- [Rate-limit strategy](#rate-limit-strategy)
- [Honest freshness](#honest-freshness)
- [API reference](#api-reference)
- [Security](#security)
- [Tech stack and why](#tech-stack-and-why)
- [Local setup](#local-setup)
- [Environment variables](#environment-variables)
- [Testing](#testing)
- [Deployment](#deployment)
- [Trade-offs](#trade-offs)
- [Future improvements](#future-improvements)

---

## The problem

The naive version of this app calls Weather-AI once per page view:

```
1 user    ->  1 upstream request
100 users ->  100 upstream requests
1,000 users -> 1,000 upstream requests
```

That fails for three separate reasons, and the third is specific to this provider.

1. **It is wasteful.** A hundred people asking about Nairobi within the same minute get a
   hundred identical answers. Weather does not change a hundred times a minute.
2. **It is fragile.** Every user request is exposed to upstream latency and failure. If
   Weather-AI is slow or down, the product is slow or down.
3. **It exhausts the quota almost immediately.** Weather-AI's rate limit is **monthly**,
   not per-second. The free tier is **1,000 requests per month** — roughly **33 upstream
   calls per day, across every location combined**. A naive implementation burns a month's
   budget in an afternoon, and the resulting `429` does not clear in sixty seconds. It
   clears at `X-RateLimit-Reset`, potentially **days** later.

That third point reshapes the whole design. Against a per-second limit, you back off for a
moment and retry. Against a monthly quota, being rate-limited is a **sustained outage you
inflicted on yourself**, and the only defences are to not get there and to still be useful
once you do.

---

## What the Weather-AI docs actually say

Everything below was verified against <https://weather-ai.co/docs> and by probing the live
API, rather than assumed.

**Base URL** `https://api.weather-ai.co` · **Auth** `Authorization: Bearer wai_<key>`

Verified live — an unauthenticated request returns:

```console
$ curl -i "https://api.weather-ai.co/v1/weather?lat=-1.2921&lon=36.8219"
HTTP/1.1 401 Unauthorized
{"error":"Missing Authorization header. Use: Bearer <api_key>"}
```

### `GET /v1/weather`

| Param   | Type    | Required | Notes                                        |
| ------- | ------- | -------- | -------------------------------------------- |
| `lat`   | float   | **yes**  | e.g. `-1.2921`                               |
| `lon`   | float   | **yes**  | e.g. `36.8219`                               |
| `days`  | integer | no       | 1–7 Free, 1–14 Pro, 1–16 Scale. Default `7`  |
| `ai`    | boolean | no       | Default **`true`** — spends the AI quota     |
| `units` | string  | no       | `metric` / `imperial`. Default `metric`      |
| `lang`  | string  | no       | `en`, `sw`. Default `en`                     |

Three findings from the docs materially shaped this project:

**1. There is no location-name lookup.** `/v1/weather` accepts coordinates only, and
`/v1/ip-lookup` (geocoding) is Pro-and-above. So a "search for Nairobi" feature has to be
served by *us*. That is why PostgreSQL holds a **Kenya gazetteer** — 47 counties plus 52
major towns with coordinates and aliases — and why searching costs zero upstream quota.

**2. The sibling endpoints are not cheaper.** `/v1/forecast`, `/v1/current`, `/v1/daily`
and `/v1/hourly` all *"delegate to the same handler as `/v1/weather`"* and return the same
shape. There is no lighter "current conditions only" call, so `/v1/weather` is our single
integration and `days=1` keeps the payload small.

**3. `ai=true` is the default and spends a second, much smaller quota** (200/month on
free). Anga does not use the AI summary, so it sends **`ai=false`** on every call. The docs
say this explicitly: *"Add `?ai=false` to skip Gemini AI summaries and preserve your AI
quota."*

### Rate limiting

```
X-RateLimit-Limit:     1000        # monthly cap
X-RateLimit-Remaining: 987
X-RateLimit-Reset:     1717977600  # unix epoch
```

Limits reset on a **30-day rolling period from the subscription date**, not the calendar
month. Documented plans: Free 1,000/mo (200 AI), Pro 50,000/mo, Scale 500,000/mo.

### Error codes

| Status | Meaning             | Documented cause                              |
| ------ | ------------------- | --------------------------------------------- |
| 400    | Bad Request         | Missing required parameters                   |
| 401    | Unauthorized        | Missing, malformed or revoked key             |
| 403    | Forbidden           | Plan does not include the feature             |
| 429    | Too Many Requests   | Monthly quota exceeded — check `X-RateLimit-Reset` |
| 500    | Internal Error      | Server-side issue                             |
| 503    | Service Unavailable | Database unreachable                          |

Error bodies use `{"error": "..."}`.

### ⚠️ The one thing the docs do not specify

**Weather-AI does not publish a response-body schema.** There is no OpenAPI document
(`/openapi.json` 404s) and the docs show sample bodies only for `/v1/ip-lookup` and the
tree-analysis endpoints. Since inventing field names would be worse than admitting the
gap, every assumption about the upstream body is confined to a single module,
[`backend/weather/adapter.py`](backend/weather/adapter.py), which maps each field from a
list of candidate paths.

To pin it down against a real key — one request, then the candidate lists collapse to the
verified path each:

```bash
python manage.py probe_upstream --lat -1.2864 --lon 36.8172 --save raw.json
```

It prints the raw body, the adapter's interpretation, any field that failed to resolve,
and the observed quota. Nothing outside `adapter.py` needs to change afterwards.

---

## Architecture

```
                     ┌───────────────────────────┐
                     │      React (Vercel)       │
                     │                           │
                     │  Location search          │
                     │  Weather-reactive backdrop│
                     │  Freshness always shown   │
                     └─────────────┬─────────────┘
                                   │  HTTPS, no API key in the browser
                                   ▼
                     ┌───────────────────────────┐        ┌──────────────────┐
                     │    Django + DRF (Render)  │───────▶│   PostgreSQL     │
                     │                           │        │                  │
                     │  Validate & normalise     │        │  Kenya gazetteer │
                     │  Throttle (per client)    │        │  47 counties     │
                     │  Map errors to codes      │        │  52 towns        │
                     └─────────────┬─────────────┘        └──────────────────┘
                                   │
                                   ▼
                     ┌───────────────────────────┐
                     │      Redis (Render)       │
                     │                           │
                     │  Fresh  30 min            │
                     │  Stale   6 h  (fallback)  │
                     │  Single-flight locks      │
                     │  Quota + circuit breaker  │
                     └─────────────┬─────────────┘
                                   │  cache miss ONLY
                                   ▼
                     ┌───────────────────────────┐
                     │      Weather-AI API       │
                     │  /v1/weather?lat&lon      │
                     │  ai=false, days=1         │
                     └───────────────────────────┘
```

The browser never talks to Weather-AI. The API key exists only in the backend environment.

### Module layout

| Path | Responsibility |
| ---- | -------------- |
| `weather/service.py` | **The orchestrator.** Cache → breaker → coalesce → fetch → degrade |
| `weather/cache.py` | Cache keys and the fresh/stale envelope |
| `weather/quota.py` | `X-RateLimit-*` tracking and the circuit breaker |
| `weather/client.py` | HTTP transport only. One request, classified. No retries |
| `weather/adapter.py` | Upstream shape → our payload, and condition classification |
| `weather/views.py` | Thin HTTP layer: validate, call service, map exceptions |
| `weather/metrics.py` | Cache/upstream counters for `/api/meta/stats/` |
| `locations/` | Kenya gazetteer: model, normalisation, search |

Transport is separate from policy, which is why the entire caching layer is testable
without a network.

---

## Request flows

### A — Fresh cache hit (the common case)

```
User ──▶ Django ──▶ Redis: fresh (age 4 min < 30 min TTL) ──▶ respond
                                                              Weather-AI NOT called
```
`meta.status = "cached"`, typically a few milliseconds.

### B — Cache miss

```
User ──▶ Django ──▶ Redis: empty ──▶ acquire lock ──▶ Weather-AI 200
                                  ──▶ store (6 h retention) ──▶ respond
```
`meta.status = "live"`.

### C — 50 simultaneous users, cold cache

```
50 users ──▶ Django ──▶ 1 wins the lock ──▶ ONE Weather-AI request
                        49 wait for the result ──▶ all 50 get the same reading
```
Verified with 30 real concurrent HTTP requests — see [Request coalescing](#request-coalescing).

### D — Expired cache, upstream healthy

```
User ──▶ Redis: 41 min old (stale) ──▶ Weather-AI 200 ──▶ replace ──▶ respond "live"
```

### E — Expired cache, upstream returns 429

```
User ──▶ Weather-AI 429
      ──▶ read X-RateLimit-Reset, open breaker until then
      ──▶ NO retry
      ──▶ serve stale, labelled
```
Returns **HTTP 200** with `is_stale: true` and `fallback_reason: "rate_limited"`. Every
subsequent request short-circuits at the breaker without touching the network.

### F — No cache, upstream unavailable

```
User ──▶ no cached data + upstream failing ──▶ HTTP 503 + Retry-After
```
Clean `weather_unavailable` / `rate_limited` code; the frontend renders a human message.

**All six flows are covered by tests**, and E, F and C were additionally verified against a
running server (below).

---

## Caching strategy

### Cache keys

```
anga:weather:v1:{units}:{slug}
└──┬─┘ └──┬──┘ └┬┘ └─┬─┘ └─┬─┘
   │      │     │    │     └── canonical location, e.g. "nairobi"
   │      │     │    └──────── metric | imperial (different upstream responses)
   │      │     └───────────── payload schema version
   │      └─────────────────── namespace
   └────────────────────────── Django KEY_PREFIX
```

**Normalisation** (`locations/normalize.py`) is what makes the cache actually work.
`"Nairobi"`, `"nairobi"` and `"  NAIROBI  "` must not become three entries:

| Input | Key |
| ----- | --- |
| `"  NAIROBI  "` | `nairobi` |
| `"Murang'a"` / `"Murang’a"` | `muranga` |
| `"Homa Bay"` | `homa-bay` |
| `"Nairobi City"` (alias) | `nairobi` |

Aliases resolve to the canonical row *before* the key is built, so `Diani` and `Ukunda`
share one cache entry rather than each costing an upstream request.

Normalisation is also a **security boundary**. The result becomes part of a cache key, so
raw user input never reaches the cache backend: input is length-capped at 64 characters and
restricted to letters, digits, spaces, hyphens, apostrophes and periods. Control characters
(CRLF), Redis glob and hash-tag characters, and path traversal are rejected outright, and
the output is guaranteed to match `^[a-z0-9-]+$`.

`v1` is a payload schema version — changing the response shape means bumping it, which
retires every old entry without a manual flush.

### One entry, two lifetimes

Rather than keeping a short-lived "fresh" key alongside a long-lived "stale" copy and
keeping them in sync, Anga stores **one entry with the long retention**, stamped with
`fetched_at`. Freshness is derived from its age:

```
age < 30 min           →  FRESH   serve as current
30 min ≤ age < 6 h     →  STALE   fallback only, always labelled
age ≥ 6 h              →  gone    Redis has expired it
```

One write, no divergence between two copies, and the exact data age is always available to
report honestly to the client.

### Invalidation

There is no manual invalidation endpoint, deliberately — it would be an unauthenticated way
to force upstream traffic. Entries leave the cache by TTL expiry, by a successful refetch
overwriting them, or by a `v1` version bump.

---

## Choosing the TTL: the arithmetic

Weather-AI's documentation gives no caching guidance, so the TTL was derived rather than
guessed. The binding constraint is the **monthly** quota.

Free tier: **1,000 requests/month ÷ 30 days ≈ 33 upstream calls per day, total.**

Worst case for a *single* continuously-requested location:

| TTL | Max upstream calls/day for ONE location | vs. the 33/day budget |
| --- | --- | --- |
| 5 min | 288 | **8.7× over** |
| 10 min | 144 | **4.4× over** |
| 30 min | 48 | **1.5× over** |
| 60 min | 24 | within budget |

The honest conclusion is one a TTL-only design misses: **no TTL alone can protect a
1,000/month quota.** Even 30 minutes on one hot location exceeds the daily budget if it is
polled continuously. Three things resolve this together:

1. **Fetching is lazy.** Anga never background-refreshes locations. An entry is only ever
   created for a location a user actually asked for, so real cost tracks real traffic
   rather than the theoretical worst case above.
2. **The quota reserve is the hard backstop.** Upstream calls stop entirely once fewer than
   `WEATHER_QUOTA_RESERVE` (25) monthly requests remain. Ordinary traffic cannot drain the
   budget to zero.
3. **The TTL sets the ceiling per location**, and 30 minutes is where the trade-off lands.

**Why 30 minutes is also defensible meteorologically**, independent of quota: surface
observations are typically published hourly, and Kenyan conditions are dominated by a
diurnal cycle with afternoon convective rain — real conditions rarely change meaningfully
inside half an hour. A 30-minute reading is not a stale reading; it is roughly as current
as the observation network itself.

**Why 6 hours of stale retention**, rather than the more usual 30 minutes: with a *monthly*
quota, a `429` means no fresh data for potentially **days**. A 30-minute stale window would
expire long before the lockout ended, leaving users with nothing precisely when the
fallback matters most. Six hours keeps a recently-known reading available across a long
outage while staying short enough that the data is still worth showing.

Both are environment-configurable (`WEATHER_CACHE_TTL`, `WEATHER_STALE_TTL`). On a Pro plan
(50,000/month ≈ 1,666/day) the reasoning changes and a shorter TTL becomes affordable —
which is exactly why they are configuration, not constants.

---

## Request coalescing

### The problem

Fifty users request an uncached Nairobi at the same instant. All fifty miss the cache. All
fifty call Weather-AI. Forty-nine of those responses are identical and wasted — and on a
1,000/month budget, that single burst costs 5% of the month.

### The mechanism

`cache.add()` is atomic — on Redis it compiles to `SET NX EX`. Exactly one concurrent
request acquires the lock and becomes the **leader**; the rest become **followers**.

```
50 concurrent requests
        │
        ├── 1 leader   ── acquires lock ── calls Weather-AI once ── writes cache
        │
        └── 49 followers ── poll for the leader's result ── serve it
```

Two details that make it correct rather than merely plausible:

- **Followers compare `fetched_at` against the entry that existed when they began
  waiting**, so a pre-existing *stale* entry is never mistaken for the leader's fresh
  result.
- **The leader releases the lock only if the token still matches its own.** Without that
  check, a leader that overran `WEATHER_LOCK_TTL` could delete a *successor's* lock and let
  a second upstream request through.

If the leader fails or is slow, followers **degrade to stale data rather than retrying** —
retrying is precisely the stampede coalescing exists to prevent.

### Verified

Not just unit-tested. Against a running server, with a mock upstream that reports its own
independent request counter:

```console
$ for i in $(seq 1 30); do curl -s "…/api/weather/?location=Kisumu" & done; wait
HTTP status codes returned:
     30 200

$ curl "…/api/meta/stats/"
  cache_miss                = 30
  coalesce_leader           = 1
  coalesce_follower_served  = 29
  upstream_request          = 1

# the mock's OWN counter, independent of anything Django reports:
$ curl -H "Authorization: Bearer …" http://127.0.0.1:8789/v1/usage
{"plan": "free", "requests": {"used": 1, "limit": 1000}}
```

**30 simultaneous requests → 1 upstream call.** The threaded test suite asserts the same
property with 25 real threads.

### Limitations, stated plainly

- With Redis, the lock is **correct across multiple backend instances** — that is the main
  reason Redis was chosen over Django's database cache, whose `add()` is a
  select-then-insert with a genuine race window.
- Without Redis (the local `LocMemCache` fallback), coalescing is **per-process only**. Four
  gunicorn workers would allow up to four upstream calls for the same burst. Still far
  better than fifty, but not the real guarantee.
- Followers **block a worker thread** while waiting, bounded by `WEATHER_COALESCE_WAIT`
  (12s). At this scale that is fine and is why the deployment uses threaded gunicorn
  workers. An async view or a background-refresh worker would remove the block entirely;
  see [Future improvements](#future-improvements).

---

## Rate-limit strategy

**Principle: when upstream says we are rate limited, stop calling upstream.**

Every response — success or failure — has its `X-RateLimit-Limit` / `-Remaining` / `-Reset`
headers recorded. That is free information, so we never spend a request on `/v1/usage` just
to learn our own quota.

```
                    ┌──────────────────────────────┐
   upstream call ──▶│  quota.upstream_allowed()    │
                    └──────────────┬───────────────┘
                                   │
        breaker open? ─────────────┼── yes ──▶ do NOT call. Serve stale, or 503.
                                   │
        remaining ≤ reserve? ──────┼── yes ──▶ do NOT call. Preserve the budget.
                                   │
                                   └── no ───▶ proceed
```

- **On `429`:** record the headers, open the circuit breaker **until `X-RateLimit-Reset`**,
  and serve cache exclusively until then. No retry — a retry cannot succeed against a
  monthly quota, and would only burn budget.
- **On `5xx` / timeout / connection failure:** a short backoff (`WEATHER_FAILURE_BACKOFF`,
  60s) so a struggling upstream is not hammered. Short, because these are usually transient.
- **Breaker duration is clamped** to `WEATHER_MAX_BREAKER_SECONDS` (24h), so a malformed or
  absurd reset header cannot wedge the service indefinitely. Against a real 30-day reset
  this means one probe request per day — about 30/month, an acceptable price for not being
  permanently stuck on bad data.
- **No retries anywhere.** `requests` is configured with `max_retries=0`; urllib3's implicit
  retries are disabled deliberately. Backoff happens once, centrally, at the breaker.

Because the breaker lives in the shared cache, with Redis **all instances observe one 429
and back off together** instead of each discovering it independently.

---

## Honest freshness

Stale data is never presented as current. Every response carries:

```json
"meta": {
  "status": "stale",
  "is_cached": true,
  "is_stale": true,
  "fetched_at": "2026-08-20T09:00:00Z",
  "age_seconds": 840,
  "expires_at": "2026-08-20T09:30:00Z",
  "ttl_seconds": 1800,
  "fallback_reason": "rate_limited",
  "retry_at": "2026-08-20T10:00:00Z"
}
```

The UI reflects all three states in words, not only colour:

| State | Indicator | Line under the reading |
| ----- | --------- | ---------------------- |
| Live | green dot | *Updated just now · live from Weather-AI* |
| Cached | blue dot | *Updated 4 minutes ago · cached* |
| Stale | amber dot | *Last updated 14 minutes ago · **not current*** |

Stale readings additionally carry a notice above the temperature:

> *Live updates are paused — showing the last reading we saved from 14 minutes ago.*

Age wording always **rounds down** to the completed unit, so freshness can never be
overstated. A cache hit is shown as a cache hit — being open about the ordinary case is
what makes the stale warning credible when it appears.

---

## API reference

### `GET /api/weather/?location={name}&units={metric|imperial}`

```json
{
  "location": { "slug": "nairobi", "name": "Nairobi", "county": "Nairobi",
                "kind": "county", "label": "Nairobi" },
  "weather": {
    "temperature": 24.4, "feels_like": 25.2, "humidity": 62,
    "wind_speed": 11.0, "wind_direction": "SE", "wind_direction_degrees": 130.0,
    "precipitation": 0.0, "precipitation_chance": 12,
    "pressure": 1014.0, "uv_index": 7.0,
    "condition": "Partly cloudy",
    "condition_group": "partly_cloudy", "condition_intensity": "none",
    "is_day": true, "observed_at": "2026-08-20T09:00:00Z", "units": "metric"
  },
  "meta": { "status": "live", "is_cached": false, "is_stale": false, "…": "…" }
}
```

Every `weather` field is nullable; the UI omits what the API did not return rather than
rendering an empty card.

`condition_group` (`clear`, `partly_cloudy`, `cloudy`, `fog`, `drizzle`, `rain`,
`thunderstorm`, `unknown`) and `condition_intensity` (`none`, `light`, `moderate`, `heavy`)
are a **stable vocabulary the backend derives**, so the frontend switches its backdrop on one
shared contract instead of re-interpreting upstream condition strings in each component.

**Errors** — all share one shape, and the `code` is what the UI keys off:

| HTTP | `code` | Meaning |
| ---- | ------ | ------- |
| 400 | `invalid_location` | Malformed, empty or over-long input |
| 400 | `invalid_units` | Units other than metric/imperial |
| 404 | `unknown_location` | Well-formed, but not a Kenyan location we cover |
| 429 | `too_many_requests` | **Our** throttle — the client is going too fast |
| 503 | `rate_limited` | **Upstream** quota exhausted, no cached fallback |
| 503 | `weather_unavailable` | Upstream down, no cached fallback |

`429` and `503` are deliberately distinct: conflating them would leave the frontend unable
to tell "you are going too fast" from "Weather-AI is out of quota".

### `GET /api/locations/?q={query}&limit={n}`

Autocomplete over the gazetteer. Served entirely from PostgreSQL — **typing costs no
upstream quota.** An empty `q` returns the most prominent locations.

### `GET /api/meta/stats/`

Non-sensitive observability so the caching can be demonstrated without shell access:
counters, derived hit rate, the active cache configuration, the last observed upstream
quota, and breaker state. Contains no secrets and no user data.

### `GET /healthz`

Liveness probe. Never throttled.

---

## Security

**API key protection.** `WEATHER_AI_API_KEY` is read from the environment and lives only in
the backend process. It is never in the React bundle, never in a response body, never in a
log line, and never in an exception message — `weather/client.py` logs the path, coordinates
and status code only, and deliberately does not interpolate `RequestException` (which can
carry the full request URL). `.env` is gitignored from the first commit;
`backend/.env.example` documents every variable with placeholders.

A test asserts error bodies never contain `bearer`, `wai_`, `api_key`, `authorization`,
`traceback` or the upstream hostname.

**CORS.** An explicit allow-list from `FRONTEND_ORIGINS`. `CORS_ALLOW_ALL_ORIGINS` is never
enabled, credentials are off, and only `GET`/`OPTIONS` are permitted. Verified:

```console
$ curl -I -H "Origin: http://localhost:5173" …   →  access-control-allow-origin: http://localhost:5173
$ curl -I -H "Origin: https://evil.example.com" … →  (no allow-origin header)
```

**Input validation.** Covered under [Cache keys](#cache-keys) — length cap, restricted
charset, guaranteed-safe output, applied before input can reach the cache or the database.

**Our own throttling.** DRF `ScopedRateThrottle`: 60/min weather, 120/min locations, 30/min
meta. This protects the backend from abuse and *therefore* protects the Weather-AI quota —
forcing cache misses on uncached locations is the only way a client can generate upstream
traffic at all. Limits sit well above normal use; a person using the app will never meet
them. Throttled requests are rejected before reaching the service layer, so they cost
nothing upstream.

**No auth surface.** `django.contrib.auth`, sessions and the admin are not installed. This
is a read-only public JSON API; anything else would be attack surface with no purpose.

**Production hardening** (active whenever `DEBUG=False`): `SECURE_SSL_REDIRECT`, HSTS with
preload, `SECURE_PROXY_SSL_HEADER` for Render's proxy, `nosniff`, `X-Frame-Options: DENY`,
strict referrer policy, secure cookies. Startup **fails loudly** if `DJANGO_SECRET_KEY` or
`DATABASE_URL` is missing with `DEBUG=False`, rather than silently running insecurely.

**Error hygiene.** A custom DRF exception handler maps everything to `{"error": {"code",
"message"}}`. Unhandled exceptions are logged server-side with their traceback and returned
as an opaque `internal_error`.

---

## Tech stack and why

| Choice | Why |
| ------ | --- |
| **Django + DRF** | Batteries for the boring-but-critical parts: settings/env handling, a cache abstraction with atomic `add()`, throttling, a clean exception-handling seam |
| **PostgreSQL** | Holds the Kenya gazetteer. This is genuinely relational, persistent data — and it exists because Weather-AI resolves coordinates only, so location search *must* be ours |
| **Redis** | The weather cache **and** the coordination primitive. `cache.add()` → atomic `SET NX EX` is what makes single-flight correct across instances |
| **React + Vite** | Small dependency surface, fast builds, a ~52 KB gzipped bundle |
| **Plain CSS** | A styling framework would add weight and push the design toward a generic look. The visual identity is the point |
| **`requests`** | Explicit, synchronous, easy to configure with zero retries |

**No weather data is stored in PostgreSQL.** Weather responses are volatile, expire on a
TTL and need atomic single-flight coordination — all cache concerns. Persisting every
response to a relational table would add write load and an unbounded growth problem while
solving nothing the cache does not already solve. `weather/models.py` is intentionally
empty and says so.

**Why Redis over Django's database cache**, given Postgres was already provisioned: the
database backend's `add()` is a select-then-insert with a real race window, which would
undermine the coalescing guarantee that is the centre of this project. That was the
deciding factor, not speed. The trade-off is one more service to provision — mitigated by a
documented `LocMemCache` fallback so local development needs no Redis at all.

---

## Local setup

**Prerequisites:** Python 3.11+, Node 18+. PostgreSQL and Redis are optional locally —
both have documented fallbacks.

```bash
git clone <your-repo-url> anga && cd anga
```

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # then edit: add your wai_ key
python manage.py migrate
python manage.py seed_locations    # loads 99 Kenyan locations
python manage.py runserver 8000
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env               # VITE_API_BASE_URL=http://localhost:8000
npm run dev                        # http://localhost:5173
```

### Developing without spending quota

The free tier is 1,000 requests **per month**, which is not a budget to spend on UI work.
`tools/mock_weather_api.py` implements the documented contract — bearer auth, the real
`X-RateLimit-*` headers, the documented `{"error": …}` shape, `429` and `5xx` simulation:

```bash
python tools/mock_weather_api.py --port 8787
# then in backend/.env:  WEATHER_AI_BASE_URL=http://localhost:8787
```

It exercises the entire real code path — client, adapter, cache, coalescing, quota
tracking, breaker. Useful flags for demonstrating degradation:

```bash
--fail-after 3     # succeed 3 times, then always 429   (Scenarios E and F)
--status 503       # always fail                        (graceful degradation)
--latency 1.5      # slow responses                     (makes coalescing visible)
```

Its **response body shape is a plausible guess, not a verified contract** — see
[the caveat above](#️-the-one-thing-the-docs-do-not-specify).

### Using real PostgreSQL and Redis locally

```bash
createdb anga
# in backend/.env:
DATABASE_URL=postgres://anga:anga@localhost:5432/anga
REDIS_URL=redis://localhost:6379/0
```

Without them, the app logs a clear warning and falls back to SQLite and `LocMemCache`. Both
fallbacks are development-only: production **refuses to start** without `DATABASE_URL`.

---

## Environment variables

Full documentation with defaults is in [`backend/.env.example`](backend/.env.example).

| Variable | Required | Notes |
| -------- | -------- | ----- |
| `DJANGO_SECRET_KEY` | prod | Startup fails without it when `DEBUG=False` |
| `DEBUG` | – | Default `False` |
| `ALLOWED_HOSTS` | prod | Comma-separated; Render's hostname is added automatically |
| `WEATHER_AI_API_KEY` | **yes** | Your `wai_` key. **Never commit** |
| `WEATHER_AI_BASE_URL` | – | Default `https://api.weather-ai.co` |
| `DATABASE_URL` | prod | Postgres URL; SQLite fallback in `DEBUG` only |
| `REDIS_URL` | recommended | `LocMemCache` fallback degrades coalescing to per-process |
| `WEATHER_CACHE_TTL` | – | Fresh window, seconds. Default `1800` (30 min) |
| `WEATHER_STALE_TTL` | – | Stale retention, seconds. Default `21600` (6 h) |
| `WEATHER_QUOTA_RESERVE` | – | Stop calling upstream below this many left. Default `25` |
| `WEATHER_COALESCE_WAIT` | – | Follower wait, seconds. Default `12` |
| `WEATHER_LOCK_TTL` | – | Single-flight lock lifetime. Default `15` |
| `WEATHER_FAILURE_BACKOFF` | – | Backoff after 5xx/timeout. Default `60` |
| `WEATHER_INCLUDE_AI` | – | Default `False` — preserves the 200/month AI quota |
| `FRONTEND_ORIGINS` | prod | Exact CORS origins, comma-separated. No wildcards |
| `THROTTLE_WEATHER` | – | Default `60/min` |
| `VITE_API_BASE_URL` | frontend | Backend URL. **Public** — never put secrets in `VITE_*` |

---

## Testing

**110 tests.** 75 backend, 35 frontend.

```bash
cd backend && python manage.py test        # 75 tests
cd frontend && npm test                    # 35 tests
```

Coverage is concentrated on the engineering behaviour rather than spread thin:

**Backend** — cache hit / miss / expiry / replacement; units cached separately; normalisation
collapsing case, whitespace, apostrophes and aliases onto one key; stale fallback on 429,
5xx and timeout; clean failure with no fallback; breaker short-circuiting before the network;
quota-reserve suspension; **coalescing with 25 real threads asserting exactly one upstream
call**; followers degrading rather than retrying when the leader fails; per-location lock
isolation; the full HTTP contract; throttling; adapter field mapping and condition
classification; and the security assertions (hostile input rejection, no secret leakage).

**Frontend** — loading skeleton, successful reading, cached labelling, stale warning with
its explanation, each error state, retry recovery, mouse and keyboard search selection, the
assertion that searching never triggers a weather request, omission of fields the API did
not return, and backdrop selection from condition data.

Notable bugs these caught during development: the typographic apostrophe `’` (what phone
keyboards emit) being rejected by validation; CRLF passing input validation; and a derived
metric that double-counted coalescing followers and reported more upstream calls avoided
than requests received.

---

## Deployment

**Backend + PostgreSQL + Redis → Render** · **Frontend → Vercel**

### Backend

1. Render → **New → Blueprint** → point at this repository. [`render.yaml`](render.yaml)
   provisions the web service, database and Key Value instance, and wires
   `DATABASE_URL`/`REDIS_URL` automatically.
2. Set the two secrets marked `sync: false` in the dashboard:
   - `WEATHER_AI_API_KEY` — your `wai_` key
   - `FRONTEND_ORIGINS` — e.g. `https://anga.vercel.app`
3. `build.sh` runs migrations and seeds the gazetteer on every deploy (both idempotent).

`DJANGO_SECRET_KEY` is generated by Render; it never exists in the repository.

### Frontend

1. Vercel → **New Project** → set **Root Directory** to `frontend`.
2. Set `VITE_API_BASE_URL` to the Render URL, e.g. `https://anga-api.onrender.com`.
3. Deploy. [`vercel.json`](frontend/vercel.json) handles the SPA rewrite and security
   headers.

Set `VERCEL_PROJECT_SLUG` on the backend to allow that project's preview deployments
through CORS without opening it to the world.

**Verify:**
```bash
curl https://<backend>/healthz
curl "https://<backend>/api/weather/?location=Nairobi"
curl "https://<backend>/api/weather/?location=Nairobi"   # meta.status should now be "cached"
```

---

## Trade-offs

Being straight about what this does and does not solve.

**Followers block a worker thread.** Bounded at 12s and fine at this scale with threaded
gunicorn workers, but under heavy load on many distinct uncached locations it consumes
capacity. Async views or background refresh would remove it.

**The circuit breaker is shared state, not consensus.** With Redis all instances back off
together. If Redis itself is unavailable, `quota.py` degrades to allowing calls rather than
blocking them — availability over strict quota protection. Arguably the wrong default under
a monthly quota, and worth revisiting.

**Metrics are approximate.** Counters use non-transactional `incr`, so concurrent
increments can lose a count. Fine for observability; they never drive control flow.

**The gazetteer is hand-curated.** 99 locations covering all 47 counties and the major
towns. Somewhere small and genuinely Kenyan will be missing, and the user gets a specific
"we do not cover that yet" message rather than weather. The alternative — free-text
geocoding — is Pro-tier on Weather-AI and would have added a second upstream dependency.

**Render's free tier cold-starts.** After inactivity the first request can take
30+ seconds. That is a plan limitation, not an architectural one, and it makes a cold first
load look slower than the system actually is.

**LocMemCache is a real downgrade, not just a convenience.** Without Redis, coalescing is
per-process and the cache dies on restart. It exists so local development needs no
infrastructure, and the app logs a warning at startup so nobody deploys that way by
accident.

**The upstream response shape is not fully verified.** The single largest caveat, discussed
[above](#️-the-one-thing-the-docs-do-not-specify). The risk is contained to one module with
a one-command path to resolving it.

**No forecast.** `/v1/weather` returns up to 7 days on the free tier and Anga shows only
current conditions. Displaying a forecast would cost nothing extra upstream — the data is
already in the response we cache — but it was out of scope for this build.

---

## Future improvements

Deliberately **not** implemented, to keep the scope honest:

- **Stale-while-revalidate.** Serve the stale entry immediately and refresh in the
  background, so nobody ever waits on upstream. The clearest next win.
- **Background refresh for popular locations**, driven by observed request counts, so hot
  locations are always warm and cold ones never cost anything.
- **Async views**, removing the blocking follower wait entirely.
- **A real metrics backend** (Prometheus/StatsD) instead of cache counters, with alerting on
  quota exhaustion before it happens.
- **A forecast view**, using the forecast days already present in the cached response.
- **Automated load testing** in CI to assert the coalescing property under sustained load
  rather than in a single test run.
- **A distributed lock with fencing tokens** (Redlock-style) if this ever ran at a scale
  where the current lock's failure modes mattered.

---

## Credits

Weather data from [Weather-AI](https://weather-ai.co/docs). Built as a technical assignment
demonstrating API consumption, caching, concurrency control, rate-limit handling and
graceful degradation.
