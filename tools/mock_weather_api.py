"""A local stand-in for the Weather-AI API. DEVELOPMENT ONLY.

Why this exists
---------------
Weather-AI's free tier allows 1,000 requests per MONTH. Developing and
demonstrating against the live API would burn that budget on work that does not
need real data. This server implements the parts of the contract that Anga
depends on, so the entire real code path - client, adapter, cache, coalescing,
quota tracking, circuit breaker - can be exercised without spending quota.

What it faithfully reproduces (all verified against https://weather-ai.co/docs):
  * GET /v1/weather with required lat/lon and optional days/ai/units/lang
  * Bearer auth, rejecting a missing header with the documented 401 body
  * X-RateLimit-Limit / -Remaining / -Reset headers on every response
  * 429 with a future X-RateLimit-Reset once the budget is spent
  * the documented {"error": "..."} error shape

What it does NOT reproduce
--------------------------
The response BODY. Weather-AI does not publish a response schema, so the body
below is a plausible shape, not a verified one. It is here to drive the UI, not
to define the contract. Run `manage.py probe_upstream` against a real key to
capture the true shape, then prune weather/adapter.py's FIELD_CANDIDATES to it.

Usage
-----
    python tools/mock_weather_api.py --port 8787

    # then, in backend/.env
    WEATHER_AI_BASE_URL=http://localhost:8787
    WEATHER_AI_API_KEY=wai_local_mock_key

Failure simulation, to exercise graceful degradation:

    --fail-after N   serve N successful requests, then always 429
    --status 503     always return this status
    --latency 2.5    delay every response, to make coalescing observable
"""

import argparse
import json
import math
import random
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

STATE = {
    "served": 0,
    "limit": 1000,
    "fail_after": None,
    "forced_status": None,
    "latency": 0.0,
}

# Deterministic-ish conditions so a given location looks stable across reloads
# but different locations look different.
CONDITIONS = [
    (0, "Clear", 0.0),
    (1, "Mainly clear", 0.0),
    (2, "Partly cloudy", 0.0),
    (3, "Overcast", 0.0),
    (45, "Fog", 0.0),
    (53, "Moderate drizzle", 0.6),
    (61, "Slight rain", 1.4),
    (63, "Moderate rain", 4.2),
    (65, "Heavy rain", 11.8),
    (95, "Thunderstorm", 8.5),
]


def build_body(lat, lon, units):
    """A plausible current-conditions body. Shape is a guess - see docstring."""
    # Seed from coordinates so each location is visually distinct but stable.
    seed = int(abs(lat * 1000) + abs(lon * 1000))
    rng = random.Random(seed)
    code, text, precip = CONDITIONS[seed % len(CONDITIONS)]

    now = datetime.now(timezone.utc)
    # Rough day/night for East Africa (UTC+3): sunrise ~06:30, sunset ~18:45.
    local_hour = (now.hour + 3) % 24
    is_day = 6 <= local_hour < 19

    base_c = 18 + 8 * math.cos(math.radians((local_hour - 15) * 15)) - abs(lat) * 0.4
    temperature = round(base_c if units == "metric" else base_c * 9 / 5 + 32, 1)
    feels = round(temperature + rng.uniform(-1.2, 1.8), 1)

    return {
        "location": {"lat": lat, "lon": lon, "timezone": "Africa/Nairobi"},
        "current": {
            "time": now.isoformat(),
            "temperature": temperature,
            "feels_like": feels,
            "humidity": rng.randint(38, 88),
            "wind_speed": round(rng.uniform(3, 26), 1),
            "wind_deg": rng.randint(0, 359),
            "precipitation": precip,
            "precipitation_probability": min(100, int(precip * 9) + rng.randint(0, 15)),
            "pressure": rng.randint(1006, 1022),
            "uv_index": 0 if not is_day else rng.randint(1, 11),
            "weather_code": code,
            "condition": {"text": text, "code": code},
            "is_day": 1 if is_day else 0,
        },
        "units": units,
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print(f"[mock] {self.address_string()} {fmt % args}")

    def _send(self, status, payload, extra_headers=None):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra_headers or {}).items():
            self.send_header(key, str(value))
        self.end_headers()
        self.wfile.write(body)

    def _rate_limit_headers(self, remaining, reset_at):
        return {
            "X-RateLimit-Limit": STATE["limit"],
            "X-RateLimit-Remaining": max(0, remaining),
            "X-RateLimit-Reset": reset_at,
        }

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        # Monthly quota resets 30 days out, matching the documented rolling
        # period.
        reset_at = int(time.time()) + 30 * 86400

        auth = self.headers.get("Authorization", "")
        if not auth:
            self._send(401, {"error": "Missing Authorization header. Use: Bearer <api_key>"})
            return
        if not auth.startswith("Bearer wai_"):
            self._send(401, {"error": "Invalid API key."})
            return

        if parsed.path == "/v1/usage":
            self._send(
                200,
                {
                    "plan": "free",
                    "requests": {"used": STATE["served"], "limit": STATE["limit"]},
                },
                self._rate_limit_headers(STATE["limit"] - STATE["served"], reset_at),
            )
            return

        if parsed.path not in ("/v1/weather", "/v1/forecast", "/v1/current"):
            self._send(404, {"error": "Not found."})
            return

        if STATE["latency"]:
            time.sleep(STATE["latency"])

        if STATE["forced_status"]:
            status = STATE["forced_status"]
            self._send(
                status,
                {"error": f"Simulated upstream failure ({status})."},
                self._rate_limit_headers(STATE["limit"] - STATE["served"], reset_at),
            )
            return

        if STATE["fail_after"] is not None and STATE["served"] >= STATE["fail_after"]:
            self._send(
                429,
                {"error": "Monthly quota exceeded."},
                self._rate_limit_headers(0, reset_at),
            )
            return

        try:
            lat = float(params.get("lat", [None])[0])
            lon = float(params.get("lon", [None])[0])
        except (TypeError, ValueError):
            self._send(400, {"error": "lat and lon are required."})
            return

        units = params.get("units", ["metric"])[0]
        STATE["served"] += 1

        print(
            f"[mock] UPSTREAM HIT #{STATE['served']} lat={lat} lon={lon} "
            f"units={units} ai={params.get('ai', ['?'])[0]}"
        )

        self._send(
            200,
            build_body(lat, lon, units),
            self._rate_limit_headers(STATE["limit"] - STATE["served"], reset_at),
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--limit", type=int, default=1000, help="Reported monthly cap.")
    parser.add_argument("--fail-after", type=int, default=None, help="429 after N successes.")
    parser.add_argument("--status", type=int, default=None, help="Always return this status.")
    parser.add_argument("--latency", type=float, default=0.0, help="Seconds to delay each response.")
    args = parser.parse_args()

    STATE["limit"] = args.limit
    STATE["fail_after"] = args.fail_after
    STATE["forced_status"] = args.status
    STATE["latency"] = args.latency

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"[mock] Weather-AI stand-in on http://127.0.0.1:{args.port}")
    print(f"[mock] limit={args.limit} fail_after={args.fail_after} "
          f"status={args.status} latency={args.latency}s")
    print("[mock] DEVELOPMENT ONLY - the response body shape is unverified.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[mock] stopped")


if __name__ == "__main__":
    main()
