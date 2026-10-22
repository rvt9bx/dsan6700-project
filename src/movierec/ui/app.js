/* Eenie Meenie Movies: front end for the group movie recommender.
 * Plain JavaScript, no framework. FastAPI serves this file at /static/app.js
 * and the page (index.html) at GET /.
 *
 * Sections:
 *   1. Config + state
 *   2. Screen switching + top bar
 *   3. Setup (mode, group size, names)
 *   4. Turns (hand-off, input, live pin, seal)
 *   5. API calls (async job pattern) + mock mode
 *   6. Results
 *   7. Event wiring
 */

// ---------- 1. CONFIG + STATE ----------

// true = fake the API inside this file (no backend needed).
// false = send real requests to the FastAPI server.
const USE_MOCK = true;
const POLL_MS = 1000;          // how often to check job status
const POLL_TIMEOUT_MS = 60000; // give up after a minute

// The mood map (Cozy/Intense, Light/Dark) is paused until the team decides on it.
// true = show the map; false = show idea suggestions and a plain poster instead.
const SHOW_MOOD_MAP = false;

// One color per person, in order (person 1 = first color, and so on).
const COLORS = ['#E2553A', '#2C7DA0', '#C48A0E', '#8E4D9E', '#2F8F6B', '#C2457A'];
// Example text shown in the empty text box, a different one for each turn.
const PLACEHOLDERS = [
  "Something cozy with a twist I won't see coming",
  "A heist that's funny, nothing too long",
  "Dark and tense, keep me on the edge of my seat",
  "Feel-good, like a warm blanket",
  "Big loud action, pure fun",
  "Smart sci-fi we'll argue about after",
];
// Colors for placeholder posters: [top of gradient, bottom of gradient, title color].
// Each movie always gets the same one (picked from its title).
const POSTER_TONES = [
  ['#44624D', '#121D16', '#F2D27A'],
  ['#7BA3C9', '#1B2C46', '#FFFFFF'],
  ['#E0A060', '#5C2A10', '#FFF1DC'],
  ['#D7695A', '#6E1F22', '#FFE3DA'],
  ['#9C6BB0', '#3A1D4A', '#F6E7FF'],
  ['#4D9C9A', '#143A3C', '#E3FFF9'],
];

/**
 * Builds a brand-new, empty app state. Used when the page first loads and
 * when someone taps "New movie night".
 * @returns {object} everything the app needs to remember between screens
 */
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

// Shortcuts: $('#id') finds one element on the page, $$('.class') finds all matches.
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

/**
 * Lists the people taking part, with a display name, avatar letter, color and
 * what they wrote. A blank name becomes "You" (solo) or "Person N" (group),
 * and their avatar shows "Y" or the number N.
 * @returns {{i: number, name: string, initial: string, color: string, text: string}[]}
 */
function people() {
  const n = state.mode === 'solo' ? 1 : state.size;
  return Array.from({ length: n }, (_, i) => {
    const typed = state.names[i].trim();
    const fallback = state.mode === 'solo' ? 'You' : `Person ${i + 1}`;
    return {
      i,
      name: typed || fallback,
      initial: typed ? typed[0].toUpperCase() : (state.mode === 'solo' ? 'Y' : String(i + 1)),
      color: COLORS[i],
      text: state.texts[i] || '',
    };
  });
}

// ---------- 2. SCREEN SWITCHING + TOP BAR ----------

/**
 * Shows one screen and hides all the others, updates the top bar, then
 * scrolls to the top.
 * @param {string} screen name of the screen, e.g. 'intro' shows #screen-intro
 */
function show(screen) {
  $$('.screen').forEach((el) => { el.hidden = el.id !== `screen-${screen}`; });
  renderNav(screen);
  window.scrollTo(0, 0);
}

/**
 * Fills the right side of the top bar. On the intro it shows two short notes;
 * everywhere else it shows Setup / Picks / Results with the current step
 * highlighted (on phones only the current step shows).
 * @param {string} screen the screen being shown
 */
function renderNav(screen) {
  if (screen === 'intro') {
    $('#nav').innerHTML = '<span class="pill">No sign-up</span><span class="pill">Works solo too</span>';
    return;
  }
  const step = screen === 'start' ? 0 : (screen === 'loading' || screen === 'results') ? 2 : 1;
  const picks = state.mode === 'solo' ? 'Your pick' : `Picks · ${Math.min(state.turn + 1, state.size)} of ${state.size}`;
  const labels = ['Setup', step === 1 ? picks : 'Picks', 'Results'];
  $('#nav').innerHTML = `<div class="steps-nav">${labels.map((label, k) => {
    const cls = k < step ? 'done' : k === step ? 'on' : '';
    return `<span class="${cls}"${k === step ? ' aria-current="step"' : ''}>${k < step ? '✓ ' : ''}${label}</span>`;
  }).join('')}</div>`;
}

