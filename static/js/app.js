/* =========================================================
   SIMPLE HASH ROUTER
   Routes:
     #/                        → home (fixtures list)
     #/fixture/<fixture_id>    → prediction sub-page
   ========================================================= */
const App = {
    fixturesCache: {}, // id → fixture object
    predictionsCache: {}, // id → prediction payload
    currentRoute: null,
};

document.addEventListener('DOMContentLoaded', () => {
    window.addEventListener('hashchange', route);
    route();
});

async function route() {
    const hash = location.hash || '#/';
    const app = document.getElementById('app');
    if (!app) return;

    // fixture sub-page
    const m = hash.match(/^#\/fixture\/(\d+)/);
    if (m) {
        App.currentRoute = 'fixture';
        await renderFixturePage(app, m[1]);
        return;
    }

    // home
    App.currentRoute = 'home';
    await renderHome(app);
}

/* =========================================================
   HOME PAGE
   ========================================================= */
async function renderHome(app) {
    app.innerHTML = `
        <section class="controls">
          <button id="refreshBtn" class="btn" type="button">
            <span aria-hidden="true">🔄</span> Refresh Today's Fixtures
          </button>
        </section>
        <section class="fixtures-section" aria-label="Fixtures list">
          <h2 class="section-title">📅 Today's Fixtures</h2>
          <div id="fixturesList">
            <div class="loading">Loading today’s fixtures…</div>
          </div>
        </section>
    `;

    document.getElementById('refreshBtn')
        .addEventListener('click', loadTodayFixtures);

    await loadTodayFixtures();
}

async function loadTodayFixtures() {
    const list = document.getElementById('fixturesList');
    const dateEl = document.getElementById('todayDate');
    if (!list) return;

    list.innerHTML = '<div class="loading">Loading today’s fixtures…</div>';

    try {
        const res = await fetch('/api/today-fixtures');
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();

        if (dateEl) {
            let displayDate = data.date || '';
            try {
                const d = new Date(data.date + 'T00:00:00');
                displayDate = d.toLocaleDateString('en-GB', {
                    day: 'numeric',
                    month: 'short',
                    year: 'numeric'
                });
            } catch (e) {}
            dateEl.textContent = '📅 ' + displayDate;
        }

        if (!data.fixtures || data.fixtures.length === 0) {
            list.innerHTML = '<div class="loading">' +
                esc(data.message || 'No fixtures today.') + '</div>';
            return;
        }

        // Cache fixtures for sub-page routing
        data.fixtures.forEach(f => {
            App.fixturesCache[f.fixture_id] = f;
        });

        // Group by league
        const groups = {};
        data.fixtures.forEach(f => {
            const key = f.league || 'Other Competitions';
            (groups[key] = groups[key] || []).push(f);
        });

        const leagueKeys = Object.keys(groups).sort((a, b) => {
            const aCup = groups[a][0].is_cup ? 1 : 0;
            const bCup = groups[b][0].is_cup ? 1 : 0;
            if (aCup !== bCup) return aCup - bCup;
            return a.localeCompare(b);
        });

        let html = '';
        leagueKeys.forEach(league => {
            const isCup = groups[league][0].is_cup;
            const icon = isCup ? '🏆' : '⚽';
            html += '<div class="league-group">' +
                '<h3 class="league-title">' + icon + ' ' + esc(league) +
                (isCup ? '<span class="badge cup">CUP</span>' : '') +
                '</h3><div class="fixtures-grid">';
            groups[league].forEach(f => { html += buildFixtureCard(f); });
            html += '</div></div>';
        });

        list.innerHTML = html;
    } catch (err) {
        console.error(err);
        list.innerHTML = '<div class="loading">Failed to load fixtures: ' +
            esc(err.message) + '</div>';
    }
}

function buildFixtureCard(f) {
    const time = formatKickoff(f.date);
    const statusBadge = buildStatusBadge(f.status);
    const href = '#/fixture/' + f.fixture_id;

    return '<a class="fixture-card" href="' + href + '" ' +
        'aria-label="' + esc(f.home_team) + ' vs ' + esc(f.away_team) + '">' +
        '<div class="fixture-teams">' +
        '<span class="team-home" title="' + esc(f.home_team) + '">' +
        esc(f.home_team) + '</span>' +
        '<span class="vs">vs</span>' +
        '<span class="team-away" title="' + esc(f.away_team) + '">' +
        esc(f.away_team) + '</span>' +
        '</div>' +
        '<div class="fixture-meta">' +
        '<span>🏟️ ' + esc(f.venue || 'TBA') + '</span>' +
        '<span>⏰ ' + esc(time) + ' ' + statusBadge + '</span>' +
        '</div>' +
        '<div class="fixture-hint"><span>Tap for prediction</span><span>→</span></div>' +
        '</a>';
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
        return String(dt.getHours()).padStart(2, '0') + ':' +
            String(dt.getMinutes()).padStart(2, '0');
    } catch {
        return isoDate;
    }
}

