/**
 * app.js — Full frontend logic for European football prediction app.
 * Features:
 *  - Loads today's fixtures (top-5 leagues + domestic cups) grouped by league
 *  - Click a fixture to predict; prediction panel toggles inline
 *  - Shows prediction, confidence, xG, likely score, Team DNA cards
 *  - High-probability events (>= threshold, default 80%, cups 75%)
 *  - Reveal all events, SHAP feature impact, reasons
 *  - Cup badge + data-freshness warning
 *  - Auto-refresh button
 */

document.addEventListener('DOMContentLoaded', () => {
    const refreshBtn = document.getElementById('refreshBtn');
    if (refreshBtn) refreshBtn.addEventListener('click', loadTodayFixtures);
    loadTodayFixtures();
});

/* --------------------------------------------------------------
 * Fixtures loader
 * -------------------------------------------------------------- */
async function loadTodayFixtures() {
    const list = document.getElementById('fixturesList');
    const dateEl = document.getElementById('todayDate');
    if (!list) return;

    list.innerHTML = '<div class="loading">Loading today\'s fixtures...</div>';

    try {
        const res = await fetch('/api/today-fixtures');
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();

        if (dateEl) {
            dateEl.textContent = '\uD83D\uDCC5 ' + (data.date || '');
        }

        if (!data.fixtures || data.fixtures.length === 0) {
            list.innerHTML = '<div class="loading">' +
                esc(data.message || 'No fixtures today.') + '</div>';
            return;
        }

        // Group by league
        const groups = {};
        data.fixtures.forEach(f => {
            const key = f.league || 'Other Competitions';
            (groups[key] = groups[key] || []).push(f);
        });

        // Sort league keys: leagues first, cups second, alphabetical
        const leagueKeys = Object.keys(groups).sort((a, b) => {
            const aCup = groups[a][0].is_cup ? 1 : 0;
            const bCup = groups[b][0].is_cup ? 1 : 0;
            if (aCup !== bCup) return aCup - bCup;
            return a.localeCompare(b);
        });

        let html = '';
        leagueKeys.forEach(league => {
            const isCup = groups[league][0].is_cup;
            const icon = isCup ? '\uD83C\uDFC6' : '\u26BD';
            html += '<div class="league-group">' +
                '<h3 class="league-title">' + icon + ' ' + esc(league) +
                (isCup ? '<span class="badge cup">CUP</span>' : '') +
                '</h3><div class="fixtures-grid">';
            groups[league].forEach(f => { html += buildFixtureCard(f); });
            html += '</div></div>';
        });

        list.innerHTML = html;
        attachCardHandlers(data.fixtures);
    } catch (err) {
        console.error(err);
        list.innerHTML = '<div class="loading">Failed to load fixtures: ' +
            esc(err.message) + '</div>';
    }
}

/* --------------------------------------------------------------
 * Fixture card markup
 * -------------------------------------------------------------- */
function buildFixtureCard(f) {
    const id = 'fixture-' + f.fixture_id;
    const time = formatKickoff(f.date);
    const statusBadge = buildStatusBadge(f.status);

    return '' +
        '<div class="fixture-wrapper" id="' + id + '">' +
        '<div class="fixture-card" data-fixture-id="' + f.fixture_id + '">' +
        '<div class="fixture-teams">' +
        '<span class="team-home">' + esc(f.home_team) + '</span>' +
        '<span class="vs">vs</span>' +
        '<span class="team-away">' + esc(f.away_team) + '</span>' +
        '</div>' +
        '<div class="fixture-meta">' +
        '<span>\uD83C\uDFDF\uFE0F ' + esc(f.venue || 'TBA') + '</span>' +
        '<span>\u23F0 ' + esc(time) + ' ' + statusBadge + '</span>' +
        '</div>' +
        (f.round ? '<div class="fixture-round">' + esc(f.round) + '</div>' : '') +
        '<div class="fixture-hint">\uD83D\uDC46 Tap to predict</div>' +
        '</div>' +
        '<div class="prediction-panel hidden" id="panel-' +
        f.fixture_id + '"></div>' +
        '</div>';
}

