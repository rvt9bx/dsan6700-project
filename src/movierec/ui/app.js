/* Overlap: front end for the group movie recommender.
 * Plain JavaScript, no framework. Served by FastAPI at GET /.
 *
 * Sections:
 *   1. Config + state
 *   2. Screen switching
 *   3. Setup (mode, group size, names)
 *   4. Turns (hand-off, input, live pin, seal)
 *   5. API calls (async job pattern) + mock mode
 *   6. Results
 *   7. Event wiring
 */

// ---------- 1. CONFIG + STATE ----------

// Flip to false once the backend is running. Mock mode fakes the API.
const USE_MOCK = true;
const POLL_MS = 1000;          // how often to check job status
const POLL_TIMEOUT_MS = 60000; // give up after a minute

const COLORS = ['#E2553A', '#2C7DA0', '#C48A0E', '#8E4D9E', '#2F8F6B', '#C2457A'];
const PLACEHOLDERS = [
  "Something cozy with a twist I won't see coming",
  "A heist that's funny, nothing too long",
  "Dark and tense, keep me on the edge of my seat",
  "Feel-good, like a warm blanket",
  "Big loud action, pure fun",
  "Smart sci-fi we'll argue about after",
];

function freshState() {
  return {
    mode: 'group',            // 'solo' | 'group'
    size: 3,                  // number of people (2-6) in group mode
    names: ['', '', '', '', '', ''],
    texts: [],                // texts[i] = person i's description
    turn: 0,                  // whose turn it is
    jobIds: [],               // one job per person until the API accepts groups
    results: null,            // response from /results
    revealed: -1,             // which person's pick is open on results
  };
}
let state = freshState();

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

function people() {
  const n = state.mode === 'solo' ? 1 : state.size;
  return Array.from({ length: n }, (_, i) => ({
    i,
    name: state.names[i].trim() || (state.mode === 'solo' ? 'You' : `Person ${i + 1}`),
    color: COLORS[i],
    text: state.texts[i] || '',
  }));
}

// ---------- 2. SCREEN SWITCHING ----------

function show(screen) {
  $$('.screen').forEach((el) => { el.hidden = el.id !== `screen-${screen}`; });
  window.scrollTo(0, 0);
}

// ---------- 3. SETUP ----------

function renderSetup() {
  $$('.mode').forEach((b) => b.setAttribute('aria-pressed', b.dataset.mode === state.mode));
  $('#group-setup').hidden = state.mode === 'solo';
  $('#size-label').textContent = state.size;
  renderNames();
}

function renderNames() {
  const list = $('#name-list');
  list.innerHTML = '';
  people().forEach((p) => {
    const row = document.createElement('div');
    row.className = 'name-row';
    row.innerHTML = `
      <span class="dot" style="background:${p.color}"></span>
      <input aria-label="Person ${p.i + 1}" placeholder="Person ${p.i + 1}">`;
    const input = row.querySelector('input');
    input.value = state.names[p.i];
    input.addEventListener('input', (e) => { state.names[p.i] = e.target.value; });
    list.appendChild(row);
  });
}

// ---------- 4. TURNS ----------

function renderEnvelopes() {
  // TODO: style .env.sealed / .env.current / .env.waiting / .env.open in styles.css
  const html = people().map((p) => {
    const status = p.i < state.turn ? 'sealed' : p.i === state.turn ? 'current' : 'waiting';
    return `<div class="env-wrap">
      <div class="env ${status}" style="--c:${p.color}"></div>
      <span>${escapeHtml(p.name)}</span></div>`;
  }).join('');
  $$('.envelopes').forEach((el) => { el.innerHTML = html; });
}

function startTurn() {
  if (state.mode === 'solo') return showInput();
  renderEnvelopes();
  const cur = people()[state.turn];
  $$('.js-cur-name').forEach((el) => { el.textContent = cur.name; });
  $('#handoff-sub').textContent = state.turn === 0
    ? 'Everyone else, look away. Picks stay sealed until the end.'
    : `${state.turn} sealed so far. Nobody sees a pick until everyone has written one.`;
  show('handoff');
}