// ---------- 3. SETUP ----------

/**
 * Draws the "Who's watching?" screen: highlights the chosen mode, hides the
 * group options in solo mode, and updates the people count and name boxes.
 */
function renderSetup() {
  $$('.mode').forEach((b) => b.setAttribute('aria-pressed', b.dataset.mode === state.mode));
  $('#group-setup').hidden = state.mode === 'solo';
  $('#size-label').textContent = state.size;
  renderNames();
}

/**
 * Draws one name box (with a numbered colored dot) per person. Typing in a box
 * saves the name into state right away.
 */
function renderNames() {
  const list = $('#name-list');
  list.innerHTML = '';
  people().forEach((p) => {
    const row = document.createElement('div');
    row.className = 'name-row';
    row.innerHTML = `
      <span class="dot" style="background:${p.color}" aria-hidden="true">${p.i + 1}</span>
      <input aria-label="Person ${p.i + 1}" placeholder="Person ${p.i + 1}">`;
    const input = row.querySelector('input');
    input.value = state.names[p.i];
    input.addEventListener('input', (e) => { state.names[p.i] = e.target.value; });
    list.appendChild(row);
  });
}

// ---------- 4. TURNS ----------

/**
 * Draws everyone's progress in two places:
 *   - the row of envelopes (filled = sealed, outlined = writing now, dashed = waiting)
 *   - the "Picks so far" list on wide screens (avatar, name, envelope, status)
 */
function renderEnvelopes() {
  const all = people();
  const statusOf = (p) => (p.i < state.turn ? 'sealed' : p.i === state.turn ? 'current' : 'waiting');
  const envHtml = all.map((p) => `<div class="env-wrap">
      <div class="env ${statusOf(p)}" style="--c:${p.color}"></div>
      <span>${escapeHtml(p.name)}</span></div>`).join('');
  $$('.envelopes').forEach((el) => { el.innerHTML = envHtml; });

  const label = { sealed: 'Sealed', current: 'Writing', waiting: 'Waiting' };
  const listHtml = all.map((p) => {
    const s = statusOf(p);
    return `<div class="who-row">${avatar(p)}<span class="grow">${escapeHtml(p.name)}</span>
      <span class="env ${s}" style="--c:${p.color}"></span><span class="status st-${s}">${label[s]}</span></div>`;
  }).join('');
  $$('.who-list').forEach((el) => { el.innerHTML = listHtml; });
}

/**
 * Starts the current person's turn. In group mode it shows the "Pass it to ..."
 * screen first; in solo mode it goes straight to the input screen.
 */
function startTurn() {
  if (state.mode === 'solo') return showInput();
  renderEnvelopes();
  const cur = people()[state.turn];
  $('#handoff-av').innerHTML = avatar(cur, 'xl');
  $$('.js-cur-name').forEach((el) => { el.textContent = cur.name; });
  $('#handoff-sub').textContent = state.turn === 0
    ? 'Everyone else, look away. Picks stay sealed until the end.'
    : `${state.turn} sealed so far. Nobody sees a pick until everyone has written one.`;
  show('handoff');
}

/**
 * Shows the input screen for the current person: their avatar and title
 * ("Person 2's turn"), the text box, idea suggestions (or the mood map pin),
 * everyone's progress, and a hint about who goes next.
 */
function showInput() {
  const all = people();
  const cur = all[state.turn];
  const solo = state.mode === 'solo';
  $('#screen-input').style.setProperty('--c', cur.color);
  $('#input-av').innerHTML = avatar(cur, 'lg');
  $('#input-title').textContent = solo ? 'Your pick' : `${cur.name}'s turn`;
  $('#input-sub').textContent = solo ? 'Describe the movie you want tonight.' : 'Everyone else, look away.';
  $('#pick-text').value = cur.text;
  $('#pick-text').placeholder = PLACEHOLDERS[state.turn % PLACEHOLDERS.length];
  $('#pick-error').hidden = true;
  $('#seal-btn').textContent = solo ? 'Find my movie' : 'Seal my pick';
  $('#next-hint').textContent = solo ? ''
    : state.turn === all.length - 1 ? 'Last pick. Then everyone opens them together.'
    : `Then pass it to ${all[state.turn + 1].name}`;
  $('#input-side').hidden = solo;
  $('#input-envs').hidden = solo;
  renderEnvelopes();
  $('#input-map').hidden = !SHOW_MOOD_MAP;
  $('#ideas').hidden = SHOW_MOOD_MAP;
  if (SHOW_MOOD_MAP) movePin(cur.text, cur.color);
  else renderIdeas();
  show('input');
  $('#pick-text').focus();
}

