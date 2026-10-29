import os
import time
import pandas as pd                      # <-- FIX: added top-level import
from datetime import date, datetime, timedelta
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS

from api_client import FootballAPI, current_season, get_today_local
from european_leagues import (
    EuropeanLeaguesAPI, ALL_COMPETITIONS, ALL_LEAGUE_IDS, TOP5_LEAGUES, TEAMS_CACHE_PATH)
from real_data_collector import RealDataCollector
from data_processor import (
    DataProcessor, calculate_expected_goals, generate_score_probabilities)
from feature_builder import FeatureBuilder
from model_trainer import ModelTrainer
from predictions_store import (
    init_db, save_prediction, has_prediction, settle_finished,
    accuracy_stats, recent_predictions, save_model_version,
    latest_model_version,
)
from dna_builder import build_team_dna, save_dna_cache, load_dna_cache

app = Flask(__name__)
CORS(app)

MODEL_PATH = os.path.join("models", "football_model.joblib")
TRAINING_DF_PATH = os.path.join("training_data", "matches_all.parquet")

api_client = FootballAPI(tier=os.environ.get("API_TIER", "pro"))
eu_api = EuropeanLeaguesAPI(tier=os.environ.get("API_TIER", "pro"))
data_processor = DataProcessor()
model_trainer = ModelTrainer()
feature_builder = FeatureBuilder(api_client)
collector = RealDataCollector(api_client)

TOP5_LEAGUE_IDS = set(TOP5_LEAGUES.values())

STRONG = [
    'Manchester City', 'Liverpool', 'Arsenal',
    'Real Madrid', 'Barcelona', 'Atlético de Madrid',
    'Inter', 'Juventus', 'AC Milan', 'Napoli',
    'Bayern Munich', 'Bayer Leverkusen', 'Borussia Dortmund',
    'Paris Saint-Germain', 'Marseille', 'Monaco',
]
MODERATE = [
    'Manchester United', 'Chelsea', 'Tottenham', 'Newcastle United',
    'Aston Villa', 'Brighton & Hove Albion',
    'Sevilla', 'Villarreal', 'Real Sociedad', 'Real Betis',
    'Roma', 'Lazio', 'Atalanta', 'Fiorentina',
    'RB Leipzig', 'VfB Stuttgart', 'Eintracht Frankfurt',
    'Lille', 'Lyon', 'Nice', 'Lens', 'Rennes',
]

_training_df = None
_dynamic_dna = {}


def team_strength(name: str) -> int:
    if name in STRONG: return 2
    if name in MODERATE: return 1
    return 0


def load_or_collect_training_data():
    global _training_df
    if _training_df is not None:
        return _training_df
    if os.path.exists(TRAINING_DF_PATH):
        try:
            _training_df = pd.read_parquet(TRAINING_DF_PATH)
            return _training_df
        except Exception as e:
            print(f"[data] parquet load failed: {e}")
    seasons = [current_season(), current_season() - 1]
    try:
        df = collector.collect_all(seasons, leagues=TOP5_LEAGUES)
        if not df.empty:
            collector.save(df)
            _training_df = df
            return df
    except Exception as e:
        print(f"[data] collection failed: {e}")
    _training_df = pd.DataFrame()
    return _training_df


def build_features_for_training(df):
    if df.empty:
        return df
    rows = []
    for _, r in df.sort_values("timestamp").iterrows():
        try:
            feats = feature_builder.build(
                home_id=r["home_id"], away_id=r["away_id"],
                df=df[df["timestamp"] < r["timestamp"]],
                kickoff_ts=r["timestamp"],
                home_strength=team_strength(r["home"]),
                away_strength=team_strength(r["away"]))
            rows.append((feats, r["result"], r["timestamp"]))
        except Exception:
            continue
    if not rows:
        return pd.DataFrame()
    feat_cols = ["home_position", "away_position",
                 "home_points", "away_points",
                 "home_goal_diff", "away_goal_diff",
                 "home_win_rate", "away_win_rate",
                 "home_draw_rate", "away_draw_rate",
                 "home_attack_strength", "away_attack_strength",
                 "home_defense_strength", "away_defense_strength",
                 "home_form", "away_form",
                 "position_difference", "points_difference"]
    out = pd.DataFrame([r[0] for r in rows], columns=feat_cols)
    out["result"] = [r[1] for r in rows]
    out["timestamp"] = [r[2] for r in rows]
    return out


