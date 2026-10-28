"""Team DNA, formation, style interactions, events, explainability."""
import math
from typing import Dict, List, Tuple

from formation_map import lookup_formation

# Expanded to cover all formations in 4-3-3.txt
FORMATIONS: Dict[str, Dict[str, float]] = {
    "4-3-3":     {"defense": 0.80, "midfield": 0.85, "attack": 0.95, "width": 0.85, "press": 0.80},
    "4-2-3-1":   {"defense": 0.85, "midfield": 0.90, "attack": 0.85, "width": 0.75, "press": 0.75},
    "4-4-2":     {"defense": 0.85, "midfield": 0.75, "attack": 0.80, "width": 0.80, "press": 0.70},
    "3-5-2":     {"defense": 0.75, "midfield": 0.95, "attack": 0.85, "width": 0.90, "press": 0.75},
    "3-4-3":     {"defense": 0.70, "midfield": 0.80, "attack": 0.95, "width": 0.85, "press": 0.85},
    "5-4-1":     {"defense": 0.98, "midfield": 0.70, "attack": 0.55, "width": 0.55, "press": 0.45},
    "5-3-2":     {"defense": 0.95, "midfield": 0.75, "attack": 0.65, "width": 0.55, "press": 0.50},
    "4-1-4-1":   {"defense": 0.88, "midfield": 0.85, "attack": 0.70, "width": 0.70, "press": 0.65},
    "4-5-1":     {"defense": 0.92, "midfield": 0.88, "attack": 0.55, "width": 0.60, "press": 0.55},
    "4-1-2-1-2": {"defense": 0.78, "midfield": 0.95, "attack": 0.85, "width": 0.40, "press": 0.75},
    "4-3-2-1":   {"defense": 0.80, "midfield": 0.90, "attack": 0.85, "width": 0.50, "press": 0.78},
    "3-4-1-2":   {"defense": 0.78, "midfield": 0.88, "attack": 0.88, "width": 0.55, "press": 0.78},
    "4-4-1-1":   {"defense": 0.85, "midfield": 0.78, "attack": 0.75, "width": 0.72, "press": 0.68},
    "4-3-1-2":   {"defense": 0.78, "midfield": 0.92, "attack": 0.88, "width": 0.45, "press": 0.75},
    "3-1-4-2":   {"defense": 0.75, "midfield": 0.92, "attack": 0.88, "width": 0.70, "press": 0.80},
    "3-4-2-1":   {"defense": 0.80, "midfield": 0.90, "attack": 0.88, "width": 0.65, "press": 0.82},
    # Niche systems seen in Bundesliga / Ligue 1
    "4-2-2-2":   {"defense": 0.78, "midfield": 0.88, "attack": 0.90, "width": 0.55, "press": 0.85},
    "2-4-4":     {"defense": 0.60, "midfield": 0.95, "attack": 0.98, "width": 0.85, "press": 0.90},
    "3-2-2-3":   {"defense": 0.72, "midfield": 0.92, "attack": 0.96, "width": 0.80, "press": 0.88},
    "3-2-4-1":   {"defense": 0.75, "midfield": 0.90, "attack": 0.92, "width": 0.78, "press": 0.85},
}

STYLE_INTERACTIONS: Dict[Tuple[str, str], Tuple[float, float]] = {
    ("possession", "low_block"):   (1.25, 0.70),
    ("possession", "counter"):     (0.90, 1.30),
    ("high_press",  "possession"): (1.20, 0.85),
    ("high_press",  "high_press"): (1.15, 1.15),
    ("counter",     "possession"): (1.25, 0.85),
    ("counter",     "low_block"):  (1.10, 0.75),
    ("direct",      "low_block"):  (1.15, 0.80),
    ("wing_play",   "narrow"):     (1.20, 0.90),
    ("physical",    "technical"):  (1.15, 0.95),
}

# African legacy entries kept; European teams will now resolve via
# formation_map lookup, so DEFAULT_DNA is only a last resort.
TEAM_DNA: Dict[str, Dict] = {
    "Al Ahly":           {"style": "possession", "formation": "4-2-3-1", "aggression": 0.65, "discipline": 0.80, "home_boost": 0.15},
    "Zamalek":           {"style": "counter",    "formation": "4-3-3",   "aggression": 0.75, "discipline": 0.65, "home_boost": 0.12},
    "Wydad Casablanca":  {"style": "high_press", "formation": "4-3-3",   "aggression": 0.80, "discipline": 0.70, "home_boost": 0.18},
    "Raja Casablanca":   {"style": "possession", "formation": "4-2-3-1", "aggression": 0.70, "discipline": 0.75, "home_boost": 0.14},
    "Mamelodi Sundowns": {"style": "possession", "formation": "4-2-3-1", "aggression": 0.60, "discipline": 0.85, "home_boost": 0.16},
    "Kaizer Chiefs":     {"style": "direct",     "formation": "4-4-2",   "aggression": 0.70, "discipline": 0.65, "home_boost": 0.10},
    "Orlando Pirates":   {"style": "wing_play",  "formation": "4-3-3",   "aggression": 0.75, "discipline": 0.70, "home_boost": 0.12},
    "Esperance":         {"style": "high_press", "formation": "3-5-2",   "aggression": 0.85, "discipline": 0.72, "home_boost": 0.15},
    "Etoile du Sahel":   {"style": "counter",    "formation": "4-4-2",   "aggression": 0.70, "discipline": 0.78, "home_boost": 0.10},
    "TP Mazembe":        {"style": "physical",   "formation": "4-4-2",   "aggression": 0.85, "discipline": 0.68, "home_boost": 0.18},
    "Simba SC":          {"style": "possession", "formation": "4-3-3",   "aggression": 0.65, "discipline": 0.75, "home_boost": 0.12},
    "Young Africans":    {"style": "counter",    "formation": "4-2-3-1", "aggression": 0.72, "discipline": 0.70, "home_boost": 0.10},
    "Pyramids FC":       {"style": "possession", "formation": "4-3-3",   "aggression": 0.60, "discipline": 0.80, "home_boost": 0.12},
    "Hearts of Oak":     {"style": "direct",     "formation": "4-4-2",   "aggression": 0.75, "discipline": 0.65, "home_boost": 0.14},
    "Asante Kotoko":     {"style": "high_press", "formation": "4-3-3",   "aggression": 0.80, "discipline": 0.68, "home_boost": 0.15},
}