/**
 * Shows three example descriptions near the text box. Tapping one fills the
 * box with it. Each turn gets a different three (and not the one already
 * shown as the text box's placeholder). Used while the mood map is paused.
 */
function renderIdeas() {
  const ideas = [1, 2, 3].map((k) => (state.turn + k) % PLACEHOLDERS.length);
  $('#ideas').innerHTML = `<span class="muted">Need an idea?</span>
    ${ideas.map((n) => `<button class="idea" data-idea="${n}"><b aria-hidden="true">+</b>${escapeHtml(PLACEHOLDERS[n])}</button>`).join('')}`;
}

// Live pin. Placeholder logic: keyword counts.
// TODO: replace with x, y from the backend (similarity to anchor phrases).
const WORDS = {
  cozy: ['cozy', 'cosy', 'warm', 'sweet', 'calm', 'comfort', 'feel-good', 'feel good', 'romance', 'family', 'chill'],
  intense: ['intense', 'tense', 'edge', 'action', 'thriller', 'scary', 'horror', 'loud', 'heist', 'twist', 'suspense'],
  light: ['funny', 'comedy', 'light', 'happy', 'fun', 'silly', 'laugh', 'upbeat', 'musical'],
  dark: ['dark', 'sad', 'grim', 'crime', 'murder', 'serious', 'bleak', 'mystery', 'gritty'],
};

/**
 * Guesses where a description sits on the mood map by counting mood words.
 * More "intense" words push the pin right, more "cozy" words push it left;
 * "dark" pushes it down and "light" pushes it up.
 * @param {string} text what the person typed
 * @returns {{x: number, y: number}} position in percent (kept between 14 and 86
 *   so the pin never touches the edge)
 */
function placeFromText(text) {
  const t = text.toLowerCase();
  const count = (list) => list.filter((w) => t.includes(w)).length;
  const clamp = (v) => Math.max(14, Math.min(86, v));
  return {
    x: clamp(50 + 13 * (count(WORDS.intense) - count(WORDS.cozy))),
    y: clamp(50 + 13 * (count(WORDS.dark) - count(WORDS.light))),
  };
}

/**
 * Moves the person's pin (and the soft circle around it) on the input map to
 * match what they have typed so far.
 * @param {string} text what the person typed
 * @param {string} color the person's color
 */
function movePin(text, color) {
  const { x, y } = placeFromText(text);
  for (const el of [$('#my-pin'), $('#my-halo')]) {
    el.style.left = `${x}%`;
    el.style.top = `${y}%`;
    el.style.setProperty('--c', color);
  }
}

/**
 * Runs when someone taps "Seal my pick". Saves their text (or shows an error if
 * it is empty), shows the "Sealed" screen for a moment, then moves on to the
 * next person, or sends everyone's picks to the API after the last person.
 */
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
// Matches the FastAPI endpoints in src/movierec/api/main.py (schemas in schemas.py):
//   POST /recommend              body {query_text, top_k}         -> {job_id, status}
//   GET  /recommend/{id}/status  -> {job_id, status: "pending"|"running"|"completed"|"failed", error}
//   GET  /recommend/{id}/results -> {results: [{id, title, score, overview}]}
//
// The API takes ONE query per job, so for now a group sends one job per person
// and combineResults() merges them here in the browser.
// TEMP: once the API accepts a list of members, send one job and let the
// backend do the aggregation (recommend.py), then delete combineResults().

const TOP_K = 5;

/**
 * Sends everyone's picks to the API and shows the results. Steps:
 *   1. POST /recommend once per person, collecting a job ID for each
 *   2. wait until every job reports "completed"
 *   3. GET each job's results and merge them into one group pick
 * The loading screen's checklist advances at each step. If anything fails,
 * it shows an error with a "Try again" button.
 */
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