def retrain_from_real_data():
    df = load_or_collect_training_data()
    if df.empty or len(df) < 100:
        return {"ok": False, "reason": "insufficient data"}
    feat_df = build_features_for_training(df)
    if feat_df.empty:
        return {"ok": False, "reason": "feature build failed"}
    acc, metrics = model_trainer.train_model(feat_df)
    if acc is None:
        return {"ok": False, "reason": "training failed"}
    model_trainer.save_model(MODEL_PATH)
    version = f"v_{int(time.time())}"
    save_model_version(version, len(feat_df), metrics)
    return {"ok": True, "accuracy": acc, "metrics": metrics,
            "version": version, "n": len(feat_df)}


def ensure_model():
    if model_trainer.is_trained:
        return
    if model_trainer.load_model(MODEL_PATH):
        return
    print("[model] no model — attempting real-data retrain")
    result = retrain_from_real_data()
    if not result.get("ok"):
        print(f"[model] fallback synthetic; reason: {result}")


def get_dna_map():
    global _dynamic_dna
    if _dynamic_dna:
        return _dynamic_dna
    cached = load_dna_cache()
    if cached:
        _dynamic_dna = cached
        return cached
    df = load_or_collect_training_data()
    if not df.empty:
        _dynamic_dna = build_team_dna(df)
        save_dna_cache(_dynamic_dna)
    return _dynamic_dna


