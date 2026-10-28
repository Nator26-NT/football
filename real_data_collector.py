"""Collect real match results from API-Football for training."""
import os
import json
import time
from datetime import date, timedelta
from typing import Dict, List, Optional

import pandas as pd

from api_client import FootballAPI, current_season
from european_leagues import ALL_COMPETITIONS

DATA_DIR = os.path.join(os.path.dirname(__file__), "training_data")
os.makedirs(DATA_DIR, exist_ok=True)


class RealDataCollector:
    def __init__(self, api: FootballAPI):
        self.api = api

    def _raw_path(self, season: int) -> str:
        return os.path.join(DATA_DIR, f"matches_{season}.parquet")

    def collect_season(self, league_id: int, season: int,
                       force: bool = False) -> pd.DataFrame:
        """Download every fixture for a league/season. Uses cache to skip."""
        cache_path = os.path.join(
            DATA_DIR, f"league_{league_id}_{season}.json")
        if os.path.exists(cache_path) and not force:
            with open(cache_path) as f:
                raw = json.load(f)
        else:
            data = self.api.make_request(
                "fixtures",
                {"league": league_id, "season": season},
                cache_sec=30 * 24 * 3600)
            if not data or not data.get("response"):
                return pd.DataFrame()
            raw = data["response"]
            with open(cache_path, "w") as f:
                json.dump(raw, f)

        rows = []
        for item in raw:
            try:
                fx = item["fixture"]
                status = fx["status"]["short"]
                if status != "FT":
                    continue
                hg = item["goals"]["home"]
                ag = item["goals"]["away"]
                if hg is None or ag is None:
                    continue
                league = item["league"]
                home_id = item["teams"]["home"]["id"]
                away_id = item["teams"]["away"]["id"]
                rows.append({
                    "fixture_id": fx["id"],
                    "league_id": league["id"],
                    "league_name": league["name"],
                    "season": season,
                    "date": fx["date"],
                    "timestamp": fx.get("timestamp"),
                    "home_id": home_id,
                    "away_id": away_id,
                    "home": item["teams"]["home"]["name"],
                    "away": item["teams"]["away"]["name"],
                    "home_goals": hg,
                    "away_goals": ag,
                    "referee": fx.get("referee"),
                    "venue": (fx.get("venue") or {}).get("name"),
                    "result": "H" if hg > ag else ("A" if ag > hg else "D"),
                })
            except Exception:
                continue
        return pd.DataFrame(rows)

    def collect_all(self, seasons: List[int],
                    leagues: Optional[Dict[str, int]] = None
                    ) -> pd.DataFrame:
        leagues = leagues or ALL_COMPETITIONS
        frames = []
        for season in seasons:
            for name, lid in leagues.items():
                print(f"[collect] {name} {season}")
                df = self.collect_season(lid, season)
                if not df.empty:
                    frames.append(df)
        if not frames:
            return pd.DataFrame()
        combined = pd.concat(frames, ignore_index=True)
        combined = combined.drop_duplicates(subset=["fixture_id"])
        return combined.sort_values("timestamp").reset_index(drop=True)

    def save(self, df: pd.DataFrame, name: str = "matches_all.parquet"):
        path = os.path.join(DATA_DIR, name)
        df.to_parquet(path, index=False)
        print(f"[collect] saved {len(df)} rows to {path}")
        return path