function showInput() {
  const all = people();
  const cur = all[state.turn];
  const solo = state.mode === 'solo';
  $('#input-title').textContent = solo ? 'Your pick' : `${cur.name}'s turn`;
  $('#turn-label').textContent = solo ? '' : `${state.turn + 1} of ${all.length}`;
  $('#pick-text').value = cur.text;
  $('#pick-text').placeholder = PLACEHOLDERS[state.turn % PLACEHOLDERS.length];
  $('#pick-error').hidden = true;
  $('#seal-btn').textContent = solo ? 'Find my movie' : 'Seal my pick';
  $('#next-hint').textContent = solo ? ''
    : state.turn === all.length - 1 ? 'Last pick. Then everyone opens them together.'
    : `Then hand the phone to ${all[state.turn + 1].name}`;
  renderEnvelopes();
  movePin(cur.text, cur.color);
  show('input');
  $('#pick-text').focus();
}

// Live pin. Placeholder logic: keyword counts.
// TODO: replace with x, y from the backend (similarity to anchor phrases).
const WORDS = {
  cozy: ['cozy', 'cosy', 'warm', 'sweet', 'calm', 'comfort', 'feel-good', 'feel good', 'romance', 'family', 'chill'],
  intense: ['intense', 'tense', 'edge', 'action', 'thriller', 'scary', 'horror', 'loud', 'heist', 'twist', 'suspense'],
  light: ['funny', 'comedy', 'light', 'happy', 'fun', 'silly', 'laugh', 'upbeat', 'musical'],
  dark: ['dark', 'sad', 'grim', 'crime', 'murder', 'serious', 'bleak', 'mystery', 'gritty'],
};
function placeFromText(text) {
  const t = text.toLowerCase();
  const count = (list) => list.filter((w) => t.includes(w)).length;
  const clamp = (v) => Math.max(14, Math.min(86, v));
  return {
    x: clamp(50 + 13 * (count(WORDS.intense) - count(WORDS.cozy))),
    y: clamp(50 + 13 * (count(WORDS.dark) - count(WORDS.light))),
  };
}
function movePin(text, color) {
  const { x, y } = placeFromText(text);
  for (const el of [$('#my-pin'), $('#my-halo')]) {
    el.style.left = `${x}%`;
    el.style.top = `${y}%`;
    el.style.setProperty('--c', color);
  }
}

function seal() {
  const text = $('#pick-text').value.trim();
  if (!text) { $('#pick-error').hidden = false; return; }
  state.texts[state.turn] = text;

  if (state.mode === 'solo') return submitPicks();

  // Sealed screen, then on to the next person (or submit if last).
  const cur = people()[state.turn];
  $('#big-envelope').style.setProperty('--c', cur.color);
  $('#sealed-sub').textContent = `${cur.name}'s pick is in. ${state.turn + 1} of ${state.size} sealed.`;
  state.turn += 1;
  renderEnvelopes();
  show('sealed');
  setTimeout(() => (state.turn >= state.size ? submitPicks() : startTurn()), 1300);
}

// ---------- 5. API (async job pattern) ----------
// Matches the fastapi_skeleton branch (src/movierec/api/main.py + schemas.py):
//   POST /recommend              body {query_text, top_k}         -> {job_id, status}
//   GET  /recommend/{id}/status  -> {job_id, status: "pending"|"running"|"completed"|"failed", error}
//   GET  /recommend/{id}/results -> {results: [{id, title, score, overview}]}
//
// The API takes ONE query per job, so for now a group sends one job per person
// and combineResults() merges them here in the browser.
// TEMP: once the API accepts a list of members, send one job and let the
// backend do the aggregation (recommend.py), then delete combineResults().

const TOP_K = 5;

async function submitPicks() {
  setLoadStep(0);
  $('#load-error').hidden = true;
  show('loading');
  try {
    const members = people();
    const jobIds = await Promise.all(members.map((p) =>
      api('POST', '/recommend', { query_text: p.text, top_k: TOP_K }).then((r) => r.job_id)));
    state.jobIds = jobIds;
    setLoadStep(1);
    await Promise.all(jobIds.map(waitForJob));
    setLoadStep(2);
    const perPerson = await Promise.all(jobIds.map((id) => api('GET', `/recommend/${id}/results`)));
    state.results = combineResults(perPerson, members);
    if (!state.results) throw new Error('No movies came back');
    renderResults();
    show('results');
  } catch (err) {
    console.error(err);
    $('#load-error').hidden = false;
  }
}

