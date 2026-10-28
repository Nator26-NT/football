"""Prediction persistence + settlement + retrain-trigger stats."""
import json
import os
import sqlite3
import time
from typing import Dict, List, Optional

DB = os.path.join(os.path.dirname(__file__), "predictions.db")


def _connect():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _connect() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fixture_id INTEGER,
            home TEXT, away TEXT, league TEXT, kickoff TEXT,
            created_at REAL,
            prediction TEXT, confidence REAL,
            probabilities TEXT, expected_goals TEXT,
            events TEXT, reasons TEXT,
            is_cup INTEGER DEFAULT 0,
            data_age_sec REAL,
            model_version TEXT,
            actual_result TEXT, actual_home INTEGER, actual_away INTEGER,
            settled_at REAL
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_fixture "
                  "ON predictions(fixture_id)")
        c.execute("""CREATE TABLE IF NOT EXISTS model_versions (
            version TEXT PRIMARY KEY,
            trained_at REAL,
            n_samples INTEGER,
            metrics TEXT
        )""")
        # Migrate older schemas safely
        for col, decl in [
            ("is_cup", "INTEGER DEFAULT 0"),
            ("data_age_sec", "REAL"),
            ("model_version", "TEXT"),
        ]:
            try:
                c.execute(f"ALTER TABLE predictions ADD COLUMN {col} {decl}")
            except sqlite3.OperationalError:
                pass


def has_prediction(fixture_id: int) -> bool:
    with _connect() as c:
        return c.execute(
            "SELECT 1 FROM predictions WHERE fixture_id=? LIMIT 1",
            (fixture_id,)).fetchone() is not None


def save_prediction(payload: Dict):
    with _connect() as c:
        c.execute("""INSERT INTO predictions
            (fixture_id, home, away, league, kickoff, created_at,
             prediction, confidence, probabilities, expected_goals,
             events, reasons, is_cup, data_age_sec, model_version)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            payload.get("fixture_id"),
            payload["home"], payload["away"],
            payload.get("league", ""), payload.get("kickoff", ""),
            time.time(),
            payload["prediction"], payload["confidence"],
            json.dumps(payload["probabilities"]),
            json.dumps(payload["expected_goals"]),
            json.dumps(payload.get("events", [])),
            json.dumps(payload.get("reasons", [])),
            1 if payload.get("is_cup") else 0,
            payload.get("data_age_sec"),
            payload.get("model_version", ""),
        ))


def save_model_version(version: str, n_samples: int, metrics: Dict):
    with _connect() as c:
        c.execute("""INSERT OR REPLACE INTO model_versions
            (version, trained_at, n_samples, metrics)
            VALUES (?,?,?,?)""",
            (version, time.time(), n_samples, json.dumps(metrics)))


def latest_model_version() -> Optional[str]:
    with _connect() as c:
        row = c.execute(
            "SELECT version FROM model_versions "
            "ORDER BY trained_at DESC LIMIT 1").fetchone()
    return row["version"] if row else None


def unsettled_count(since_ts: float = 0.0) -> int:
    with _connect() as c:
        return c.execute(
            "SELECT COUNT(*) c FROM predictions "
            "WHERE actual_result IS NULL AND created_at>=?",
            (since_ts,)).fetchone()["c"]


def settle_finished(fixtures: List[Dict]) -> int:
    if not isinstance(fixtures, list):
        return 0
    settled = 0
    with _connect() as c:
        for f in fixtures:
            try:
                if f.get("fixture", {}).get("status", {}).get("short") != "FT":
                    continue
                fx_id = f["fixture"]["id"]
                hg = f["goals"]["home"]; ag = f["goals"]["away"]
                if hg is None or ag is None:
                    continue
                actual = "H" if hg > ag else ("A" if ag > hg else "D")
                cur = c.execute("""UPDATE predictions
                    SET actual_result=?, actual_home=?, actual_away=?,
                        settled_at=?
                    WHERE fixture_id=? AND actual_result IS NULL""",
                    (actual, hg, ag, time.time(), fx_id))
                settled += cur.rowcount
            except Exception:
                continue
    return settled


def accuracy_stats() -> Dict:
    with _connect() as c:
        rows = c.execute("""SELECT prediction, actual_result,
                                   actual_home, actual_away, events
                            FROM predictions
                            WHERE actual_result IS NOT NULL""").fetchall()
    if not rows:
        return {"settled": 0}
    total = len(rows)
    hits = 0
    goal_hits = {"Over 0.5 Goals": 0, "Over 1.5 Goals": 0,
                 "Under 5.5 Goals": 0}
    goal_seen = {k: 0 for k in goal_hits}
    omap = {"Home Win": "H", "Away Win": "A", "Draw": "D"}
    for r in rows:
        if omap.get(r["prediction"]) == r["actual_result"]:
            hits += 1
        try:
            evts = json.loads(r["events"]) if r["events"] else []
        except Exception:
            evts = []
        tg = (r["actual_home"] or 0) + (r["actual_away"] or 0)
        for e in evts:
            name = e.get("name")
            if name not in goal_hits:
                continue
            goal_seen[name] += 1
            if name == "Over 0.5 Goals" and tg >= 1: goal_hits[name] += 1
            elif name == "Over 1.5 Goals" and tg >= 2: goal_hits[name] += 1
            elif name == "Under 5.5 Goals" and tg <= 5: goal_hits[name] += 1
    acc = {"settled": total,
           "outcome_accuracy": round(hits / total, 3) if total else None}
    for name in goal_hits:
        seen = goal_seen[name]
        acc[f"{name}_accuracy"] = round(goal_hits[name] / seen, 3) if seen else None
    return acc


def recent_predictions(limit: int = 20) -> List[Dict]:
    with _connect() as c:
        rows = c.execute("""
            SELECT fixture_id, home, away, league, prediction, confidence,
                   actual_result, actual_home, actual_away, created_at,
                   is_cup, model_version
            FROM predictions
            ORDER BY created_at DESC LIMIT ?""", (limit,)).fetchall()
    return [dict(r) for r in rows]