def make_prediction(home: str, away: str,
                    fixture_id: int = None, league: str = "",
                    kickoff: str = "", referee: str = None,
                    kickoff_ts: float = None, is_cup: bool = False,
                    home_id: int = 0, away_id: int = 0,
                    real_xg: dict = None) -> dict:
    hs, aws = team_strength(home), team_strength(away)
    df = load_or_collect_training_data()

    try:
        features = feature_builder.build(
            home_id=home_id, away_id=away_id,
            df=df if not df.empty else None,
            kickoff_ts=kickoff_ts or time.time(),
            home_strength=hs, away_strength=aws)
    except Exception:
        features = [4, 7, 48, 38, 18, 10, 0.6, 0.45, 0.22, 0.28,
                    1.8, 1.5, 1.0, 1.1, 10, 7, -3, 10]

    try:
        outcome = model_trainer.predict_match(features)
    except Exception:
        outcome = {"prediction": "Home Win",
                   "probabilities": {"Home Win": 0.45, "Draw": 0.30,
                                     "Away Win": 0.25},
                   "confidence": 0.45, "_scaled_features": None}

    scaled = outcome.pop("_scaled_features", None)
    xg = calculate_expected_goals(hs, aws, outcome, real_xg=real_xg)

    # ---------- FIX: reconcile model label with xG ----------
    if not real_xg:
        xg_home_win = xg["home"] > xg["away"] + 0.15
        xg_away_win = xg["away"] > xg["home"] + 0.15
        xg_draw = abs(xg["home"] - xg["away"]) <= 0.15

        model_pred = outcome["prediction"]
        model_conf = outcome["confidence"]

        if xg_away_win and model_pred == "Home Win":
            outcome["prediction"] = "Away Win"
            outcome["probabilities"] = {
                "Home Win": round(outcome["probabilities"]["Home Win"] * 0.7, 3),
                "Draw":    outcome["probabilities"]["Draw"],
                "Away Win": round(1 - outcome["probabilities"]["Home Win"] * 0.7
                                   - outcome["probabilities"]["Draw"], 3),
            }
            outcome["confidence"] = max(outcome["probabilities"].values())
        elif xg_home_win and model_pred == "Away Win":
            outcome["prediction"] = "Home Win"
            outcome["probabilities"] = {
                "Home Win": round(1 - outcome["probabilities"]["Away Win"] * 0.7
                                   - outcome["probabilities"]["Draw"], 3),
                "Draw":    outcome["probabilities"]["Draw"],
                "Away Win": round(outcome["probabilities"]["Away Win"] * 0.7, 3),
            }
            outcome["confidence"] = max(outcome["probabilities"].values())
        elif xg_draw and model_pred != "Draw":
            outcome["prediction"] = "Draw"
            outcome["probabilities"] = {
                "Home Win": round(outcome["probabilities"]["Home Win"] * 0.75, 3),
                "Draw":    round(0.25 + outcome["probabilities"]["Draw"] * 0.5, 3),
                "Away Win": round(outcome["probabilities"]["Away Win"] * 0.75, 3),
            }
            outcome["confidence"] = max(outcome["probabilities"].values())
    # ---------------------------------------------------------

    scores = generate_score_probabilities(xg)
    top = max(scores, key=lambda x: x["probability"])

    tactical = data_processor.build_tactical_context(
        home, away, outcome, xg,
        referee_name=referee,
        model_trainer=model_trainer,
        scaled_features=scaled,
        feature_names=model_trainer.feature_names,
        is_cup=is_cup,
        dynamic_dna=get_dna_map(),
    )

    if outcome["confidence"] < 0.45 and not tactical["high_probability_events"]:
        return {
            "status": "insufficient_confidence",
            "home_team": home, "away_team": away,
            "prediction": None,
            "reason": "Model confidence below 45% and no threshold events",
        }

    payload = {
        "fixture_id": fixture_id,
        "home": home, "away": away, "league": league, "kickoff": kickoff,
        "prediction": outcome["prediction"],
        "confidence": outcome["confidence"],
        "probabilities": outcome["probabilities"],
        "expected_goals": tactical["expected_goals"],
        "events": tactical["high_probability_events"],
        "reasons": tactical["reasons"],
        "is_cup": is_cup,
        "data_age_sec": api_client.last_cache_age_sec,
        "model_version": latest_model_version() or "unknown",
    }
    if fixture_id and not has_prediction(fixture_id):
        try:
            save_prediction(payload)
        except Exception as e:
            print(f"[store] save failed: {e}")

    return {
        "home_team": home, "away_team": away,
        "prediction": outcome["prediction"],
        "probabilities": outcome["probabilities"],
        "confidence": outcome["confidence"],
        "expected_goals": tactical["expected_goals"],
        "score_probabilities": [
            {"score": f"{s['score'][0]}-{s['score'][1]}",
             "probability": s["probability"]} for s in scores],
        "most_likely_score": {
            "display": f"{top['score'][0]}-{top['score'][1]}",
            "probability": top["probability"]},
        "team_dna": tactical["team_dna"],
        "formation_matchup": tactical["formation_matchup"],
        "high_probability_events": tactical["high_probability_events"],
        "all_events": tactical["all_events"],
        "reasons": tactical["reasons"],
        "attributions": tactical["attributions"],
        "is_cup": is_cup,
        "event_threshold": tactical["event_threshold"],
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/today-fixtures")
def today_fixtures():
    include_cups = request.args.get("include_cups") in ("1", "true", "yes")
    allowed = (ALL_LEAGUE_IDS if include_cups else TOP5_LEAGUE_IDS)
    today = get_today_local().isoformat()
    try:
        data = api_client.get_fixtures_by_date(today)
        if not data or not data.get("response"):
            return jsonify({"date": today, "fixtures": [],
                            "message": "No fixtures found."})
        fixtures = []
        for item in data["response"]:
            league_id = item["league"]["id"]
            if league_id not in allowed:
                continue
            is_cup = league_id not in TOP5_LEAGUE_IDS
            try:
                fixtures.append({
                    "fixture_id": item["fixture"]["id"],
                    "date": item["fixture"]["date"],
                    "timestamp": item["fixture"].get("timestamp"),
                    "status": item["fixture"]["status"]["short"],
                    "venue": (item["fixture"]["venue"] or {}).get("name", "TBA"),
                    "home_team": item["teams"]["home"]["name"],
                    "away_team": item["teams"]["away"]["name"],
                    "home_id": item["teams"]["home"]["id"],
                    "away_id": item["teams"]["away"]["id"],
                    "league": item["league"]["name"],
                    "league_id": league_id,
                    "is_cup": is_cup,
                    "round": item["league"].get("round", ""),
                    "referee": item["fixture"].get("referee"),
                })
            except Exception:
                continue
        return jsonify({"date": today, "fixtures": fixtures,
                        "include_cups": include_cups})
    except Exception as e:
        return jsonify({"date": today, "fixtures": [], "message": str(e)})


@app.route("/api/predict", methods=["POST"])
def predict():
    body = request.get_json(silent=True) or {}
    home = (body.get("home_team") or "").strip()
    away = (body.get("away_team") or "").strip()
    if not home or not away or home == away:
        return jsonify({"error": "Valid home and away teams required"}), 400

    real_xg = None
    fixture_id = body.get("fixture_id")
    if fixture_id:
        stats = api_client.get_fixture_statistics(fixture_id)
        if stats and stats.get("response"):
            real_xg = data_processor.extract_xg_from_statistics(
                stats["response"],
                body.get("home_id", 0),
                body.get("away_id", 0))

    try:
        return jsonify(make_prediction(
            home, away, fixture_id=fixture_id,
            league=body.get("league", ""),
            kickoff=body.get("kickoff", ""),
            referee=body.get("referee"),
            kickoff_ts=body.get("timestamp"),
            is_cup=body.get("is_cup", False),
            home_id=body.get("home_id", 0),
            away_id=body.get("away_id", 0),
            real_xg=real_xg))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/settle", methods=["POST"])
def settle():
    try:
        yesterday = (get_today_local() - timedelta(days=1)).isoformat()
        data = api_client.get_fixtures_by_date(yesterday)
        if not data or not data.get("response"):
            return jsonify({"settled": 0, "message": "No finished fixtures"})
        n = settle_finished(data["response"])
        return jsonify({"settled": n})
    except Exception as e:
        return jsonify({"settled": 0, "error": str(e)}), 200


@app.route("/api/retrain", methods=["POST"])
def retrain():
    result = retrain_from_real_data()
    return jsonify(result), (200 if result.get("ok") else 500)


@app.route("/api/accuracy")
def accuracy():
    try:
        return jsonify(accuracy_stats())
    except Exception as e:
        return jsonify({"settled": 0, "error": str(e)})


@app.route("/api/recent")
def recent():
    try:
        return jsonify(recent_predictions(20))
    except Exception:
        return jsonify([])


@app.route("/api/formations")
def formations():
    from formation_map import TEAM_FORMATION_OVERRIDES
    return jsonify(TEAM_FORMATION_OVERRIDES)


@app.route("/api/teams")
def get_all_teams():
    teams = eu_api.load_teams_cache()
    if not teams:
        teams = eu_api.fetch_and_cache_all_teams()
    return jsonify(teams)


@app.route("/api/health")
def health():
    return jsonify({
        "api": api_client.health(),
        "model_trained": model_trainer.is_trained,
        "model_version": latest_model_version(),
        "features": len(model_trainer.feature_names),
        "training_rows": 0 if _training_df is None else len(_training_df),
        "dna_teams": len(_dynamic_dna),
        "time": datetime.utcnow().isoformat(),
    })


if __name__ == "__main__":
    init_db()
    ensure_model()
    print("[startup] Checking team cache...")
    if not os.path.exists(TEAMS_CACHE_PATH):
        print("[startup] Fetching all teams from API (this may take a minute)...")
        eu_api.fetch_and_cache_all_teams()
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)