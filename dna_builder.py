"""Derive Team DNA from real fixtures, honoring the formation map."""
import json
import os
from typing import Dict, Optional

import numpy as np
import pandas as pd

from formation_map import lookup_formation

DNA_CACHE = os.path.join(os.path.dirname(__file__), "team_dna_dynamic.json")


def _classify_style(possession: float, attack_per_game: float,
                    defense_per_game: float) -> str:
    if possession >= 0.55:
        return "possession"
    if possession <= 0.42 and attack_per_game > 1.2:
        return "counter"
    if possession <= 0.42 and defense_per_game < 1.1:
        return "low_block"
    if attack_per_game > 1.6 and defense_per_game > 1.4:
        return "high_press"
    if attack_per_game > 1.4:
        return "direct"
    return "balanced"


def build_team_dna(df: pd.DataFrame, min_matches: int = 3) -> Dict[str, Dict]:
    """Build {team_name: dna_dict} using real matches + formation_map."""
    if df.empty:
        return {}

    teams = pd.concat([
        df[["home_id", "home"]].rename(columns={"home_id": "id", "home": "name"}),
        df[["away_id", "away"]].rename(columns={"away_id": "id", "away": "name"}),
    ]).drop_duplicates("id")

    out = {}
    for _, t in teams.iterrows():
        tid, name = t["id"], t["name"]
        sub = df[(df["home_id"] == tid) | (df["away_id"] == tid)]
        
        # Relaxed min_matches to 3 so newly promoted teams get data
        if len(sub) < min_matches:
            continue

        gf = ga = 0.0
        for _, r in sub.iterrows():
            is_home = r["home_id"] == tid
            gf += r["home_goals"] if is_home else r["away_goals"]
            ga += r["away_goals"] if is_home else r["home_goals"]
        n = len(sub)
        attack = gf / n
        defense = ga / n

        poss_proxy = min(0.75, 0.35 + (attack - defense) * 0.08)
        style = _classify_style(poss_proxy, attack, defense)

        # Lookup real formation or dynamically generate
        formation = lookup_formation(name, fallback=None)

        home_sub = df[df["home_id"] == tid]
        away_sub = df[df["away_id"] == tid]
        hw = (home_sub["result"] == "H").mean() if len(home_sub) else 0.5
        aw = (away_sub["result"] == "A").mean() if len(away_sub) else 0.5
        home_boost = max(0.0, min(0.25, hw - aw))

        out[name] = {
            "style": style,
            "formation": formation,
            "aggression": round(min(0.9, 0.4 + defense * 0.3), 2),
            "discipline": round(max(0.4, 0.9 - attack * 0.1), 2),
            "home_boost": round(home_boost, 3),
            "attack": round(attack, 2),
            "defense": round(defense, 2),
            "sample_size": n,
        }
    return out


def save_dna_cache(dna: Dict[str, Dict]):
    try:
        with open(DNA_CACHE, "w") as f:
            json.dump(dna, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def load_dna_cache() -> Dict[str, Dict]:
    try:
        with open(DNA_CACHE) as f:
            return json.load(f)
    except Exception:
        return {}