DEFAULT_DNA = {
    "style": "balanced", "formation": "4-4-2",
    "aggression": 0.60, "discipline": 0.70, "home_boost": 0.10,
}

# Style inference from formation (used when only formation is known)
_FORMATION_STYLE = {
    "5-4-1": "low_block", "5-3-2": "low_block",
    "4-5-1": "low_block", "4-1-4-1": "counter",
    "3-4-2-1": "high_press", "3-4-3": "high_press",
    "3-5-2": "counter", "4-2-2-2": "high_press",
    "4-3-3": "possession", "4-2-3-1": "possession",
    "4-4-2": "direct", "4-4-1-1": "direct",
    "4-1-2-1-2": "possession", "4-3-2-1": "possession",
    "3-4-1-2": "possession", "4-3-1-2": "possession",
    "3-1-4-2": "possession", "2-4-4": "high_press",
    "3-2-2-3": "possession", "3-2-4-1": "possession",
}


def get_team_dna(team_name: str) -> Dict:
    """Resolve DNA for a team. Priority: static table → formation lookup."""
    if team_name in TEAM_DNA:
        return dict(TEAM_DNA[team_name])

    form = lookup_formation(team_name, fallback=None)
    if form:
        style = _FORMATION_STYLE.get(form, "balanced")
        return {
            "style": style,
            "formation": form,
            "aggression": 0.65 if style in ("high_press", "physical") else 0.60,
            "discipline": 0.75 if style == "possession" else 0.70,
            "home_boost": 0.12,
            "_source": "formation_map",
        }

    return dict(DEFAULT_DNA)


def formation_matchup(home_form: str, away_form: str) -> Dict:
    h = FORMATIONS.get(home_form, FORMATIONS["4-4-2"])
    a = FORMATIONS.get(away_form, FORMATIONS["4-4-2"])
    home_adv = ((h["midfield"] - a["midfield"]) * 0.5
                + (h["attack"] - a["defense"]) * 0.3
                + (h["press"] - a["press"]) * 0.2)
    away_adv = ((a["midfield"] - h["midfield"]) * 0.5
                + (a["attack"] - h["defense"]) * 0.3
                + (a["press"] - h["press"]) * 0.2)
    notes = []
    if h["midfield"] - a["midfield"] > 0.10:
        notes.append(f"{home_form} controls the middle third against {away_form}")
    if a["midfield"] - h["midfield"] > 0.10:
        notes.append(f"{away_form} dominates central midfield")
    if h["width"] > 0.85 and a["defense"] > 0.90:
        notes.append("Home width vs compact defence — expect crosses")
    if h["defense"] > 0.90 and a["attack"] < 0.70:
        notes.append("Home low block likely to frustrate away attack")
    if a["width"] > 0.85 and h["defense"] > 0.90:
        notes.append("Away wing-backs vs compact back line")
    return {"home_advantage": home_adv, "away_advantage": away_adv, "notes": notes}


def tactical_interaction(home_dna: Dict, away_dna: Dict) -> Tuple[float, float, List[str]]:
    pair = (home_dna["style"], away_dna["style"])
    hm, am = STYLE_INTERACTIONS.get(pair, (1.0, 1.0))
    notes = []
    if pair in STYLE_INTERACTIONS:
        favour = "home" if hm > am else ("away" if am > hm else "a balanced tempo")
        notes.append(
            f"{home_dna['style'].replace('_', ' ').title()} vs "
            f"{away_dna['style'].replace('_', ' ').title()} typically favours {favour}"
        )
    return hm, am, notes