function buildStatusBadge(status) {
    if (!status) return '';
    const map = {
        'NS': { label: 'Not Started', cls: 'status-ns' },
        '1H': { label: 'Live', cls: 'status-live' },
        '2H': { label: 'Live', cls: 'status-live' },
        'HT': { label: 'Half Time', cls: 'status-live' },
        'FT': { label: 'FT', cls: 'status-ft' },
        'PST': { label: 'Postponed', cls: 'status-pst' },
        'CANC': { label: 'Cancelled', cls: 'status-pst' },
    };
    const s = map[status];
    if (!s) return '';
    return '<span class="status-badge ' + s.cls + '">' + s.label + '</span>';
}

function formatKickoff(isoDate) {
    if (!isoDate) return '';
    try {
        const dt = new Date(isoDate);
        const hh = String(dt.getHours()).padStart(2, '0');
        const mm = String(dt.getMinutes()).padStart(2, '0');
        return hh + ':' + mm;
    } catch {
        return isoDate;
    }
}

/* --------------------------------------------------------------
 * Card click handlers
 * -------------------------------------------------------------- */
function attachCardHandlers(allFixtures) {
    const map = {};
    allFixtures.forEach(f => { map[f.fixture_id] = f; });

    document.querySelectorAll('.fixture-card').forEach(card => {
        card.addEventListener('click', () => {
            const id = card.dataset.fixtureId;
            const fixture = map[id];
            const panel = document.getElementById('panel-' + id);
            if (!fixture || !panel) return;

            if (!panel.classList.contains('hidden')) {
                panel.classList.add('hidden');
                card.classList.remove('active');
                return;
            }

            card.classList.add('active');
            panel.classList.remove('hidden');
            panel.innerHTML = '<div class="loading">Calculating prediction...</div>';
            predictMatch(fixture, panel);
        });
    });
}

/* --------------------------------------------------------------
 * Prediction request
 * -------------------------------------------------------------- */
async function predictMatch(fixture, panel) {
    try {
        const res = await fetch('/api/predict', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                home_team: fixture.home_team,
                away_team: fixture.away_team,
                home_id: fixture.home_id,
                away_id: fixture.away_id,
                fixture_id: fixture.fixture_id,
                league: fixture.league,
                league_id: fixture.league_id,
                kickoff: fixture.date,
                timestamp: fixture.timestamp,
                is_cup: !!fixture.is_cup,
                referee: fixture.referee
            })
        });

        if (!res.ok) {
            const errBody = await res.json().catch(() => ({}));
            throw new Error(errBody.error || ('HTTP ' + res.status));
        }

        const p = await res.json();
        panel.innerHTML = buildPredictionHtml(p);
        attachRevealHandlers(panel);
    } catch (err) {
        console.error(err);
        panel.innerHTML = '<div class="prediction-inner">' +
            '<div class="low-confidence">' +
            '<div class="lc-title">Prediction failed</div>' +
            '<div class="lc-text">' + esc(err.message) + '</div>' +
            '</div></div>';
    }
}

function attachRevealHandlers(panel) {
    panel.querySelectorAll('[data-reveal-events]').forEach(btn => {
        btn.addEventListener('click', () => {
            const block = panel.querySelector('.all-events-block');
            if (!block) return;
            const isHidden = block.classList.toggle('hidden');
            btn.textContent = isHidden ? 'Show all events' : 'Hide extra events';
        });
    });
}

/* --------------------------------------------------------------
 * Prediction markup
 * -------------------------------------------------------------- */
