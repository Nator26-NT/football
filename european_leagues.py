"""European Top 5 Leagues & Domestic Cups API Extension."""
import os
import json
from typing import Dict, List, Optional

from api_client import FootballAPI, current_season

TOP5_LEAGUES = {
    "Premier League": 39,
    "La Liga": 140,
    "Serie A": 135,
    "Bundesliga": 78,
    "Ligue 1": 61,
}

DOMESTIC_CUPS = {
    "FA Cup": 45,
    "Copa del Rey": 143,
    "Coppa Italia": 137,
    "DFB-Pokal": 81,
    "Coupe de France": 66,
}

ALL_COMPETITIONS = {**TOP5_LEAGUES, **DOMESTIC_CUPS}
ALL_LEAGUE_IDS = set(ALL_COMPETITIONS.values())

TEAMS_CACHE_PATH = os.path.join(os.path.dirname(__file__), "all_teams_cache.json")


class EuropeanLeaguesAPI(FootballAPI):
    def __init__(self, tier: str = "pro"):
        super().__init__(tier=tier)
        self.league_names = {v: k for k, v in ALL_COMPETITIONS.items()}
        self.cup_names = {v: k for k, v in DOMESTIC_CUPS.items()}
        self._validated_ids: Optional[set] = None

    # ---------- Validation ----------
    def validate_league_ids(self) -> Dict[int, bool]:
        """Ping /leagues?id=X for each tracked competition. Cached 30 days."""
        results = {}
        for name, lid in ALL_COMPETITIONS.items():
            data = self.make_request(
                "leagues", {"id": lid}, cache_sec=30 * 24 * 3600)
            ok = bool(data and data.get("response"))
            results[lid] = ok
            if not ok:
                self.last_error = f"league_id {lid} ({name}) validation failed"
        self._validated_ids = {k for k, v in results.items() if v}
        return results

    # ---------- Team retrieval ----------
    def get_league_teams(self, league_id: int,
                        season: Optional[int] = None
                        ) -> Optional[List[Dict]]:
        if league_id not in self.league_names:
            self.last_error = f"Unknown league_id: {league_id}"
            return None
        season = season or current_season()
        data = self.make_request(
            "teams", {"league": league_id, "season": season},
            cache_sec=7 * 24 * 3600)
        if not data or not data.get("response"):
            return None
        teams = []
        for item in data["response"]:
            try:
                t = item["team"]
                teams.append({
                    "team_id": t["id"],
                    "name": t["name"],
                    "code": t.get("code"),
                    "country": t.get("country"),
                    "logo": t.get("logo"),
                    "league_id": league_id,
                    "league_name": self.league_names.get(league_id, "Unknown"),
                    "is_cup": league_id in self.cup_names,
                })
            except Exception:
                continue
        return teams

    def get_all_top5_teams(self,
                          season: Optional[int] = None
                          ) -> Dict[int, List[Dict]]:
        season = season or current_season()
        result = {}
        for league_id in ALL_COMPETITIONS.values():
            teams = self.get_league_teams(league_id, season)
            if teams:
                result[league_id] = teams
        return result

    def get_all_team_ids(self,
                        season: Optional[int] = None) -> Dict[int, str]:
        season = season or current_season()
        flat = {}
        for teams in self.get_all_top5_teams(season).values():
            for t in teams:
                flat[t["team_id"]] = t["name"]
        return flat

    # ---------- Dynamic All Teams Fetch & Cache ----------
    def fetch_and_cache_all_teams(self, season: Optional[int] = None) -> Dict:
        """Pulls all teams from the API and caches them in a flat dictionary."""
        season = season or current_season()
        flat_teams = {}
        for league_name, league_id in ALL_COMPETITIONS.items():
            teams = self.get_league_teams(league_id, season)
            if teams:
                for t in teams:
                    flat_teams[str(t["team_id"])] = {
                        "name": t["name"],
                        "league": league_name,
                        "is_cup": t["is_cup"],
                        "logo": t.get("logo")
                    }
        try:
            with open(TEAMS_CACHE_PATH, "w") as f:
                json.dump(flat_teams, f, indent=2)
        except Exception as e:
            print(f"[cache] Failed to save teams: {e}")
        return flat_teams

    def load_teams_cache(self) -> Dict:
        """Loads the cached teams dictionary."""
        if os.path.exists(TEAMS_CACHE_PATH):
            try:
                with open(TEAMS_CACHE_PATH) as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    # ---------- Reverse mapping ----------
    def get_team_current_league(self, team_id: int,
                                season: Optional[int] = None
                                ) -> Optional[str]:
        season = season or current_season()
        cache_path = self._cache_path(
            "teams_mapping", {"season": season})
        cached = self._read_cache(cache_path, 7 * 24 * 3600)
        if cached is not None:
            return cached.get(str(team_id))
        mapping = {}
        for league_id in ALL_COMPETITIONS.values():
            teams = self.get_league_teams(league_id, season)
            if teams:
                for t in teams:
                    mapping[str(t["team_id"])] = t["league_name"]
        self._write_cache(cache_path, mapping)
        return mapping.get(str(team_id))