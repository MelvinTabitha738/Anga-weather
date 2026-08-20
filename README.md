# Anga — Weather for Kenya

**Anga** (Swahili for *sky*) is a weather dashboard for Kenyan counties and towns:
current conditions, an hourly outlook and a 7-day forecast, over a backdrop that reacts
to the actual weather.

The dashboard is the visible product. The engineering underneath it is the real subject —
a Django service that sits between users and the
[Weather-AI API](https://weather-ai.co/docs) and *manages* upstream consumption through
**server-side caching, request coalescing, rate-limit awareness and graceful
degradation**.

The governing idea:

> A user request does not have to become an upstream request.

Two facts about the provider shaped everything else, both verified against the live API
rather than assumed:

1. **`/v1/weather` takes coordinates only** — there is no place-name lookup on the free
   tier, so location search is served from our own Kenya gazetteer in PostgreSQL.
2. **Rate limits are monthly, not per-second** — 1,000 requests/month on the free tier,
   about 33 upstream calls *per day across every location combined*. A `429` here is not a
   momentary backoff; it is a lockout lasting until the quota rolls over.

---

## Quick start

Requires Python 3.11+ and Node 18+. PostgreSQL and Redis are optional locally — both have
documented fallbacks.

```bash
# Backend  (http://localhost:8000)
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt                 # or requirements.txt for prod only
cp .env.example .env                                # add your wai_ key
python manage.py migrate
python manage.py seed_locations                     # 99 Kenyan locations
python manage.py runserver

# Frontend (http://localhost:5173)
cd frontend
npm install
npm run dev
```

No API key yet? `python tools/mock_weather_api.py --port 8787` implements the documented
contract so you can develop without spending quota — see
[Developing without spending quota](#developing-without-spending-quota).

Full detail in [Local setup](#local-setup).

---

## Table of contents

**Understanding the system**
- [The problem](#the-problem)
- [What the Weather-AI docs actually say](#what-the-weather-ai-docs-actually-say)
- [Architecture](#architecture)
- [Request flows](#request-flows)

**The engineering**
- [Caching strategy](#caching-strategy)
- [Choosing the TTL](#choosing-the-ttl-the-arithmetic)
- [Request coalescing](#request-coalescing)
- [Rate-limit strategy](#rate-limit-strategy)
- [Honest freshness](#honest-freshness)

**The product**
- [The interface](#the-interface)
- [API reference](#api-reference)
- [Security](#security)

**Working on it**
- [Tech stack and why](#tech-stack-and-why)
- [Local setup](#local-setup)
- [Environment variables](#environment-variables)
- [Testing](#testing)
- [Deployment](#deployment)

**Honesty**
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
   budget in an afternoon, and the resulting `429` does not clear in sixty seconds - it
   clears when the 30-day period rolls over, potentially **days** later.

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
integration - and since the forecast rides along in that same response, we request the
full `days=7`.

**3. `ai=true` is the default and spends a second, much smaller quota** (200/month on
free). The docs say so explicitly: *"Add `?ai=false` to skip Gemini AI summaries and
preserve your AI quota."* Since `ai_summary` comes back `null` regardless (see below),
Anga sends **`ai=false`** rather than spending that quota for nothing.

### Rate limiting

The docs state every response carries:

```
X-RateLimit-Limit:     1000        # monthly cap
X-RateLimit-Remaining: 987
X-RateLimit-Reset:     1717977600  # unix epoch
```

**Verified against the live API: these headers do not exist.** Every header of several
real `200` responses was inspected and none is present. `GET /v1/usage` works instead and
returns the authoritative reading:

```json
{"plan": "free", "used": 3, "limit": 1000, "remaining": 997, "unlimited": false}
```

See [Rate-limit strategy](#rate-limit-strategy) for how quota is tracked without the
headers. Limits reset on a **30-day rolling period from the subscription date**, not the
calendar month. Documented plans: Free 1,000/mo (200 AI), Pro 50,000/mo, Scale 500,000/mo.

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

### The response shape, verified

Weather-AI publishes **no response schema** - there is no OpenAPI document
(`/openapi.json` 404s) and the docs show sample bodies only for `/v1/ip-lookup` and the
tree-analysis endpoints. Rather than guess, the shape was captured from a real
authenticated `GET /v1/weather?days=7&ai=true`. That capture is committed as
[`backend/weather/tests/fixtures/live_weather_response.json`](backend/weather/tests/fixtures/live_weather_response.json)
and the test suite asserts against it, so an upstream change fails loudly instead of
silently producing nulls.

```
{ lat, lon, units, days,
  current:  { time, interval, temperature, windspeed, winddirection, is_day, weathercode },
  hourly:  [{ time, temp, precipitation, weathercode }]                      x48,
  daily:   [{ date, temp_max, temp_min, precipitation, weathercode }]        x7,
  ai_summary: null }
```

**What is available:** temperature, wind speed and direction, day/night, a WMO weather
code, and full hourly (48h) and daily (7d) series with precipitation.

**What is NOT available, and therefore is not displayed:**

| Field | Status |
| ----- | ------ |
| Humidity | Not returned |
| Feels-like | Not returned |
| Pressure | Not returned |
| Visibility | Not returned |
| UV index | Not returned |
| Sunrise / sunset | Not returned |
| Condition text | Not returned - derived from `weathercode` |

Anga shows what the provider actually returns. There are no placeholder cards and no
invented values.

**`ai_summary` is `null`** on a free-plan key even with `ai=true`, contradicting the docs'
claim that summaries are included by default. It is passed through untouched, and the UI
renders that section **only when it is non-null** - so the capability exists without
fabricating prose. Because it is reliably null, `WEATHER_INCLUDE_AI` defaults to `false`
rather than spending the separate 200/month AI quota for nothing.

### Condition text from WMO codes

`weathercode` is the **WMO 4677** present-weather scale (codes 0, 1, 2, 3, 51, 53 and 95
all appeared in the captured response). Rendering code `51` as "Light drizzle" translates a
documented standard rather than inventing data, and the same mapping drives both the
wording and the animated backdrop. The table lives in
[`weather/adapter.py`](backend/weather/adapter.py).

### The forecast is free

The hourly and daily series arrive **in the same response** as current conditions, so
`days=7` costs exactly the same single request against the monthly quota as `days=1`.
Anga therefore requests the free-plan maximum and renders the full forecast from data it
was already caching.

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

### The failure mode

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

The documented `X-RateLimit-*` headers **do not exist on the live API**, so quota is
tracked two ways, combined:

1. **`GET /v1/usage`** is authoritative - `{plan, used, limit, remaining, unlimited}`. But
   it costs a request itself, so polling it would consume the very budget it reports on.
   Hourly polling would be 720 requests/month against a 1,000/month tier: absurd. It is
   synced **at most once per `WEATHER_USAGE_TTL` (default 24h)** - about 30 requests a
   month, 3% of the budget - and only piggybacked onto a cache miss that was already
   calling upstream.

   Critically, that interval is enforced by a **shared atomic claim**, not by a timestamp
   check alone:

   ```
                          Redis
                            │
                   lock:upstream:usage   ← cache.add() = SET NX EX
                            │
              ┌─────────────┼─────────────┐
           Worker A      Worker B      Worker C
              └─────────────┼─────────────┘
                            ↓
                    exactly one winner
                            ↓
                       /v1/usage
   ```

   `usage_sync_due()` is a plain read, so it is a check-then-act race, and the request
   coalescing lock does **not** cover it — that lock is keyed by location, so concurrent
   leaders for Nairobi, Mombasa and Kisumu are three separate leaders arriving at the gate
   together. Without the claim, a cold cache on a multi-worker deploy spends one request
   per concurrent miss on a reading identical for all of them. A test asserts that 6
   concurrent workers across 6 different locations produce exactly **1** `/v1/usage` call,
   and that 50 threads contending on the claim produce exactly **1** winner.

   The claim is held for `WEATHER_USAGE_LOCK_TTL` (1h), which doubles as the retry
   backoff: a failed sync is not retried until it expires, so a broken endpoint costs at
   most ~24 requests a day rather than one per cache miss. On success `synced_at` is
   stamped, which keeps the gate shut for the full 24h regardless of when the claim
   lapses.

2. **Local counting** covers the gap. We are the only consumer of this key, so
   `remaining_at_sync - calls_since_sync` is an accurate running estimate for free.

The estimate is deliberately **conservative**: every attempt is counted, including failed
ones, so `remaining` can only ever read lower than reality and the reserve triggers early
rather than late. Header parsing is still attempted on every response - costless, and it
picks the headers up automatically if the provider ever starts sending them.

```
                    ┌──────────────────────────────┐
   upstream call ──▶│  quota.upstream_allowed()    │
                    └──────────────┬───────────────┘
                                   │
        breaker open? ─────────────┼── yes ──▶ do NOT call. Serve stale, or 503.
                                   │
   estimated remaining ≤ reserve? ─┼── yes ──▶ do NOT call. Preserve the budget.
                                   │
                                   └── no ───▶ proceed
```

- **On `429`:** open the circuit breaker, force the stored `remaining` to zero, and serve
  cache exclusively. No retry - a retry cannot succeed against a monthly quota and would
  only burn budget. With no `X-RateLimit-Reset` to read, the backoff falls to
  `WEATHER_DEFAULT_429_BACKOFF` (15 min), after which one probe request tests whether the
  quota has rolled over.
- **On `5xx` / timeout / connection failure:** a short backoff
  (`WEATHER_FAILURE_BACKOFF`, 60s), because these are usually transient.
- **Breaker duration is clamped** to `WEATHER_MAX_BREAKER_SECONDS` (24h) so a malformed
  value cannot wedge the service indefinitely.
- **No retries anywhere.** `requests` is configured with `max_retries=0`; urllib3's
  implicit retries are disabled deliberately. Backoff happens once, centrally.

Because the breaker and the quota estimate both live in the shared cache, with Redis **all
instances observe one 429 and back off together**.

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

The UI spends words only where they change what the reader should **believe**:

| State | Indicator | Line under the reading |
| ----- | --------- | ---------------------- |
| Live | green dot | *Updated just now* |
| Cached | blue dot | *Updated 4 minutes ago* |
| Outlived the TTL | amber dot | *Updated 31 minutes ago · **may be out of date*** + Refresh |
| Stale | amber dot | *Last updated 14 minutes ago · **not current*** |

Note what the first two deliberately do **not** say: whether the response came from cache
or from upstream. That is implementation vocabulary. The reader has one question — *how
old is this?* — and the age answers it completely; whether the bytes came from Redis is
our concern, not theirs, and labelling the ordinary case "cached" only implies something
second-rate. It would also contradict a rule applied everywhere else here, that internals
never reach the interface.

The provenance is still available: on hover as a `title`, and in full at
`/api/meta/stats/`. The caching story belongs in the metrics and in this document, not in
the product chrome.

Stale readings additionally carry a notice above the temperature:

> *Live updates are paused — showing the last reading we saved from 14 minutes ago.*

Age wording always **rounds down** to the completed unit, so freshness can never be
overstated. And because the ordinary states stay quiet, the two that do carry a warning
are worth reading when they appear.

### The age keeps counting

`age_seconds` is a snapshot taken when the server built the response. Left alone it
freezes, so a tab open for an hour would keep insisting the reading is "just now" — the
exact overstatement the rest of the design avoids. The frontend adds locally elapsed time
on top of the server's figure, and the line ticks:

```
Updated just now · live   →   Updated 3 minutes ago   →   Updated 12 minutes ago
```

Elapsed time is measured from a local timestamp taken when the payload arrived, **not** by
comparing `now` against `fetched_at`. Those are two different clocks: a device whose time
is wrong by ten minutes would otherwise report a ten-minute error, or a negative age.
Measuring a delta on a single clock is immune to skew.

Once the displayed age passes `ttl_seconds` the reading is no longer what the server would
call fresh, so it says so and offers a **Refresh**. There is deliberately no auto-refresh:
that would silently spend quota the user did not ask for.

---

## The interface

### Anatomy

```
  ← Search locations                        ● Updated 3 minutes ago
  Kakamega
  Thursday, 20 August

      ☁      26°
             Light drizzle

  ┌──────────┬──────────────┬────────────┬──────────────┐
  │ Wind     │ Rain this hr │ Rain today │ High / Low   │
  │ 5 km/h   │ 0.1          │ 2.2        │ 26° / 15°    │
  │ WNW      │              │            │              │
  └──────────┴──────────────┴────────────┴──────────────┘

  TODAY'S OUTLOOK                            💧 Rainfall (mm)
  Now   4 PM   5 PM   6 PM   7 PM   8 PM  →  (scrolls)
  26°   26°    25°    24°    23°    22°

  NEXT 7 DAYS                                💧 Rainfall (mm)
  Today      ☁    2.2    15° ▬▬▬▬▬▬ 26°
  Tomorrow   ☁    0.4    14° ▬▬▬▬▬▬ 28°
  Saturday   ☀     —     15° ▬▬▬▬▬▬ 28°
```

The forecast costs nothing extra: `hourly` and `daily` arrive in the same upstream
response we were already caching.

### Only what the provider returns

Weather-AI returns no humidity, feels-like, pressure, visibility or UV index. Those cards
therefore **do not exist** — there are no placeholder dashes and no invented values. The
supporting row is built from what is genuinely available: wind, rainfall this hour,
rainfall today, and today's high/low.

Rainfall gets the same treatment in reverse. The API returns a figure for *every* day
including `0.0`, so a dry day is a known value rather than missing data. Every row carries
a value — a figure when it rains, an em dash when it does not — and the unit is stated
once in a column legend instead of being repeated on each line.

### Weather drives the visuals

The backend classifies each WMO code into a small stable vocabulary
(`condition_group` + `condition_intensity` + `is_day`). The frontend switches on that one
contract, so no component re-interprets upstream values:

| Condition | Treatment |
| --------- | --------- |
| Clear (day) | Warm sky, sun glow, slow breathing light |
| Clear (night) | Deep sky, moon, fixed star field |
| Partly cloudy | Softer sky, drifting cloud layers |
| Overcast | Muted grey-blue, heavier cloud, lower contrast |
| Fog | Low contrast, drifting fog layers, reduced depth |
| Drizzle / Rain | Darkened sky, canvas rainfall |
| Thunderstorm | Dark sky, heavy rain, occasional lightning |

**Intensity is data-driven.** Rain density follows the reported intensity — and measured
rainfall can *promote* it, so Kakamega's 12.6 mm thunderstorm animates harder than a
0.1 mm trace. Adding a condition means editing one table, not hunting through JSX.

### Weather imagery

Icons are rendered rather than drawn: radial and linear gradients with a consistent light
direction, soft shadow under each cloud form, translucent rain, a glowing sun corona. Line
art reads as a diagram; shading reads as weather.

**Temperature drives the light.** The sun's palette and glow are selected from the actual
temperature across five bands, so a cool Nyahururu morning renders a pale thin sun and a
hot Garissa afternoon a heavy amber one — same condition code, different heat. A
photograph of a sun would be the same sun at 12°C and 34°C.

SVG rather than an icon pack or photographs: sharp at any size, inherits the page's light,
no network request, no licensing, and — the deciding factor — it can be driven by data.

Blur filters are the expensive part and a dashboard renders roughly 31 icons at once
(24 hourly + 7 daily), so filters are applied only above 48px. Below that the gradients
carry it, which is visually near-identical at that scale and far cheaper. Gradient ids are
generated per instance with `useId`; duplicates would make every icon inherit the first
one's palette.

### Identity and the landing page

The mark is a sun low over a horizon under an open sky — the sky itself rather than a
weather symbol, since a cloud or a thermometer would tie the brand to one condition while
the product shows all of them. It is built to survive being small: the sun and horizon
separate at 20px because they differ in value, not only in hue.

The landing page is built to a supplied design: an eyebrow, a two-line Playfair Display
headline with the second line in warm amber, a short lede, the search, starting points,
and three feature panels — over a **photograph of Mount Kenya at dusk**.

**The sky moves.** A still photograph of a sky reads as a poster; a slow 80-second pan
reads as weather. It is transform-only and GPU-composited, so the cost is a layer rather
than a repaint, and it holds still under `prefers-reduced-motion`.

**The design's live-weather card is deliberately absent.** Showing a reading before anyone
has searched would mean an upstream call on every landing view — on a 1,000-request
monthly quota, the single most expensive thing this product could do. The space goes back
to the photograph instead.

Type is **Playfair Display** for the display voice and **Outfit** for the geometric UI
face, matched to the design.

The photograph gets its own scrim, measured rather than guessed: the brightest pixel
falling under text is a sunlit cloud at luminance 0.84, needing alpha 0.66 to carry
`--ink-muted` past 4.5:1. A flat 0.66 would flatten the photograph, so the weight is
pushed left where the words are and lifted on the right where the cumulus should stay
visible. In portrait the text spans the frame, so the veil does too.

Performance and comfort: one canvas and one `requestAnimationFrame` loop, delta-time
integrated so speed is identical at 60Hz and 120Hz, paused when the tab is hidden, and
fully disabled under `prefers-reduced-motion`. The weather is always stated in text, so
the animation is decoration rather than information.

### Responsive

Breakpoints sit where the **layout** breaks, not at device names — 48rem, 34rem and
22.5rem — plus `pointer: coarse` for touch targets (sized to the finger, not the screen)
and a short-landscape query, because a phone on its side has ~360px of *height*.

Verified by arithmetic across real device widths: **zero horizontal overflow from 320px to
1920px**, with 87px of temperature bar still available on an iPhone SE.

| Width | Device | Temperature bar |
| ----- | ------ | --------------- |
| 320px | iPhone SE | 87px |
| 390px | iPhone 14/15 | 133px |
| 768px | iPad portrait | 417px |
| 1920px | Desktop | 1550px |

Specific decisions: metrics go two-up on phones so all four numbers stay above the fold;
the rain column stays on mobile because the legend promises it; in landscape the hero
yields first, since height is the scarce resource. `viewport-fit=cover` is paired with
`env(safe-area-inset-*)` so content clears the notch and home indicator, and the search
input is held at 16px because iOS zooms the whole page on a smaller focused input.

### Search

Suggestions are debounced and served from PostgreSQL, so typing costs no upstream quota.

The subtle part is what happens on Enter. Because suggestions lag the keystrokes, the
visible results may still belong to an earlier query at the moment Enter is pressed —
acting on them selects the wrong town and makes the box feel like it needs several presses
before it takes. So the hook reports **which query the current results belong to**, and
Enter only trusts the list when that matches what is typed. Otherwise it submits the raw
text and lets the backend resolve it, which it can, because normalisation and alias lookup
are server-side. The first Enter is always correct.

A visible **Search** button sits alongside, because an input with no commit affordance
leaves people unsure whether their keypress registered — particularly on phones. Clear
appears only when there is something to clear.

### Accessibility

Text is a single near-white ramp over a scrim that is **solved per sky**. A fixed scrim did
not work, and asserting that it did was wrong: an audit of every palette found **20 WCAG
failures**, all on bright daytime skies, because the veil was thinnest exactly where the
sky was brightest — primary text over the fog sky measured **3.63:1** against a 4.5
requirement.

For each gradient stop, `scrimAlphaFor()` finds the lightest scrim that still carries the
whole text ramp past AA. A midnight sky keeps its depth with a thin veil; a noon sky gets
whatever it needs. Legibility no longer depends on which way the weather went, and a
palette added later is covered automatically rather than silently failing.

A test recomputes the real contrast for every theme × every stop × every step of the ramp,
so this cannot regress.

The status dot beside the reading is built the same way: a bright core, a coloured halo to
separate it from a dark background and a dark ring to separate it from a light one, plus a
slow expanding pulse — a pulse rather than a flicker, since flashing elements are an
accessibility hazard and read as an error rather than a status. The stale state pulses
faster, because it is a warning. Search is a real ARIA combobox with arrow-key
navigation; the freshness line is an `aria-live="polite"` region; every rainfall cell
carries a spoken label (*"1.9 millimetres of rain"* / *"No rain expected"*) because the
legend is not adjacent to the value; icons are `currentColor` SVG rather than emoji, which
render inconsistently and cannot inherit colour.

---

## API reference

### `GET /api/weather/?location={name}&units={metric|imperial}`

```json
{
  "location": { "slug": "kakamega", "name": "Kakamega", "county": "Kakamega",
                "kind": "county", "label": "Kakamega" },

  "current": {
    "temperature": 26.0, "wind_speed": 5.2,
    "wind_direction": "WNW", "wind_direction_degrees": 292.0,
    "precipitation_this_hour": 0.1, "weather_code": 51,
    "condition": "Light drizzle",
    "condition_group": "drizzle", "condition_intensity": "light",
    "is_day": true, "observed_at": "2026-08-20T15:30", "units": "metric"
  },

  "hourly": [
    { "time": "2026-08-20T15:00", "temperature": 26.1, "precipitation": 0.1,
      "weather_code": 51, "condition": "Light drizzle",
      "condition_group": "drizzle", "condition_intensity": "light" }
  ],

  "daily": [
    { "date": "2026-08-20", "temp_max": 26.3, "temp_min": 15.0,
      "precipitation": 2.2, "weather_code": 51, "condition": "Light drizzle",
      "condition_group": "drizzle", "condition_intensity": "light" }
  ],

  "ai_summary": null,

  "meta": { "status": "live", "is_cached": false, "is_stale": false, "…": "…" }
}
```

Sections are split by what they are, so the dashboard renders each independently. Every
value is nullable and the UI omits what is null — see
[the response shape](#the-response-shape-verified) for what this provider does and does
not return.

`condition_group` (`clear`, `partly_cloudy`, `cloudy`, `fog`, `drizzle`, `rain`, `snow`,
`thunderstorm`, `unknown`) and `condition_intensity` (`none`, `light`, `moderate`,
`heavy`) are a **stable vocabulary the backend derives from the WMO code**, so the
frontend switches its backdrop and icons on one shared contract instead of
re-interpreting upstream values in each component. Measured rainfall can promote — never
demote — the intensity, which is what makes the rain animation track real rainfall.

`hourly` starts at the hour in progress and is capped at 24 entries; `daily` carries the
full 7 days.

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

**217 tests.** 98 backend, 119 frontend.

```bash
cd backend && python manage.py test        # 98 tests
cd frontend && npm test                    # 119 tests
```

Coverage is concentrated on the engineering behaviour rather than spread thin:

**Backend** — cache hit / miss / expiry / replacement; units cached separately; normalisation
collapsing case, whitespace, apostrophes and aliases onto one key; stale fallback on 429,
5xx and timeout; clean failure with no fallback; breaker short-circuiting before the network;
quota-reserve suspension; **coalescing with 25 real threads asserting exactly one upstream
call**; followers degrading rather than retrying when the leader fails; per-location lock
isolation; the full HTTP contract; throttling; adapter field mapping and condition
classification; **assertions against the captured live response** so an upstream shape
change fails the suite; **the shared usage-sync claim** (6 concurrent workers across 6
locations produce 1 `/v1/usage` call; 50 contending threads produce 1 winner); and the
security assertions (hostile input rejection, no secret leakage).

**Frontend** — the production mount path (inside `StrictMode`, with the backend
unreachable, with corrupt `localStorage`); the dashboard (current conditions, metric row,
hourly strip, multi-day forecast); cached labelling and the stale warning with its
explanation; every error state and retry recovery; mouse and keyboard search selection;
the assertion that searching never triggers a weather request; **the assertion that
humidity / feels-like / pressure / visibility never appear**; the AI-insight section
staying hidden while `ai_summary` is null; naive-local time rendering without timezone
drift; backdrop selection from condition data; **the rainfall column never leaving a cell
blank** (fixture built from real Meru data, four dry days); **the freshness clock ticking**
from "just now" to "3 minutes ago" and warning once it outlives the TTL; **search never
acting on stale suggestions** (the regression that made Enter appear to need several
presses); and **the sun's palette tracking temperature**, including the null case that
would otherwise render a missing reading as freezing.

Notable bugs these caught during development: the typographic apostrophe `’` (what phone
keyboards emit) being rejected by validation; CRLF passing input validation; and a derived
metric that double-counted coalescing followers and reported more upstream calls avoided
than requests received.

---

## Deployment

**Backend + Redis → Render** · **PostgreSQL → Neon** · **Frontend → Vercel**

PostgreSQL is hosted on [Neon](https://neon.tech) rather than Render for two reasons:
Render permits only one free-tier database per account, and a Render free database is
**deleted after 90 days**. Neon's free tier has no such expiry.

There is a deliberate ordering here: the backend must exist before the frontend can be
told where to call, and the frontend must exist before the backend can allow its origin
through CORS. So the backend goes up first, the frontend second, and the backend's CORS
setting is filled in last.

### Before you start

- The repository pushed to GitHub
- A Weather-AI API key (`wai_…`) from the dashboard
- Free accounts on [Neon](https://neon.tech), [Render](https://render.com) and
  [Vercel](https://vercel.com)

---

### Step 1 — Push

```bash
git push origin main
```

### Step 2 — Create the database on Neon

Neon → **New Project** → name it `anga`. No card required.

**Pick the region that matches Render's**, not the one nearest your users. The browser
never talks to the database — it talks to Render, and Render talks to Neon. Since every
request resolves a location against PostgreSQL, a region mismatch adds a cross-continent
round trip to *every* request, cache hits included.

`render.yaml` pins Render to **`oregon`**, so choose **AWS US West 2 (Oregon)** on Neon.
If you move one, move the other.

Copy the **connection string** from the dashboard. It looks like:

```
postgresql://anga_owner:...@ep-xxx.eu-central-1.aws.neon.tech/anga?sslmode=require
```

Keep the `?sslmode=require` — production settings expect TLS. There is nothing else to
do here: no schema, no tables. `build.sh` migrates and seeds it on the first deploy.

### Step 3 — Provision the backend on Render

Render → **New → Blueprint** → select this repository. It reads
[`render.yaml`](render.yaml) and provisions three things:

| Resource | Name | Purpose |
| -------- | ---- | ------- |
| Web service | `anga-api` | Django + gunicorn |
| Key Value (Redis) | `anga-cache` | Weather cache, single-flight locks, quota state |

`REDIS_URL` is wired automatically and `DJANGO_SECRET_KEY` is generated by Render — it
never exists in the repository. `DATABASE_URL` is the Neon string from Step 2.

> **If the blueprint is rejected on the Key Value resource**, your account may still use
> the older name. Change **both** `type: keyvalue` (line ~78) and `fromService.type`
> (line ~56) in `render.yaml` to `redis`, then retry.

### Step 4 — Add the secrets

The Blueprint prompts only for values marked `sync: false` — everything else
(`DEBUG`, `WEATHER_AI_BASE_URL`, the TTLs) comes straight from `render.yaml`.

| Key | Value |
| --- | ----- |
| `DATABASE_URL` | the Neon connection string from Step 2 |
| `WEATHER_AI_API_KEY` | your `wai_…` key |
| `FRONTEND_ORIGINS` | leave blank for now — filled in at Step 7 |
| `VERCEL_PROJECT_SLUG` | leave blank — optional preview-deploy CORS |

`ALLOWED_HOSTS` needs nothing: Render injects `RENDER_EXTERNAL_HOSTNAME` and settings.py
appends it automatically.

### Step 5 — Verify the backend

`build.sh` runs migrations and seeds the gazetteer on every deploy; both are idempotent.
Once the deploy is live:

```bash
curl https://anga-api.onrender.com/healthz
# {"status":"ok","service":"anga"}

curl "https://anga-api.onrender.com/api/locations/?q=kaka"
# Kakamega, Mumias  -> PostgreSQL is seeded

curl "https://anga-api.onrender.com/api/weather/?location=Nairobi" | head -c 200
# "status":"live"   -> the Weather-AI key works

curl "https://anga-api.onrender.com/api/weather/?location=Nairobi" | head -c 200
# "status":"cached" -> Redis is connected and caching
```

That last pair is the real smoke test: `live` then `cached` proves the whole chain —
gazetteer lookup, upstream call, and Redis — is working.

### Step 6 — Deploy the frontend on Vercel

Vercel → **New Project** → import the repository:

| Setting | Value |
| ------- | ----- |
| Root Directory | `frontend` |
| Framework preset | Vite *(auto-detected)* |
| Environment variable | `VITE_API_BASE_URL` = `https://anga-api.onrender.com` |

Setting **Root Directory** matters — without it Vercel builds from the repo root and finds
no `package.json`. [`vercel.json`](frontend/vercel.json) handles the SPA rewrite and
security headers.

> Everything in a `VITE_*` variable is compiled into the public JavaScript bundle. The
> backend URL belongs there; the Weather-AI key never does.

### Step 7 — Close the CORS loop

Copy the Vercel URL, then back in Render set:

```
FRONTEND_ORIGINS = https://your-project.vercel.app
```

Exact origin, no trailing slash, comma-separated if there is more than one. Optionally
also set `VERCEL_PROJECT_SLUG` to allow that project's preview deployments without
opening CORS to the world. Render redeploys automatically.

### Step 8 — Confirm end to end

Open the Vercel URL and search for a Kenyan town. Then check the cache is doing its job:

```bash
curl https://anga-api.onrender.com/api/meta/stats/
```

`derived.upstream_requests_avoided` should climb while `upstream_requests_made` stays
flat, and `upstream_quota.estimated_remaining` should barely move.

---

### Troubleshooting

| Symptom | Cause |
| ------- | ----- |
| `build.sh: Permission denied` | The file lost its executable bit. `git update-index --chmod=+x backend/build.sh` |
| `/usr/bin/env: 'bash
'` | CRLF line endings reached the script. `.gitattributes` prevents this; re-commit the file |
| Browser console shows a CORS error | `FRONTEND_ORIGINS` missing, misspelled, or has a trailing slash |
| `DisallowedHost` | Rare on Render, since the hostname is auto-appended. Set `ALLOWED_HOSTS` manually if using a custom domain |
| `cannot have more than one active free tier database` | You are on the Render-managed database path. This blueprint no longer creates one — pull the latest `render.yaml` |
| `SSL connection is required` | The `?sslmode=require` suffix was dropped from the Neon string |
| Weather returns 503 `weather_unavailable` | Check `WEATHER_AI_API_KEY` is set and starts with `wai_`. Startup logs warn about both |
| Everything is slow on first load | Render free services sleep after inactivity; the first request pays a 30s+ cold start |

### Free-tier limits worth knowing

- **Render web services sleep** after ~15 minutes idle. The first request afterwards is
  slow. This is a plan limitation, not an architectural one.
- **Neon free databases suspend after ~5 minutes idle.** The first query afterwards takes
  a second or two to wake. Django is configured with `conn_health_checks=True`, so a
  connection that went stale during a suspend is detected and replaced rather than
  raising. Combined with a Render cold start, a genuinely idle deployment can take a while
  to answer its first request.
- **Weather-AI free tier is 1,000 requests/month.** The caching is what keeps a public
  deployment inside that; see [Choosing the TTL](#choosing-the-ttl-the-arithmetic).

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

**The provider returns less than the docs suggest.** No humidity, feels-like, pressure,
visibility or UV index, and `ai_summary` is null on the free plan despite the docs. The
dashboard is shaped by what genuinely exists rather than by what would look richer. If a
paid plan returns more, `weather/adapter.py` is the only file that changes.

**Quota tracking is an estimate between syncs.** The documented `X-RateLimit-*` headers do
not exist, so `remaining` is `last /v1/usage reading - locally counted calls`. It is
conservative by construction, but it would drift if another client used the same API key.
A shorter `WEATHER_USAGE_TTL` trades quota for accuracy.

**The AI insight section is built but dormant.** It renders only when `ai_summary` is
non-null, which on this plan is never. That is deliberate — the alternative was inventing
prose — but it means a visible feature of the design is currently invisible.

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
- **Automated load testing** in CI to assert the coalescing property under sustained load
  rather than in a single test run.
- **Live weather on the landing page.** Tempting and currently refused: six cities would be
  six upstream calls every 30 minutes, roughly 288 a day against a budget of 33. It only
  becomes affordable on a paid plan, or with a background refresher warming a fixed set.
- **Sunrise and sunset**, if the provider ever returns them. `is_day` is currently the only
  daylight signal, so the backdrop switches between day and night without knowing when the
  boundary actually falls.
- **A Kiswahili interface.** `lang=sw` exists but only translates the AI summary, which is
  null on this plan. Translating the interface itself is a separate, larger piece of work.
- **A distributed lock with fencing tokens** (Redlock-style) if this ever ran at a scale
  where the current lock's failure modes mattered.

---

## Credits

Weather data from [Weather-AI](https://weather-ai.co/docs). Built as a technical assignment
demonstrating API consumption, caching, concurrency control, rate-limit handling and
graceful degradation.