async function waitForJob(id) {
  const started = Date.now();
  while (Date.now() - started < POLL_TIMEOUT_MS) {
    const { status, error } = await api('GET', `/recommend/${id}/status`);
    if (status === 'completed') return;
    if (status === 'failed') throw new Error(error || 'Job failed');
    await sleep(POLL_MS);
  }
  throw new Error('Timed out waiting for results');
}

// Merge each person's top-k list into one group ranking.
// Group score = average of everyone's score; a movie missing from
// someone's list counts as 0 for them, so nobody gets ignored.
function combineResults(perPerson, members) {
  const byId = new Map();
  perPerson.forEach((res, i) => {
    (res.results || []).forEach((m) => {
      if (!byId.has(m.id)) byId.set(m.id, { movie: m, scores: members.map(() => null) });
      byId.get(m.id).scores[i] = m.score;
    });
  });
  const ranked = [...byId.values()]
    .map((c) => ({ ...c, group: avg(c.scores.map((s) => s ?? 0)) }))
    .sort((a, b) => b.group - a.group);
  if (!ranked.length) return null;
  const [top, ...rest] = ranked;
  return {
    movie: top.movie,
    alternates: rest.slice(0, 2).map((c) => ({ title: c.movie.title, group_fit: c.group })),
    // x, y still come from the front end until the API sends them
    members: members.map((p, i) => ({ name: p.name, fit: top.scores[i], ...placeFromText(p.text) })),
  };
}

async function api(method, path, body) {
  if (USE_MOCK) return mockApi(method, path, body);
  const res = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${method} ${path} -> ${res.status}`);
  return res.json();
}

// Mock backend that returns exactly what Erin's endpoints return,
// so flipping USE_MOCK to false needs no other change.
const mockJobs = {};
const MOCK_MOVIES = [
  { id: 546554, title: 'Knives Out', overview: "A detective untangles a wealthy family's alibis after the patriarch's 85th birthday ends in his death." },
  { id: 661374, title: 'Glass Onion', overview: 'A detective joins a tech billionaire and his friends for a murder-mystery weekend on a private Greek island.' },
  { id: 290250, title: 'The Nice Guys', overview: 'A mismatched pair of private eyes investigate a missing girl in 1970s Los Angeles.' },
  { id: 346648, title: 'Paddington 2', overview: 'Paddington takes on odd jobs to buy a gift for his aunt, until the gift is stolen.' },
  { id: 146233, title: 'Prisoners', overview: 'When two girls go missing, a desperate father takes matters into his own hands.' },
];
async function mockApi(method, path, body) {
  await sleep(300);
  if (method === 'POST') {
    const id = `mock-${Object.keys(mockJobs).length + 1}`;
    mockJobs[id] = { polls: 0, query: body.query_text };
    return { job_id: id, status: 'pending' };
  }
  const id = path.split('/')[2];
  const job = mockJobs[id];
  if (path.endsWith('/status')) {
    job.polls += 1;
    return { job_id: id, status: job.polls >= 2 ? 'completed' : 'running', error: null };
  }
  // Different queries get slightly different rankings so group merging is visible.
  const seed = job.query.length;
  return {
    results: MOCK_MOVIES.map((m, i) => ({ ...m, score: Math.max(0.5, 0.95 - ((i + seed) % 5) * 0.06) }))
      .sort((a, b) => b.score - a.score)
      .slice(0, body ? body.top_k : TOP_K),
  };
}

function setLoadStep(k) {
  $$('#load-steps li').forEach((li) => {
    const n = Number(li.dataset.step);
    li.className = n < k ? 'done' : n === k ? 'active' : 'waiting';
  });
}

// ---------- 6. RESULTS ----------

function renderResults() {
  const { movie, alternates, members } = state.results;
  const all = people();

  // Map: one area + pin per person, poster at the average position.
  const cx = avg(members.map((m) => m.x));
  const cy = avg(members.map((m) => m.y));
  const poster = movie.poster_path
    ? `<img class="poster" src="https://image.tmdb.org/t/p/w342${movie.poster_path}" alt="${escapeHtml(movie.title)} poster" style="left:${cx}%;top:${cy}%">`
    : `<div class="poster placeholder" style="left:${cx}%;top:${cy}%">${escapeHtml(movie.title)}</div>`;
  $('#results-map').innerHTML = `
    <span class="axis x-left">Cozy</span><span class="axis x-right">Intense</span>
    ${members.map((m, i) => `<div class="area" style="left:${m.x}%;top:${m.y}%;--c:${COLORS[i]}"></div>`).join('')}
    ${members.map((m, i) => `<div class="pin" style="left:${m.x}%;top:${m.y}%;--c:${COLORS[i]}"></div>`).join('')}
    ${poster}`;

  $('#results-title').textContent = state.mode === 'solo' ? 'Your match' : 'Your overlap';
  $('#movie-title').textContent = movie.title;
  // The API only sends id, title, score, overview today; the rest shows up when it's added.
  const meta = [
    movie.year,
    movie.runtime_min && formatRuntime(movie.runtime_min),
    movie.genres && movie.genres.join(', '),
    movie.providers && `on ${movie.providers.join(', ')}`,
  ].filter(Boolean);
  $('#movie-meta').textContent = meta.join(' · ');
  $('#movie-meta').hidden = meta.length === 0;
  $('#movie-overview').textContent = movie.overview || '';
  $('#watch-btn').textContent = `We're watching ${movie.title}`;

  renderFitBars(members, all);

  const lowest = members.reduce((a, b) => ((b.fit ?? 0) < (a.fit ?? 0) ? b : a));
  $('#fair-line').textContent = state.mode === 'solo'
    ? 'Tap your bar to see what you wrote.'
    : `Lowest fit: ${lowest.name} at ${pct(lowest.fit)}. Tap anyone to open their sealed pick.`;

  $('#alternates').innerHTML = alternates.length
    ? `<p class="muted">Next closest: ${alternates.map((a) => escapeHtml(a.title)).join(', ')}</p>` : '';
}

