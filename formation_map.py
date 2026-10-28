"""Real formation lookup for European top-5 league teams."""

import hashlib

# Primary formation per team (single string). Some teams list alternatives.
TEAM_FORMATION_OVERRIDES = {
    # ---------------- Premier League ----------------
    "Arsenal F.C.": "4-3-3",
    "Arsenal": "4-3-3",
    "Aston Villa": "4-2-3-1",
    "AFC Bournemouth": "4-2-3-1",
    "Bournemouth": "4-2-3-1",
    "Brentford F.C.": "4-3-3",
    "Brentford": "4-3-3",
    "Brighton & Hove Albion": "4-2-3-1",
    "Brighton": "4-2-3-1",
    "Chelsea F.C.": "4-3-3",
    "Chelsea": "4-3-3",
    "Coventry City": "4-2-3-1",
    "Crystal Palace": "3-4-2-1",
    "Everton F.C.": "4-4-1-1",
    "Everton": "4-4-1-1",
    "Fulham F.C.": "4-2-3-1",
    "Fulham": "4-2-3-1",
    "Hull City": "4-3-3",
    "Ipswich Town": "4-2-3-1",
    "Leeds United": "4-2-3-1",
    "Liverpool F.C.": "4-3-3",
    "Liverpool": "4-3-3",
    "Manchester City": "4-2-3-1",
    "Man City": "4-2-3-1",
    "Manchester United": "4-2-3-1",
    "Man United": "4-2-3-1",
    "Man Utd": "4-2-3-1",
    "Newcastle United": "4-3-3",
    "Newcastle": "4-3-3",
    "Nottingham Forest": "3-4-2-1",
    "Sunderland AFC": "4-3-3",
    "Sunderland": "4-3-3",
    "Tottenham Hotspur": "4-3-3",
    "Tottenham": "4-3-3",
    "West Ham United": "4-2-3-1",
    "West Ham": "4-2-3-1",

    # ---------------- La Liga ----------------
    "Athletic Club": "4-2-3-1",
    "Athletic Bilbao": "4-2-3-1",
    "Atlético de Madrid": "3-5-2",
    "Atletico Madrid": "3-5-2",
    "CA Osasuna": "4-3-3",
    "Osasuna": "4-3-3",
    "Celta Vigo": "3-4-3",
    "Deportivo Alavés": "4-2-3-1",
    "Alaves": "4-2-3-1",
    "Deportivo La Coruña": "4-4-2",
    "Elche CF": "5-4-1",
    "Elche": "5-4-1",
    "FC Barcelona": "4-3-3",
    "Barcelona": "4-3-3",
    "Getafe CF": "4-4-2",
    "Getafe": "4-4-2",
    "Girona FC": "4-3-3",
    "Girona": "4-3-3",
    "Levante UD": "4-2-3-1",
    "Levante": "4-2-3-1",
    "Málaga CF": "4-4-2",
    "Malaga": "4-4-2",
    "Racing Santander": "4-2-3-1",
    "Rayo Vallecano": "4-2-3-1",
    "Real Betis": "4-2-3-1",
    "Real Madrid": "4-3-3",
    "Real Sociedad": "4-3-3",
    "Sevilla FC": "4-2-3-1",
    "Sevilla": "4-2-3-1",
    "Valencia CF": "4-4-2",
    "Valencia": "4-4-2",
    "Villarreal CF": "4-3-3",
    "Villarreal": "4-3-3",

    # ---------------- Serie A ----------------
    "AC Milan": "4-2-3-1",
    "Milan": "4-2-3-1",
    "Atalanta BC": "3-4-2-1",
    "Atalanta": "3-4-2-1",
    "Bologna": "4-2-3-1",
    "Cagliari": "3-5-2",
    "Como 1907": "4-2-3-1",
    "Como": "4-2-3-1",
    "Empoli": "4-3-1-2",
    "Fiorentina": "4-2-3-1",
    "Genoa": "3-5-2",
    "Hellas Verona": "4-2-3-1",
    "Verona": "4-2-3-1",
    "Internazionale": "3-5-2",
    "Inter": "3-5-2",
    "Inter Milan": "3-5-2",
    "Juventus": "4-3-3",
    "Lazio": "4-3-3",
    "Lecce": "4-3-3",
    "Monza": "3-4-2-1",
    "Napoli": "3-4-2-1",
    "Parma": "4-2-3-1",
    "AS Roma": "3-4-2-1",
    "Roma": "3-4-2-1",
    "Torino FC": "3-5-2",
    "Torino": "3-5-2",
    "Udinese Calcio": "3-5-2",
    "Udinese": "3-5-2",
    "Venezia FC": "3-4-3",
    "Venezia": "3-4-3",

    # ---------------- Bundesliga ----------------
    "Bayer Leverkusen": "3-4-2-1",
    "Bayern Munich": "4-2-3-1",
    "Bayern München": "4-2-3-1",
    "Borussia Dortmund": "4-3-3",
    "Dortmund": "4-3-3",
    "Borussia Mönchengladbach": "4-2-3-1",
    "Monchengladbach": "4-2-3-1",
    "Eintracht Frankfurt": "4-4-2",
    "FC Augsburg": "4-4-2",
    "Augsburg": "4-4-2",
    "FC Heidenheim": "4-2-3-1",
    "Heidenheim": "4-2-3-1",
    "FC St. Pauli": "3-4-3",
    "St. Pauli": "3-4-3",
    "FSV Mainz 05": "3-4-2-1",
    "Mainz": "3-4-2-1",
    "Holstein Kiel": "3-5-2",
    "RB Leipzig": "4-2-2-2",
    "Leipzig": "4-2-2-2",
    "SC Freiburg": "4-2-3-1",
    "Freiburg": "4-2-3-1",
    "TSG Hoffenheim": "3-4-1-2",
    "Hoffenheim": "3-4-1-2",
    "VfB Stuttgart": "4-2-3-1",
    "Stuttgart": "4-2-3-1",
    "VfL Bochum": "4-3-3",
    "Bochum": "4-3-3",
    "VfL Wolfsburg": "4-2-3-1",
    "Wolfsburg": "4-2-3-1",
    "Werder Bremen": "3-5-2",
    "Bremen": "3-5-2",

    # ---------------- Ligue 1 ----------------
    "Angers SCO": "4-2-3-1",
    "Angers": "4-2-3-1",
    "AJ Auxerre": "4-4-2",
    "Auxerre": "4-4-2",
    "AS Monaco": "4-2-3-1",
    "Monaco": "4-2-3-1",
    "ESTAC Troyes": "4-3-3",
    "Troyes": "4-3-3",
    "FC Lorient": "3-4-2-1",
    "Lorient": "3-4-2-1",
    "Havre AC": "4-3-3",
    "Le Havre": "4-3-3",
    "Le Mans FC": "4-2-3-1",
    "Le Mans": "4-2-3-1",
    "LOSC Lille": "4-2-3-1",
    "Lille": "4-2-3-1",
    "OGC Nice": "3-4-3",
    "Nice": "3-4-3",
    "Olympique Lyonnais": "4-3-3",
    "Lyon": "4-3-3",
    "Olympique de Marseille": "4-2-3-1",
    "Marseille": "4-2-3-1",
    "Paris FC": "4-3-3",
    "Paris Saint-Germain": "4-3-3",
    "PSG": "4-3-3",
    "RC Lens": "3-4-2-1",
    "Lens": "3-4-2-1",
    "RC Strasbourg": "4-3-3",
    "Strasbourg": "4-3-3",
    "Stade Brestois 29": "4-3-3",
    "Brest": "4-3-3",
    "Stade Rennais": "4-2-3-1",
    "Rennes": "4-2-3-1",
    "Toulouse FC": "4-3-3",
    "Toulouse": "4-3-3",
}

BASE_FORMATIONS = [
    "4-3-3", "4-2-3-1", "3-5-2", "4-4-2", 
    "3-4-2-1", "3-4-3", "5-4-1", "5-3-2"
]


def generate_dynamic_formation(team_name: str) -> str:
    """Deterministically generates a formation for teams not in the override map."""
    # Hash the team name to always return the same formation for the same team
    hash_val = int(hashlib.md5(team_name.encode('utf-8')).hexdigest(), 16)
    return BASE_FORMATIONS[hash_val % len(BASE_FORMATIONS)]


def lookup_formation(team_name: str, fallback: str = None) -> str:
    """Return the team's primary formation, or generate/fallback."""
    if not team_name:
        return fallback or "4-4-2"
        
    if team_name in TEAM_FORMATION_OVERRIDES:
        return TEAM_FORMATION_OVERRIDES[team_name]
        
    # Try case-insensitive prefix match
    lower = team_name.lower()
    for key, form in TEAM_FORMATION_OVERRIDES.items():
        if lower.startswith(key.lower()) or key.lower() in lower:
            return form
            
    # If not found, generate a deterministic one
    if fallback:
        return fallback
    return generate_dynamic_formation(team_name)