/**
 * Asks the API "is this job done yet?" every POLL_MS until it is.
 * @param {string} id the job ID returned by POST /recommend
 * @throws if the job fails or takes longer than POLL_TIMEOUT_MS
 */
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

/**
 * Merges each person's list of movies into one group ranking.
 * A movie's group score is the average of everyone's score for it; if a movie
 * is missing from someone's list it counts as 0 for them, so nobody is ignored.
 * @param {object[]} perPerson one /results response per person, in order
 * @param {object[]} members the people, from people()
 * @returns {object|null} {movie, group, alternates, members} for the results
 *   screen, or null if no movies came back at all
 */
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
    group: top.group,
    alternates: rest.slice(0, 2).map((c) => ({
      title: c.movie.title, year: c.movie.year, poster_path: c.movie.poster_path, group_fit: c.group,
    })),
    // x, y still come from the front end until the API sends them
    members: members.map((p, i) => ({ name: p.name, fit: top.scores[i], ...placeFromText(p.text) })),
  };
}

/**
 * The one place the front end talks to the FastAPI server. Every request goes
 * through here. When USE_MOCK is true it answers with fake data instead.
 * @param {string} method 'GET' or 'POST'
 * @param {string} path the endpoint, e.g. '/recommend'
 * @param {object} [body] data to send as JSON (POST only)
 * @returns {Promise<object>} the server's JSON reply
 * @throws if the server replies with an error code (404, 500, ...)
 */
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

// Mock backend that returns exactly what the FastAPI endpoints return,
// so flipping USE_MOCK to false needs no other change.
const mockJobs = {};
const MOCK_MOVIES = [
  { id: 546554, title: 'Knives Out', overview: "A detective untangles a wealthy family's alibis after the patriarch's 85th birthday ends in his death." },
  { id: 661374, title: 'Glass Onion', overview: 'A detective joins a tech billionaire and his friends for a murder-mystery weekend on a private Greek island.' },
  { id: 290250, title: 'The Nice Guys', overview: 'A mismatched pair of private eyes investigate a missing girl in 1970s Los Angeles.' },
  { id: 346648, title: 'Paddington 2', overview: 'Paddington takes on odd jobs to buy a gift for his aunt, until the gift is stolen.' },
  { id: 146233, title: 'Prisoners', overview: 'When two girls go missing, a desperate father takes matters into his own hands.' },
];

/**
 * Pretends to be the FastAPI server so the app works with no backend.
 * Waits 0.3 s like a real network trip, then:
 *   POST /recommend        -> makes a fake job and returns its ID
 *   GET  .../status        -> "running" the first time, "completed" after that
 *   GET  .../results       -> the five MOCK_MOVIES with made-up scores
 * @param {string} method 'GET' or 'POST'
 * @param {string} path the endpoint
 * @param {object} [body] data sent with a POST
 * @returns {Promise<object>} the same shape of reply the real server sends
 */
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

/**
 * Updates the loading screen checklist: steps before k get a check mark
 * (done), step k spins (working on it), steps after k stay dashed (waiting).
 * @param {number} k 0 = picks received, 1 = searching, 2 = balancing
 */
function setLoadStep(k) {
  $$('#load-steps li').forEach((li) => {
    const n = Number(li.dataset.step);
    li.className = n < k ? 'done' : n === k ? 'active' : 'waiting';
  });
}

// ---------- 6. RESULTS ----------

/**
 * Draws the results screen from state.results: the poster stack (the pick in
 * front, runners-up behind it) or the mood map, the movie's title, details and
 * summary, the group-fit ring, everyone's fit bars, and the "also close" movies.
 */