function renderFitBars(members, all) {
  const rows = members
    .map((m, i) => ({ ...m, i, color: COLORS[i], text: all[i] ? all[i].text : '' }))
    .sort((a, b) => (b.fit ?? 0) - (a.fit ?? 0));
  $('#fit-bars').innerHTML = rows.map((r) => `
    <button class="fit-row" data-person="${r.i}" aria-expanded="${state.revealed === r.i}">
      <span>${escapeHtml(r.name)}</span>
      <span class="bar"><span style="width:${pct(r.fit ?? 0)};background:${r.color}"></span></span>
      <span title="${r.fit == null ? 'Not in their top picks' : ''}">${r.fit == null ? '—' : pct(r.fit)}</span>
    </button>
    ${state.revealed === r.i ? `<p class="note" style="--c:${r.color}">"${escapeHtml(r.text)}"</p>` : ''}`).join('');
}

// ---------- 7. EVENT WIRING ----------

document.addEventListener('click', (e) => {
  const modeBtn = e.target.closest('[data-mode]');
  if (modeBtn) { state.mode = modeBtn.dataset.mode; renderSetup(); return; }

  const fitRow = e.target.closest('.fit-row');
  if (fitRow) {
    const i = Number(fitRow.dataset.person);
    state.revealed = state.revealed === i ? -1 : i;
    renderFitBars(state.results.members, people());
    return;
  }

  const action = e.target.closest('[data-action]')?.dataset.action;
  switch (action) {
    case 'go-start': renderSetup(); show('start'); break;
    case 'size-down': state.size = Math.max(2, state.size - 1); renderSetup(); break;
    case 'size-up': state.size = Math.min(6, state.size + 1); renderSetup(); break;
    case 'begin': state.texts = []; state.turn = 0; startTurn(); break;
    case 'ready': showInput(); break;
    case 'seal': seal(); break;
    case 'retry': submitPicks(); break;
    case 'edit': state.turn = 0; state.revealed = -1; startTurn(); break;
    case 'watch': logWatch(); break;
    case 'restart': state = freshState(); show('intro'); break;
  }
});

$('#pick-text').addEventListener('input', (e) => {
  const cur = people()[state.turn];
  movePin(e.target.value, cur.color);
  $('#pick-error').hidden = true;
});

// TODO: agree on an endpoint with the team for click tracking (monitoring lane).
function logWatch() {
  if (USE_MOCK) { console.log('watch clicked', state.results.movie.title); return; }
  fetch('/events/watch', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ job_ids: state.jobIds, movie_id: state.results.movie.id }),
  }).catch(() => {});
}

// ---------- helpers ----------
function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }
function avg(xs) { return xs.reduce((a, b) => a + b, 0) / xs.length; }
function pct(f) { return `${Math.round(f * 100)}%`; }
function formatRuntime(min) { return `${Math.floor(min / 60)} hr ${min % 60} min`; }
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

show('intro');