/* =========================================================
   FIXTURE PREDICTION SUB-PAGE (Betway-style)
   ========================================================= */
async function renderFixturePage(app, fixtureId) {
    const id = String(fixtureId);
    let fixture = App.fixturesCache[id];

    // If user deep-linked and cache is empty, fetch today's fixtures first
    if (!fixture) {
        app.innerHTML = '<div class="loading">Loading fixture…</div>';
        try {
            const res = await fetch('/api/today-fixtures');
            const data = await res.json();
            (data.fixtures || []).forEach(f => {
                App.fixturesCache[f.fixture_id] = f;
            });
            fixture = App.fixturesCache[id];
        } catch (e) { /* ignore */ }
    }

    if (!fixture) {
        app.innerHTML = `
            <div class="pred-page">
              <div class="back-bar">
                <a class="back-btn" href="#/"><span aria-hidden="true">←</span> Back to fixtures</a>
              </div>
              <div class="low-confidence">
                <div class="lc-title">Fixture not found</div>
                <div class="lc-text">Try refreshing the fixtures list.</div>
              </div>
            </div>`;
        return;
    }

    // Predict (cached)
    let prediction = App.predictionsCache[id];
    if (!prediction) {
        app.innerHTML = renderFixtureShell(fixture, null);
        attachBackHandler();
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
            prediction = await res.json();
            App.predictionsCache[id] = prediction;
        } catch (err) {
            console.error(err);
            app.innerHTML = renderFixtureShell(fixture, null, err.message);
            attachBackHandler();
            return;
        }
    }

    app.innerHTML = renderFixtureShell(fixture, prediction);
    attachBackHandler();
    attachRevealHandler();
}

function attachBackHandler() {
    // No-op: back uses plain <a href="#/"> so no JS needed
}

function attachRevealHandler() {
    const btn = document.querySelector('[data-reveal-events]');
    if (!btn) return;
    btn.addEventListener('click', () => {
        const block = document.querySelector('.all-events-block');
        if (!block) return;
        const isHidden = block.classList.toggle('hidden');
        btn.textContent = isHidden ? 'Show all events' : 'Hide extra events';
    });
}

/* ---------- Main shell ---------- */
function renderFixtureShell(f, p, errorMsg) {
    const leagueLabel = (f.league || 'Football') +
        (f.is_cup ? '<span class="badge cup">CUP</span>' : '');
    const time = formatKickoff(f.date);
    const statusBadge = buildStatusBadge(f.status);
    const kickoffText = time ? ('⏰ ' + time) : '';

    let bodyHtml = '';
    if (errorMsg) {
        bodyHtml = `<div class="low-confidence">
            <div class="lc-title">Prediction failed</div>
            <div class="lc-text">${esc(errorMsg)}</div>
        </div>`;
    } else if (!p) {
        bodyHtml = `<div class="loading">Calculating prediction…</div>`;
    } else if (p.status === 'insufficient_confidence') {
        bodyHtml = `<div class="low-confidence">
            <div class="lc-title">No confident prediction</div>
            <div class="lc-text">${esc(p.reason || 'Signals below threshold')}</div>
        </div>`;
    } else {
        bodyHtml = renderPredictionBody(p);
    }

    return `
        <div class="pred-page">
          <div class="back-bar">
            <a class="back-btn" href="#/"><span aria-hidden="true">←</span> Back to fixtures</a>
            <div class="breadcrumb">
              <a href="#/">Home</a> / ${esc(f.league || 'Football')} / ${esc(f.home_team)} vs ${esc(f.away_team)}
            </div>
          </div>

          <div class="match-header">
            <div class="match-header-inner">
              <div class="match-league">${leagueLabel}</div>
              <div class="match-title">
                <div class="match-team home">${esc(f.home_team)}</div>
                <div class="match-score">
                  VS
                  <span class="vs-badge">${esc(f.round || 'Fixture')}</span>
                </div>
                <div class="match-team away">${esc(f.away_team)}</div>
              </div>
              <div class="match-meta">
                <span>🏟️ ${esc(f.venue || 'TBA')}</span>
                ${kickoffText ? '<span>' + esc(kickoffText) + '</span>' : ''}
                ${statusBadge ? '<span>' + statusBadge + '</span>' : ''}
                ${f.referee ? '<span>👤 ' + esc(f.referee) + '</span>' : ''}
              </div>
            </div>
          </div>

          ${bodyHtml}
        </div>`;
}