function renderResults() {
  const { movie, group, alternates, members } = state.results;
  const all = people();
  const solo = state.mode === 'solo';

  // Map: one area + pin per person, poster at the average position.
  const cx = avg(members.map((m) => m.x));
  const cy = avg(members.map((m) => m.y));
  $('#results-map').innerHTML = `
    <span class="axis x-left">Cozy</span><span class="axis x-right">Intense</span>
    <span class="axis y-top">Light</span><span class="axis y-bottom">Dark</span>
    ${members.map((m, i) => `<div class="area" style="left:${m.x}%;top:${m.y}%;--c:${COLORS[i]}"></div>`).join('')}
    ${members.map((m, i) => `<div class="pin" style="left:${m.x}%;top:${m.y}%;--c:${COLORS[i]}"></div>`).join('')}
    <div style="position:absolute;left:${cx}%;top:${cy}%">${posterHtml(movie)}</div>`;
  $('#results-map').hidden = !SHOW_MOOD_MAP;

  // While the map is paused: the pick in front, up to two runners-up fanned out behind.
  $('#results-poster').hidden = SHOW_MOOD_MAP;
  $('#results-poster').innerHTML = `
    ${alternates.map((a, k) => posterHtml(a, `back b${k + 1}`)).join('')}
    <span class="ribbon">${solo ? 'Your pick' : "Tonight's pick"}</span>
    ${posterHtml(movie, 'front')}`;

  $('#results-title').textContent = solo ? 'Your match' : 'Your overlap';
  $('#movie-title').textContent = movie.title;
  // The API only sends id, title, score, overview today; the rest shows up when it's added.
  const meta = [
    movie.year,
    movie.runtime_min && formatRuntime(movie.runtime_min),
    ...(movie.genres || []),
    movie.providers && `on ${movie.providers.join(', ')}`,
  ].filter(Boolean);
  $('#movie-meta').innerHTML = meta.map((m) => `<span class="tag">${escapeHtml(m)}</span>`).join('');
  $('#movie-meta').hidden = meta.length === 0;
  $('#movie-overview').textContent = movie.overview || '';
  $('#movie-overview').hidden = !movie.overview;
  $('#watch-btn').textContent = `We're watching ${movie.title}`;

  $('#score-ring').innerHTML = ringSvg(group, solo ? 'match' : 'group fit');
  $('#score-label').textContent = solo ? 'Match' : 'Group fit';
  const lowest = members.reduce((a, b) => ((b.fit ?? 0) < (a.fit ?? 0) ? b : a));
  $('#fair-line').textContent = solo
    ? 'Tap your bar to see what you wrote.'
    : lowest.fit == null
      ? `This wasn't in ${lowest.name}'s top picks. Tap a name to open their sealed pick.`
      : `Everyone is at ${pct(lowest.fit)} or higher. Tap a name to open their sealed pick.`;

  renderFitBars(members, all, true);

  $('#alternates').innerHTML = alternates.length
    ? `<p class="eyebrow quiet">Also close</p><div class="also">${alternates.map((a) => `
        <div class="alt">${posterHtml(a, 'mini')}<span>${escapeHtml(a.title)}<small>${pct(a.group_fit)} ${solo ? 'match' : 'group fit'}</small></span></div>`).join('')}</div>`
    : '';
}

/**
 * Draws one bar per person showing how well the movie fits them (best fit at
 * the top). Tapping a bar opens that person's sealed pick underneath it.
 * A dash means the movie wasn't in that person's own results.
 * @param {object[]} members name, fit and position for each person
 * @param {object[]} all the people, from people() (for avatars and what they wrote)
 * @param {boolean} [animate] grow the bars in from zero (only on first draw)
 */
function renderFitBars(members, all, animate = false) {
  const rows = members
    .map((m, i) => ({ ...m, i, color: COLORS[i], text: all[i] ? all[i].text : '' }))
    .sort((a, b) => (b.fit ?? 0) - (a.fit ?? 0));
  $('#fit-bars').innerHTML = rows.map((r) => `
    <button class="fit-row" data-person="${r.i}" aria-expanded="${state.revealed === r.i}">
      ${avatar(all[r.i])}
      <span class="fit-name">${escapeHtml(r.name)}</span>
      <span class="bar"><span class="${animate ? 'grow' : ''}" style="width:${pct(r.fit ?? 0)};background:${r.color}"></span></span>
      <span class="fit-pct" title="${r.fit == null ? 'Not in their top picks' : ''}">${r.fit == null ? '—' : pct(r.fit)}</span>
    </button>
    ${state.revealed === r.i ? `<p class="note" style="--c:${r.color}">"${escapeHtml(r.text)}"</p>` : ''}`).join('');
}

/**
 * Draws a movie poster. Uses the real TMDB poster when the API sends one;
 * otherwise draws a colored placeholder with the title (and year, if known).
 * @param {{title: string, year?: number, poster_path?: string}} movie
 * @param {string} [cls] extra classes, e.g. 'front', 'back b1', 'mini'
 * @returns {string} HTML for the poster
 */
