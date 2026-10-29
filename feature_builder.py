"""Real-data feature builder with time-decay and opponent strength adjustment."""
import math
import time
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from api_client import FootballAPI


def time_decay_weight(days_ago: float, half_life_days: float = 45.0) -> float:
    return 0.5 ** (days_ago / half_life_days)


class FeatureBuilder:
    def __init__(self, api: Optional[FootballAPI] = None):
        self.api = api

    @staticmethod
    def _rolling_team_stats(df: pd.DataFrame, team_id: int,
                            before_ts: float, last_n: int = 10) -> Dict:
        sub = df[((df["home_id"] == team_id) | (df["away_id"] == team_id))
                 & (df["timestamp"] < before_ts)]
        if sub.empty:
            return {"matches": 0}
        sub = sub.sort_values("timestamp").tail(last_n)

        now = before_ts
        wsum = 0.0
        gf = ga = w = d = l = 0.0
        for _, r in sub.iterrows():
            days_ago = max(0.0, (now - r["timestamp"]) / 86400.0)
            wt = time_decay_weight(days_ago)
            is_home = r["home_id"] == team_id
            tg = r["home_goals"] if is_home else r["away_goals"]
            og = r["away_goals"] if is_home else r["home_goals"]
            gf += wt * tg
            ga += wt * og
            if tg > og: w += wt
            elif tg == og: d += wt
            else: l += wt
            wsum += wt
        if wsum == 0:
            return {"matches": 0}
        return {
            "matches": len(sub),
            "goals_for": gf / wsum,
            "goals_against": ga / wsum,
            "win_rate": w / wsum,
            "draw_rate": d / wsum,
            "loss_rate": l / wsum,
            "form_pts": (w * 3 + d) / wsum,
        }

    @staticmethod
    def _team_elo(df: pd.DataFrame, team_id: int, before_ts: float,
                  k: float = 20.0, base: float = 1500.0) -> float:
        hist = df[df["timestamp"] < before_ts].sort_values("timestamp")
        elo = {tid: base for tid in
               set(hist["home_id"]).union(set(hist["away_id"]))}
        for _, r in hist.iterrows():
            h, a = r["home_id"], r["away_id"]
            eh = elo.get(h, base)
            ea = elo.get(a, base)
            exp_h = 1 / (1 + 10 ** ((ea - eh) / 400.0))
            if r["result"] == "H": s_h = 1.0
            elif r["result"] == "D": s_h = 0.5
            else: s_h = 0.0
            elo[h] = eh + k * (s_h - exp_h)
            elo[a] = ea + k * ((1 - s_h) - (1 - exp_h))
        return elo.get(team_id, base)

    def build(self, home_id: int, away_id: int,
              home_name: str = "", away_name: str = "",
              df: Optional[pd.DataFrame] = None,
              kickoff_ts: Optional[float] = None,
              league_id: Optional[int] = None,
              home_strength: int = 0, away_strength: int = 0
              ) -> List[float]:
        kickoff_ts = kickoff_ts or time.time()

        if df is not None and not df.empty:
            hf = self._rolling_team_stats(df, home_id, kickoff_ts)
            af = self._rolling_team_stats(df, away_id, kickoff_ts)
            h_elo = self._team_elo(df, home_id, kickoff_ts)
            a_elo = self._team_elo(df, away_id, kickoff_ts)
        else:
            hf = {"matches": 0}
            af = {"matches": 0}
            h_elo = a_elo = 1500.0

        def fill(stats, strength):
            return {
                "win_rate": stats.get("win_rate", 0.45 if strength == 2 else 0.30),
                "draw_rate": stats.get("draw_rate", 0.25),
                "attack": stats.get("goals_for",
                                    1.8 if strength == 2 else 1.2),
                "defense": stats.get("goals_against",
                                     0.8 if strength == 2 else 1.3),
                "form_pts": stats.get("form_pts", 5.0),
            }

        h = fill(hf, home_strength)
        a = fill(af, away_strength)

        # FIX: wider ELO -> position mapping so away teams are not
        # automatically pushed to bottom of table.
        h_pos = max(1, min(20, int(round(20 - (h_elo - 1250) / 35))))
        a_pos = max(1, min(20, int(round(20 - (a_elo - 1250) / 35))))
        h_pts = max(0, int(round((h_elo - 1250) * 0.2)))
        a_pts = max(0, int(round((a_elo - 1250) * 0.2)))

        return [
            h_pos, a_pos, h_pts, a_pts,
            h["attack"] - h["defense"],
            a["attack"] - a["defense"],
            h["win_rate"], a["win_rate"],
            h["draw_rate"], a["draw_rate"],
            h["attack"], a["attack"],
            h["defense"], a["defense"],
            h["form_pts"], a["form_pts"],
            h_pos - a_pos, h_pts - a_pts,
        ]