/* ---------- Prediction body ---------- */
function renderPredictionBody(p) {
    const pr = p.probabilities || {};
    const h = (pr['Home Win'] || 0) * 100;
    const d = (pr['Draw'] || 0) * 100;
    const a = (pr['Away Win'] || 0) * 100;
    const conf = (p.confidence || 0) * 100;
    const threshold = p.event_threshold || 80;

    const homeIsTop = p.prediction === 'Home Win';
    const drawIsTop = p.prediction === 'Draw';
    const awayIsTop = p.prediction === 'Away Win';

    // Primary banner
    const primaryHtml = `
        <div class="primary-banner">
          <div>
            <div class="pb-label">Primary Prediction</div>
            <div class="pb-value">${esc(p.prediction)}</div>
          </div>
          <div class="pb-conf">
            ${conf.toFixed(1)}%
            <small>Confidence</small>
          </div>
        </div>`;

    // 1-X-2 market
    const marketHtml = `
        <div class="market-grid">
          <div class="market-card${homeIsTop ? ' is-top' : ''}">
            <div class="m-label">Home</div>
            <div class="m-value">${h.toFixed(1)}%</div>
            <div class="m-price">${esc(p.home_team || 'Home')}</div>
          </div>
          <div class="market-card${drawIsTop ? ' is-top' : ''}">
            <div class="m-label">Draw</div>
            <div class="m-value">${d.toFixed(1)}%</div>
            <div class="m-price">Match ends level</div>
          </div>
          <div class="market-card${awayIsTop ? ' is-top' : ''}">
            <div class="m-label">Away</div>
            <div class="m-value">${a.toFixed(1)}%</div>
            <div class="m-price">${esc(p.away_team || 'Away')}</div>
          </div>
        </div>`;

    // Data warning
    let dataWarning = '';
    if (p.data_age_sec && p.data_age_sec > 3600) {
        const hours = (p.data_age_sec / 3600).toFixed(1);
        dataWarning = `<div class="data-warning">⚠ Data is ${hours}h old — prediction reliability reduced</div>`;
    }

    // DNA comparison
    const dna = p.team_dna || { home: {}, away: {} };
    const dnaCol = (name, t) => {
        const style = (t.style || 'balanced').replace(/_/g, ' ');
        return `<div class="dna-side">
            <div class="dna-team" title="${esc(name)}">${esc(name)}</div>
            <div class="dna-row"><span>Formation</span><strong>${esc(t.formation || '—')}</strong></div>
            <div class="dna-row"><span>Style</span><strong>${esc(style)}</strong></div>
            <div class="dna-row"><span>Aggression</span><strong>${((t.aggression || 0) * 100).toFixed(0)}%</strong></div>
            <div class="dna-row"><span>Discipline</span><strong>${((t.discipline || 0) * 100).toFixed(0)}%</strong></div>
            <div class="dna-row"><span>Home Boost</span><strong>${((t.home_boost || 0) * 100).toFixed(0)}%</strong></div>
        </div>`;
    };
    const dnaHtml = `
        <div class="content-card">
          <div class="card-title">🧬 Tactical DNA</div>
          <div class="dna-compare">
            ${dnaCol(p.home_team, dna.home)}
            <div class="dna-vs">VS</div>
            ${dnaCol(p.away_team, dna.away)}
          </div>
        </div>`;

    // Formation notes
    let formationNotesHtml = '';
    if (p.formation_matchup && p.formation_matchup.notes && p.formation_matchup.notes.length) {
        formationNotesHtml = `
            <div class="content-card">
              <div class="card-title">🧩 Formation Matchup</div>
              <ul class="reasons-list">
                ${p.formation_matchup.notes.map(n => '<li>' + esc(n) + '</li>').join('')}
              </ul>
            </div>`;
    }

    // Probability bars
    const probBarsHtml = `
        <div class="content-card">
          <div class="card-title">📈 Outcome Probabilities</div>
          <div class="prob-bars">
            <div class="prob-row"><span class="prob-label">Home</span>
              <div class="prob-bar"><div class="prob-fill home" style="width:${h.toFixed(1)}%"></div><span class="prob-value">${h.toFixed(1)}%</span></div>
            </div>
            <div class="prob-row"><span class="prob-label">Draw</span>
              <div class="prob-bar"><div class="prob-fill draw" style="width:${d.toFixed(1)}%"></div><span class="prob-value">${d.toFixed(1)}%</span></div>
            </div>
            <div class="prob-row"><span class="prob-label">Away</span>
              <div class="prob-bar"><div class="prob-fill away" style="width:${a.toFixed(1)}%"></div><span class="prob-value">${a.toFixed(1)}%</span></div>
            </div>
          </div>
        </div>`;

    // Events
    const evRow = (e, dim) => `
        <div class="event-row">
          <span class="event-name">${esc(e.name)}</span>
          <span class="event-confidence">${Number(e.confidence).toFixed(1)}%</span>
          <div class="event-bar"><div class="event-fill${dim ? ' dim' : ''}" style="width:${Number(e.confidence)}%"></div></div>
        </div>`;
    const high = p.high_probability_events || [];
    const all = p.all_events || [];
    const eventsHtml = `
        <div class="content-card">
          <div class="card-title">⚡ High-Probability Events (≥ ${threshold}%)</div>
          <div class="events-list">
            ${high.length ? high.map(e => evRow(e, false)).join('') : `<div class="empty-events">No events pass the ${threshold}% threshold for this fixture</div>`}
          </div>
          ${all.length > high.length ? `
            <button class="reveal-btn" data-reveal-events type="button">Show all events</button>
            <div class="all-events-block hidden">
              <div class="events-list">${all.map(e => evRow(e, true)).join('')}</div>
            </div>` : ''}
        </div>`;

    // Score probabilities
    const scores = (p.score_probabilities || []).slice(0, 5);
    const scoresHtml = `
        <div class="content-card">
          <div class="card-title">📊 Top Score Probabilities</div>
          <div class="scores-list">
            ${scores.map(s => `
              <div class="score-row">
                <span class="score-badge">${esc(s.score)}</span>
                <div class="score-bar"><div class="score-fill" style="width:${(s.probability * 100).toFixed(1)}%"></div></div>
                <span class="score-pct">${(s.probability * 100).toFixed(1)}%</span>
              </div>`).join('')}
          </div>
        </div>`;

    // Reasons
    const reasons = p.reasons || [];
    const reasonsHtml = reasons.length ? `
        <div class="content-card">
          <div class="card-title">🧠 Why This Prediction</div>
          <ul class="reasons-list">
            ${reasons.map(r => '<li>' + esc(r) + '</li>').join('')}
          </ul>
        </div>` : '';

    // Attributions
    const attrs = p.attributions || [];
    const attrsHtml = attrs.length ? `
        <div class="content-card">
          <div class="card-title">🔍 Feature Impact (SHAP on XGB)</div>
          <div class="attributions">
            ${attrs.map(at => {
                const cls = at.impact >= 0 ? 'pos' : 'neg';
                const pct = Math.abs(at.impact * 100).toFixed(1);
                return `<div class="attribution-row">
                    <span class="attr-label">${esc(at.label)}</span>
                    <div class="attr-bar"><div class="attr-fill ${cls}" style="width:${pct}%"></div></div>
                    <span class="attr-value ${cls}">${at.impact >= 0 ? '+' : '-'}${pct}%</span>
                  </div>`;
            }).join('')}
          </div>
        </div>` : '';

    return `
        ${primaryHtml}
        ${marketHtml}
        ${dataWarning}
        <div class="detail-grid">
          ${dnaHtml}
          ${probBarsHtml}
        </div>
        ${formationNotesHtml}
        ${eventsHtml}
        ${scoresHtml}
        ${reasonsHtml}
        ${attrsHtml}
    `;
}

/* =========================================================
   HELPERS
   ========================================================= */
function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    }[c]));
}