function posterHtml(movie, cls = '') {
  const title = escapeHtml(movie.title);
  if (movie.poster_path) {
    return `<img class="poster ${cls}" src="https://image.tmdb.org/t/p/w342${movie.poster_path}" alt="${title} poster">`;
  }
  const [top, bottom, ink] = POSTER_TONES[hashText(movie.title) % POSTER_TONES.length];
  // Shrink the title for long words so a word like "PADDINGTON" never breaks in half.
  const longest = Math.max(...String(movie.title).split(/\s+/).map((w) => w.length));
  const fit = Math.min(1, 7.5 / longest).toFixed(2);
  return `<div class="poster ${cls}" style="--p1:${top};--p2:${bottom};--pt:${ink};--fit:${fit}" role="img" aria-label="${title}">
    ${movie.year ? `<span class="yr">${movie.year}</span>` : ''}<span class="t">${title}</span></div>`;
}

/**
 * Draws the circular score (like a progress ring) for the group fit.
 * @param {number} f the score from 0 to 1
 * @param {string} label read out by screen readers, e.g. 'group fit'
 * @returns {string} SVG markup
 */
function ringSvg(f, label) {
  const c = 194.8; // circumference of the ring (2 × π × radius 31)
  return `<svg viewBox="0 0 74 74" role="img" aria-label="${pct(f)} ${label}">
    <circle cx="37" cy="37" r="31" class="ring-track"/>
    <circle cx="37" cy="37" r="31" class="ring-fill" stroke-dasharray="${(f * c).toFixed(1)} ${c}" transform="rotate(-90 37 37)"/>
    <text x="37" y="43" text-anchor="middle">${pct(f)}</text></svg>`;
}

// ---------- 7. EVENT WIRING ----------

// One click handler for the whole page. Each button says what it does with a
// data-action="..." attribute in index.html, and this switch runs the match.
document.addEventListener('click', (e) => {
  const modeBtn = e.target.closest('[data-mode]');
  if (modeBtn) { state.mode = modeBtn.dataset.mode; renderSetup(); return; }

  const ideaBtn = e.target.closest('[data-idea]');
  if (ideaBtn) {
    $('#pick-text').value = PLACEHOLDERS[Number(ideaBtn.dataset.idea)];
    $('#pick-error').hidden = true;
    $('#pick-text').focus();
    return;
  }

  const fitRow = e.target.closest('.fit-row');
  if (fitRow) {
    const i = Number(fitRow.dataset.person);
    state.revealed = state.revealed === i ? -1 : i;
    renderFitBars(state.results.members, people());
    return;
  }

  const action = e.target.closest('[data-action]')?.dataset.action;
  switch (action) {
    case 'go-intro': show('intro'); break;
    case 'start-group': state.mode = 'group'; renderSetup(); show('start'); break;
    case 'start-solo': state.mode = 'solo'; state.texts = []; state.turn = 0; startTurn(); break;
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

// Every keystroke in the text box clears the "write something" error (and
// moves the pin, when the mood map is on).
$('#pick-text').addEventListener('input', (e) => {
  const cur = people()[state.turn];
  if (SHOW_MOOD_MAP) movePin(e.target.value, cur.color);
  $('#pick-error').hidden = true;
});

/**
 * Records which movie the group chose when they tap "We're watching ...".
 * In mock mode it only prints to the browser console.
 * TODO: agree on an endpoint with the team for click tracking (monitoring lane).
 */
function logWatch() {
  if (USE_MOCK) { console.log('watch clicked', state.results.movie.title); return; }
  fetch('/events/watch', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ job_ids: state.jobIds, movie_id: state.results.movie.id }),
  }).catch(() => {});
}

// ---------- helpers ----------

/** Waits ms milliseconds (use with await). */
function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }
/** Average of a list of numbers. */
function avg(xs) { return xs.reduce((a, b) => a + b, 0) / xs.length; }
/** Turns 0.92 into "92%". */
function pct(f) { return `${Math.round(f * 100)}%`; }
/** Turns 130 into "2 hr 10 min". */
function formatRuntime(min) { return `${Math.floor(min / 60)} hr ${min % 60} min`; }
/** Turns any text into a stable number (the same text always gives the same number). */
function hashText(s) { let h = 0; for (const ch of String(s)) h = (h * 31 + ch.charCodeAt(0)) >>> 0; return h; }
/** A person's avatar: their initial (or number) on a circle in their color. */
function avatar(p, cls = '') {
  return `<span class="av ${cls}" style="background:${p.color}" aria-hidden="true">${escapeHtml(p.initial)}</span>`;
}
/** Makes text safe to put inside HTML, so a name like "<b>" shows as text instead of breaking the page. */
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

show('intro');