def estimate_high_probability_events(
    expected_goals: Dict,
    home_dna: Dict,
    away_dna: Dict,
    referee_avg_cards: float = None,
) -> List[Dict]:
    h_xg = max(0.1, float(expected_goals.get("home", 1.0)))
    a_xg = max(0.1, float(expected_goals.get("away", 1.0)))
    total_xg = h_xg + a_xg

    def p_over(threshold: float) -> float:
        k = int(math.floor(threshold))
        cdf = sum(math.exp(-total_xg) * (total_xg ** i) / math.factorial(i)
                  for i in range(k + 1))
        return max(0.0, min(1.0, 1.0 - cdf))

    expected_corners = 8.0 + total_xg * 1.1
    p_over_4_5_corners = 1 - math.exp(-max(0.1, expected_corners - 4.5))

    aggression_avg = (home_dna["aggression"] + away_dna["aggression"]) / 2
    discipline_avg = (home_dna["discipline"] + away_dna["discipline"]) / 2
    base_cards = 2.0 + aggression_avg * 3.0 - discipline_avg * 1.0
    expected_cards = referee_avg_cards if referee_avg_cards else max(0.5, base_cards)
    p_at_least_one_card = 1 - math.exp(-expected_cards)

    home_share = h_xg / max(0.01, total_xg)
    p_home_1_corner = 1 - math.exp(-max(0.1, expected_corners * home_share * 0.6))
    p_away_1_corner = 1 - math.exp(-max(0.1, expected_corners * (1 - home_share) * 0.6))

    pos_w = {"possession": 0.60, "high_press": 0.55, "counter": 0.42,
             "direct": 0.45, "wing_play": 0.50, "physical": 0.48, "balanced": 0.50}
    home_poss = pos_w.get(home_dna["style"], 0.5) + home_dna.get("home_boost", 0.0) * 0.3
    away_poss = pos_w.get(away_dna["style"], 0.5)
    total_poss = max(0.01, home_poss + away_poss)
    p_home_possession = home_poss / total_poss
    p_away_card = 1 - math.exp(-max(0.1, expected_cards * 0.55))

    events = [
        {"name": "Over 0.5 Goals",              "confidence": round(p_over(0.5) * 100, 1)},
        {"name": "Over 1.5 Goals",              "confidence": round(p_over(1.5) * 100, 1)},
        {"name": "Under 5.5 Goals",             "confidence": round((1 - p_over(5.5)) * 100, 1)},
        {"name": "Over 4.5 Corners",            "confidence": round(p_over_4_5_corners * 100, 1)},
        {"name": "At Least 1 Yellow Card",      "confidence": round(p_at_least_one_card * 100, 1)},
        {"name": "Home Team 1+ Corner",         "confidence": round(p_home_1_corner * 100, 1)},
        {"name": "Away Team 1+ Corner",         "confidence": round(p_away_1_corner * 100, 1)},
        {"name": "Home Team Most Possession",   "confidence": round(p_home_possession * 100, 1)},
        {"name": "Away Team To Receive A Card", "confidence": round(p_away_card * 100, 1)},
    ]
    return sorted(events, key=lambda e: e["confidence"], reverse=True)


def build_reasons(home, away, home_dna, away_dna, formation_notes, style_notes, outcome):
    reasons = []
    if home_dna.get("home_boost", 0) > 0.12:
        reasons.append(f"{home} strong home record (+{int(home_dna['home_boost']*100)}%)")
    if away_dna.get("home_boost", 0) < 0.10:
        reasons.append(f"{away} weaker away form")
    reasons.extend(style_notes)
    reasons.extend(formation_notes)
    if home_dna["aggression"] - away_dna["aggression"] > 0.15:
        reasons.append(f"{home} higher pressing intensity likely to force turnovers")
    if away_dna["discipline"] < 0.65:
        reasons.append(f"{away} disciplinary record adds card-market value")
    c = outcome.get("confidence", 0.0)
    if c > 0.70:
        reasons.append("Model + tactical signals align on a high-confidence outcome")
    elif c < 0.50:
        reasons.append("Tight tactical matchup — outcome probabilities are compressed")
    return reasons


def build_attributions(model_trainer, X_scaled, feature_names) -> List[Dict]:
    try:
        import shap
        explainer = shap.TreeExplainer(model_trainer.model)
        sv = explainer.shap_values(X_scaled)
        if isinstance(sv, list):
            stacked = sv[0]
            for arr in sv[1:]:
                mask = abs(arr) > abs(stacked)
                stacked = arr * mask + stacked * (~mask)
            vals = stacked[0]
        else:
            vals = sv[0]
        total = sum(abs(v) for v in vals) or 1.0
        pairs = sorted(
            [(feature_names[i], float(vals[i]) / total) for i in range(len(feature_names))],
            key=lambda p: abs(p[1]), reverse=True)[:5]
        return [{"label": n.replace("_", " ").title(),
                 "impact": round(v, 3)} for n, v in pairs]
    except Exception:
        try:
            import numpy as np
            imps = model_trainer.model.feature_importances_
            vals = X_scaled[0]
            scored = sorted(
                [(feature_names[i], float(imps[i]) * (1 if vals[i] >= 0 else -1))
                 for i in range(len(feature_names))],
                key=lambda p: abs(p[1]), reverse=True)[:5]
            return [{"label": n.replace("_", " ").title(),
                     "impact": round(v, 3)} for n, v in scored]
        except Exception:
            return []