function buildPredictionHtml(p) {
    if (!p) return '<div class="loading">No data</div>';

    if (p.status === 'insufficient_confidence') {
        return '<div class="prediction-inner">' +
            '<div class="low-confidence">' +
            '<div class="lc-title">No confident prediction</div>' +
            '<div class="lc-text">' +
            esc(p.reason || 'Signals below threshold') +
            '</div></div></div>';
    }

    if (p.error) {
        return '<div class="prediction-inner">' +
            '<div class="low-confidence">' +
            '<div class="lc-title">Error</div>' +
            '<div class="lc-text">' + esc(p.error) + '</div>' +
            '</div></div>';
    }

    const pr = p.probabilities || {};
    const h = ((pr['Home Win'] || 0) * 100).toFixed(1);
    const d = ((pr['Draw'] || 0) * 100).toFixed(1);
    const a = ((pr['Away Win'] || 0) * 100).toFixed(1);
    const threshold = p.event_threshold || 80;
    const cupBadge = p.is_cup ?
        ' <span class="badge cup">CUP</span>' : '';

    // Score probabilities
    let scoresHtml = '';
    (p.score_probabilities || []).slice(0, 5).forEach(s => {
        scoresHtml += '<div class="score-row">' +
            '<span class="score-badge">' + esc(s.score) + '</span>' +
            '<div class="score-bar">' +
            '<div class="score-fill" style="width:' +
            (s.probability * 100).toFixed(1) + '%"></div></div>' +
            '<span class="score-pct">' +
            (s.probability * 100).toFixed(1) + '%</span></div>';
    });

    // Events
    const evRow = (e, dim) =>
        '<div class="event-row">' +
        '<span class="event-name">' + esc(e.name) + '</span>' +
        '<span class="event-confidence">' +
        Number(e.confidence).toFixed(1) + '%</span>' +
        '<div class="event-bar"><div class="event-fill' +
        (dim ? ' dim' : '') + '" style="width:' +
        Number(e.confidence) + '%"></div></div></div>';

    const highEvents = p.high_probability_events || [];
    const allEvents = p.all_events || [];
    let eventsHtml = highEvents.map(e => evRow(e, false)).join('');
    let allEventsHtml = allEvents.map(e => evRow(e, true)).join('');

    // Reasons
    let reasonsHtml = '';
    (p.reasons || []).forEach(r => {
        reasonsHtml += '<li>' + esc(r) + '</li>';
    });

    // Attributions
    let attributionsHtml = '';
    (p.attributions || []).forEach(at => {
        const cls = at.impact >= 0 ? 'pos' : 'neg';
        const pct = Math.abs(at.impact * 100).toFixed(1);
        attributionsHtml += '<div class="attribution-row">' +
            '<span class="attr-label">' + esc(at.label) + '</span>' +
            '<div class="attr-bar"><div class="attr-fill ' + cls +
            '" style="width:' + pct + '%"></div></div>' +
            '<span class="attr-value ' + cls + '">' +
            (at.impact >= 0 ? '+' : '-') + pct + '%</span></div>';
    });

    // Data freshness warning
    let dataWarning = '';
    if (p.data_age_sec && p.data_age_sec > 3600) {
        const hours = (p.data_age_sec / 3600).toFixed(1);
        dataWarning = '<div class="data-warning">\u26A0 Data is ' +
            hours + 'h old — prediction reliability reduced</div>';
    }

    // Team DNA cards
    const dna = p.team_dna || { home: {}, away: {} };
    const dnaCard = (name, t) => {
        const style = (t.style || 'balanced').replace(/_/g, ' ');
        return '<div class="tactical-card">' +
            '<div class="tactical-card-title">' + esc(name) + '</div>' +
            '<div class="tactical-row"><span>Formation</span><strong>' +
            esc(t.formation || '—') + '</strong></div>' +
            '<div class="tactical-row"><span>Style</span><strong>' +
            esc(style) + '</strong></div>' +
            '<div class="tactical-row"><span>Aggression</span><strong>' +
            ((t.aggression || 0) * 100).toFixed(0) + '%</strong></div>' +
            '<div class="tactical-row"><span>Discipline</span><strong>' +
            ((t.discipline || 0) * 100).toFixed(0) + '%</strong></div>' +
            '<div class="tactical-row"><span>Home Boost</span><strong>' +
            ((t.home_boost || 0) * 100).toFixed(0) + '%</strong></div>' +
            '</div>';
    };

    // Formation matchup notes
    let formationNotesHtml = '';
    if (p.formation_matchup &&
        p.formation_matchup.notes &&
        p.formation_matchup.notes.length) {
        formationNotesHtml = '<div class="notes-block">' +
            '<div class="pred-subtitle">\uD83E\uDDE9 Formation Matchup</div>' +
            '<ul class="reasons-list">' +
            p.formation_matchup.notes.map(n => '<li>' + esc(n) + '</li>').join('') +
            '</ul></div>';
    }

    // Build final markup
    return '<div class="prediction-inner">' +

        // Pills
        '<div class="prediction-top">' +
        '<div class="pred-pill"><span class="pred-label">Prediction</span>' +
        '<span class="pred-value">' + esc(p.prediction) + cupBadge + '</span></div>' +
        '<div class="pred-pill"><span class="pred-label">Confidence</span>' +
        '<span class="pred-value">' +
        ((p.confidence || 0) * 100).toFixed(1) + '%</span></div>' +
        '<div class="pred-pill"><span class="pred-label">xG</span>' +
        '<span class="pred-value">' +
        (p.expected_goals ? p.expected_goals.home.toFixed(1) : '—') +
        ' - ' +
        (p.expected_goals ? p.expected_goals.away.toFixed(1) : '—') +
        '</span></div>' +
        '<div class="pred-pill"><span class="pred-label">Likely Score</span>' +
        '<span class="pred-value">' +
        (p.most_likely_score ? esc(p.most_likely_score.display) : '—') +
        '</span></div>' +
        '</div>' +

        dataWarning +

        // Team DNA
        '<div class="tactical-grid">' +
        dnaCard(p.home_team, dna.home) +
        dnaCard(p.away_team, dna.away) +
        '</div>' +

        formationNotesHtml +

        // Probabilities
        '<div class="pred-subtitle">\uD83D\uDCC8 Outcome Probabilities</div>' +
        '<div class="prob-bars">' +
        '<div class="prob-row"><span class="prob-label">Home</span>' +
        '<div class="prob-bar"><div class="prob-fill home" style="width:' +
        h + '%"></div><span class="prob-value">' + h + '%</span></div></div>' +
        '<div class="prob-row"><span class="prob-label">Draw</span>' +
        '<div class="prob-bar"><div class="prob-fill draw" style="width:' +
        d + '%"></div><span class="prob-value">' + d + '%</span></div></div>' +
        '<div class="prob-row"><span class="prob-label">Away</span>' +
        '<div class="prob-bar"><div class="prob-fill away" style="width:' +
        a + '%"></div><span class="prob-value">' + a + '%</span></div></div>' +
        '</div>' +

        // High-probability events
        '<div class="pred-subtitle">\u26A1 High-Probability Events (\u2265 ' +
        threshold + '%)</div>' +
        '<div class="events-list">' +
        (eventsHtml ||
            '<div class="empty-events">No events pass the ' +
            threshold + '% threshold for this fixture</div>') +
        '</div>' +

        // Reveal all events
        ((allEvents.length > highEvents.length) ?
            '<button class="reveal-btn" data-reveal-events>' +
            'Show all events</button>' +
            '<div class="all-events-block hidden">' +
            '<div class="events-list">' + allEventsHtml + '</div></div>' :
            '') +

        // Score probabilities
        '<div class="pred-subtitle">\uD83D\uDCCA Top Score Probabilities</div>' +
        '<div class="scores-list">' + scoresHtml + '</div>' +

        // Reasons
        (reasonsHtml ?
            '<div class="pred-subtitle">\uD83E\uDDE0 Why This Prediction</div>' +
            '<ul class="reasons-list">' + reasonsHtml + '</ul>' :
            '') +

        // Attributions
        (attributionsHtml ?
            '<div class="pred-subtitle">\uD83D\uDD0D Feature Impact ' +
            '(SHAP on XGB)</div>' +
            '<div class="attributions">' + attributionsHtml + '</div>' :
            '') +

        '</div>';
}

/* --------------------------------------------------------------
 * HTML escaping
 * -------------------------------------------------------------- */
function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    }[c]));
}