"""DataProcessor: real xG, dynamic DNA, formation-map fallback, league-only."""
import json
import math
import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from formation_map import lookup_formation
from tactical_engine import (
    get_team_dna as _get_team_dna, formation_matchup, tactical_interaction,
    estimate_high_probability_events, build_reasons, build_attributions,
)

REFEREE_CACHE = os.path.join(os.path.dirname(__file__), "referee_stats.json")


class DataProcessor:
    def __init__(self):
        self.feature_columns = []

    @staticmethod
    def extract_xg_from_statistics(stats_response: List[Dict],
                                   home_id: int, away_id: int
                                   ) -> Optional[Dict]:
        if not isinstance(stats_response, list) or len(stats_response) < 2:
            return None
        out = {}
        for team_stats in stats_response:
            tid = team_stats.get("team", {}).get("id")
            stats = team_stats.get("statistics", [])
            xg = None
            for s in stats:
                if s.get("type", "").lower() in ("expected_goals", "xg"):
                    try:
                        xg = float(s.get("value") or 0.0)
                    except (TypeError, ValueError):
                        xg = None
                    break
            if xg is None:
                return None
            if tid == home_id:
                out["home"] = xg
            elif tid == away_id:
                out["away"] = xg
        if "home" not in out or "away" not in out:
            return None
        return {"home": out["home"], "away": out["away"]}

    def _referee_avg_cards(self, referee: Optional[str]) -> float:
        if not referee:
            return 0.0
        try:
            with open(REFEREE_CACHE) as f:
                data = json.load(f)
            return float(data.get(referee, 0.0))
        except Exception:
            return 0.0

    def _resolve_dna(self, team: str,
                     dynamic_map: Optional[Dict[str, Dict]]) -> Dict:
        if dynamic_map and team in dynamic_map:
            dna = dict(dynamic_map[team])
            mapped = lookup_formation(team, fallback=None)
            if mapped:
                dna["formation"] = mapped
            return dna
        return _get_team_dna(team)

    def build_tactical_context(
        self,
        home: str, away: str,
        outcome: Dict, expected_goals: Dict,
        referee_name: Optional[str] = None,
        model_trainer=None,
        scaled_features=None,
        feature_names=None,
        is_cup: bool = False,
        dynamic_dna: Optional[Dict[str, Dict]] = None,
        home_dna_override: Optional[Dict] = None,
        away_dna_override: Optional[Dict] = None,
    ) -> Dict:
        home_dna = (home_dna_override
                    or self._resolve_dna(home, dynamic_dna))
        away_dna = (away_dna_override
                    or self._resolve_dna(away, dynamic_dna))

        form_match = formation_matchup(
            home_dna["formation"], away_dna["formation"])
        hm, am, style_notes = tactical_interaction(home_dna, away_dna)

        expected_goals = {
            "home": round(expected_goals["home"] * hm, 2),
            "away": round(expected_goals["away"] * am, 2),
        }

        ref_cards = (self._referee_avg_cards(referee_name)
                     if referee_name else None)
        events = estimate_high_probability_events(
            expected_goals, home_dna, away_dna,
            referee_avg_cards=ref_cards)

        cup_penalty = 0.9 if is_cup else 1.0
        events = [{**e, "confidence": round(e["confidence"] * cup_penalty, 1)}
                  for e in events]

        reasons = build_reasons(home, away, home_dna, away_dna,
                                form_match["notes"], style_notes, outcome)
        if is_cup:
            reasons.append("Cup fixture — rotation risk reduces reliability")

        attributions = []
        if model_trainer and scaled_features is not None:
            try:
                if hasattr(model_trainer, "get_shap_attributions"):
                    arr = (scaled_features[0].tolist()
                           if hasattr(scaled_features, "__len__")
                           else scaled_features)
                    attributions = model_trainer.get_shap_attributions(
                        arr, top_k=5)
                else:
                    attributions = build_attributions(
                        model_trainer, scaled_features, feature_names)
            except Exception:
                attributions = []

        threshold = 75.0 if is_cup else 80.0
        return {
            "team_dna": {"home": home_dna, "away": away_dna},
            "formation_matchup": form_match,
            "style_notes": style_notes,
            "expected_goals": expected_goals,
            "all_events": events,
            "high_probability_events": [
                e for e in events if e["confidence"] >= threshold],
            "reasons": reasons,
            "attributions": attributions,
            "is_cup": is_cup,
            "event_threshold": threshold,
        }


def calculate_expected_goals(home_strength: int, away_strength: int,
                             outcome_prediction: Optional[Dict] = None,
                             real_xg: Optional[Dict] = None) -> Dict:
    if real_xg and "home" in real_xg and "away" in real_xg:
        hx = float(real_xg["home"])
        ax = float(real_xg["away"])
    else:
        # FIX: stronger away-side bumps so underdog away teams are not ignored
        if home_strength == 2 and away_strength <= 1:
            hx, ax = np.random.normal(1.6, 0.35), np.random.normal(0.9, 0.25)
        elif away_strength == 2 and home_strength <= 1:
            hx, ax = np.random.normal(0.8, 0.25), np.random.normal(1.6, 0.35)
        elif home_strength == away_strength:
            hx, ax = np.random.normal(1.4, 0.3), np.random.normal(1.3, 0.3)
        else:
            hx, ax = np.random.normal(1.5, 0.3), np.random.normal(1.2, 0.25)

    # FIX: confidence-based adjustment only when model is confident AND xG
    # does not already contradict it
    if outcome_prediction and outcome_prediction.get("confidence", 0) > 0.55:
        p = outcome_prediction.get("prediction")
        if p == "Home Win" and hx >= ax - 0.2:
            hx += 0.15; ax -= 0.05
        elif p == "Away Win" and ax >= hx - 0.2:
            hx -= 0.05; ax += 0.15

    return {"home": max(0.3, float(hx)), "away": max(0.3, float(ax))}


def generate_score_probabilities(expected_goals: Dict,
                                 max_goals: int = 6) -> List[Dict]:
    hx, ax = expected_goals["home"], expected_goals["away"]
    # FIX: negative-binomial-style overdispersion for goal totals
    # (r > 1 widens the distribution vs pure Poisson)
    r_dispersion = 4.0
    def _negbin_pmf(k: int, mu: float) -> float:
        if mu <= 0:
            return 1.0 if k == 0 else 0.0
        r = r_dispersion
        p = r / (r + mu)
        from math import lgamma, exp, log
        return exp(lgamma(k + r) - lgamma(r) - lgamma(k + 1)
                   + r * log(p) + k * log(1 - p))

    scores = []
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            ph = _negbin_pmf(h, hx)
            pa = _negbin_pmf(a, ax)
            p = ph * pa
            if p > 0.001:
                scores.append({"score": (h, a), "probability": float(p)})
    scores.sort(key=lambda x: x["probability"], reverse=True)
    total = sum(s["probability"] for s in scores) or 1.0
    for s in scores:
        s["probability"] /= total
    return scores[:10]