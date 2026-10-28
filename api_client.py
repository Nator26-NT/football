import requests
import time
import json
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional

CACHE_DIR = os.path.join(os.path.dirname(__file__), ".cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# Define your app's target timezone (South Africa Standard Time)
APP_TIMEZONE = ZoneInfo("Africa/Johannesburg")


def get_today_local() -> date:
    """Returns the current date in the app's target timezone (SAST)."""
    return datetime.now(APP_TIMEZONE).date()


def current_season(today: Optional[date] = None) -> int:
    """API-Football uses season start year. July+ = new season."""
    d = today or get_today_local()
    return d.year if d.month >= 7 else d.year - 1


class FootballAPI:
    # API-Football per-minute rate limits by tier
    TIER_LIMITS = {
        "free": 10,
        "pro": 300,
        "ultra": 450,
        "mega": 900,
    }

    def __init__(self, tier: str = "pro"):
        self.base_url = "https://v3.football.api-sports.io"
        self.headers = {
            'x-rapidapi-key': os.environ.get(
                'API_FOOTBALL_KEY', '18fde68c9204c01be253d70a920d1966'),
            'x-rapidapi-host': 'v3.football.api-sports.io',
        }
        # Sliding-window rate limiter (per minute)
        self.tier = tier
        self.per_minute_limit = self.TIER_LIMITS.get(tier, 300)
        self._call_timestamps: List[float] = []
        # Track freshness of last returned data
        self.last_cache_age_sec: Optional[float] = None
        self.last_from_cache: bool = False
        self.last_error: Optional[str] = None
        # Live API-returned quota headers
        self.api_remaining: Optional[int] = None
        self.api_limit: Optional[int] = None
        self.request_count = 0

    # ---------- Cache helpers ----------
    def _cache_path(self, endpoint: str, params: Dict) -> str:
        key = endpoint + "_" + "_".join(
            f"{k}={params[k]}" for k in sorted(params))
        safe = "".join(c if c.isalnum() or c in "-_=" else "_" for c in key)
        return os.path.join(CACHE_DIR, safe + ".json")

    def _read_cache(self, path: str, max_age_sec: int) -> Optional[Dict]:
        if not os.path.exists(path):
            return None
        age = time.time() - os.path.getmtime(path)
        if age > max_age_sec:
            return None
        try:
            with open(path) as f:
                self.last_cache_age_sec = age
                self.last_from_cache = True
                return json.load(f)
        except Exception:
            return None

    def _read_stale_cache(self, path: str) -> Optional[Dict]:
        """Return cache regardless of age, plus its age."""
        if not os.path.exists(path):
            return None
        try:
            age = time.time() - os.path.getmtime(path)
            with open(path) as f:
                self.last_cache_age_sec = age
                self.last_from_cache = True
                return json.load(f)
        except Exception:
            return None

    def _write_cache(self, path: str, data: Dict):
        try:
            with open(path, "w") as f:
                json.dump(data, f)
            self.last_cache_age_sec = 0.0
        except Exception:
            pass

    # ---------- Rate limiter ----------
    def _throttle(self):
        now = time.time()
        # Drop calls older than 60s
        self._call_timestamps = [
            t for t in self._call_timestamps if now - t < 60.0]
        if len(self._call_timestamps) >= self.per_minute_limit - 2:
            # Wait until oldest call falls out of window
            sleep_for = 60.0 - (now - self._call_timestamps[0]) + 0.5
            if sleep_for > 0:
                time.sleep(sleep_for)
                now = time.time()
                self._call_timestamps = [
                    t for t in self._call_timestamps if now - t < 60.0]
        self._call_timestamps.append(now)

    # ---------- Main request ----------
    def make_request(self, endpoint: str, params: Dict,
                     cache_sec: int = 300) -> Optional[Dict]:
        cache_path = self._cache_path(endpoint, params)
        cached = self._read_cache(cache_path, cache_sec)
        if cached is not None:
            return cached

        self._throttle()
        self.request_count += 1
        self.last_error = None

        try:
            url = f"{self.base_url}/{endpoint}"
            resp = requests.get(url, headers=self.headers,
                                params=params, timeout=30)
            # Update live quota from headers
            try:
                self.api_remaining = int(
                    resp.headers.get("x-ratelimit-requests-remaining",
                                     resp.headers.get("x-ratelimit-remaining",
                                                      -1)))
                self.api_limit = int(
                    resp.headers.get("x-ratelimit-requests-limit",
                                     resp.headers.get("x-ratelimit-limit",
                                                      -1)))
            except (TypeError, ValueError):
                pass

            if resp.status_code == 200:
                data = resp.json()
                if data.get("errors"):
                    errs = data["errors"]
                    if isinstance(errs, dict) and not errs:
                        # Empty errors dict means no error
                        self._write_cache(cache_path, data)
                        return data
                    self.last_error = str(errs)
                    return self._read_stale_cache(cache_path)
                self._write_cache(cache_path, data)
                self.last_from_cache = False
                return data

            self.last_error = f"status_{resp.status_code}"
            if resp.status_code == 429:
                time.sleep(5)  # backoff
            return self._read_stale_cache(cache_path)
        except Exception as e:
            self.last_error = str(e)
            return self._read_stale_cache(cache_path)

    # ---------- Endpoints (unchanged signatures) ----------
    def get_fixtures_by_date(self, target_date: Optional[str] = None,
                             timezone: str = "Africa/Johannesburg"
                             ) -> Optional[Dict]:
        if target_date is None:
            target_date = get_today_local().isoformat()
        return self.make_request(
            "fixtures",
            {"date": target_date, "timezone": timezone},
            cache_sec=180)

    def get_team_recent_fixtures(self, team_id: int,
                                 last: int = 10) -> Optional[Dict]:
        return self.make_request(
            "fixtures", {"team": team_id, "last": last}, cache_sec=3600)

    def get_fixture_statistics(self, fixture_id: int) -> Optional[Dict]:
        return self.make_request(
            "fixtures/statistics", {"fixture": fixture_id}, cache_sec=86400)

    def get_lineups(self, fixture_id: int) -> Optional[Dict]:
        return self.make_request(
            "fixtures/lineups", {"fixture": fixture_id}, cache_sec=86400)

    def get_referee_history(self, referee: str,
                            last: int = 30) -> Optional[Dict]:
        return self.make_request(
            "fixtures", {"referee": referee, "last": last},
            cache_sec=6 * 3600)

    # ---------- Health ----------
    def health(self) -> Dict:
        return {
            "tier": self.tier,
            "per_minute_limit": self.per_minute_limit,
            "calls_last_60s": len(self._call_timestamps),
            "api_remaining": self.api_remaining,
            "api_limit": self.api_limit,
            "last_error": self.last_error,
            "last_cache_age_sec": self.last_cache_age_sec,
            "last_from_cache": self.last_from_cache,
            "total_requests": self.request_count,
        }