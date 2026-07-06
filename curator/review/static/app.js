// curator/review/static/app.js
const token = new URLSearchParams(location.search).get('token') || '';
const H = {'X-Review-Token': token, 'Content-Type': 'application/json'};

let state = {buckets: [], currentBucket: null, photos: [], focused: 0, selected: new Set()};

async function api(method, path, body) {
  const r = await fetch(path, {method, headers: H, body: body ? JSON.stringify(body) : undefined});
  return r.json();
}

async function loadState() {
  const s = await api('GET', '/api/state');
  state.buckets = s.buckets;
  renderSidebar();
  if (!state.currentBucket && s.buckets.length) selectBucket(s.buckets[0].key);
}

function renderSidebar() {
  const el = document.getElementById('sidebar');
  el.innerHTML = '<h2>Buckets</h2>' + state.buckets.map(b =>
    `<div class="bucket-item${b.key === state.currentBucket ? ' active' : ''}"
          onclick="selectBucket('${b.key}')" data-key="${b.key}">
       <span>${b.label}</span><span class="count">${b.count}</span>
     </div>`).join('');
}

function selectBucket(key) {
  state.currentBucket = key;
  const b = state.buckets.find(b => b.key === key);
  state.photos = b ? b.photos : [];
  state.focused = 0;
  state.selected.clear();
  renderSidebar();
  renderGrid();
  if (key === 'needs-review') startTriage();
}

function renderGrid() {
  const grid = document.getElementById('grid');
  grid.innerHTML = state.photos.map((p, i) =>
    `<div class="thumb-card${state.focused === i ? ' focused' : ''}${state.selected.has(i) ? ' selected' : ''}"
          data-i="${i}" onclick="cardClick(${i})">
       <img loading="lazy" src="${p.thumb || ''}" alt="${p.rel_path}">
       <div class="badge">${p.verdict}</div>
     </div>`).join('');
}

function cardClick(i) {
  state.focused = i;
  if (document.getElementById('lightbox').hidden === false) openLightbox(i);
  else renderGrid();
}

function openLightbox(i) {
  const p = state.photos[i];
  if (!p) return;
  state.focused = i;
  const lb = document.getElementById('lightbox');
  lb.hidden = false;
  lb.querySelector('#lb-img-wrap img').src = p.placed ? `/${p.placed}` : p.thumb;
  const vi = p.verdict_info || {};
  lb.querySelector('#lb-info').innerHTML =
    `<h3>${p.rel_path}</h3>
     <div class="ev-line"><strong>Verdict:</strong> ${p.verdict}</div>
     <div class="ev-line"><strong>Bucket:</strong> ${p.bucket}</div>
     <pre style="margin-top:8px;font-size:11px;color:#888;white-space:pre-wrap">${JSON.stringify(vi, null, 2)}</pre>`;
}

function closeLightbox() {
  document.getElementById('lightbox').hidden = true;
}

// Triage mode
let triageIdx = 0;
function startTriage() {
  triageIdx = 0;
  showTriage();
}
function showTriage() {
  const p = state.photos[triageIdx];
  if (!p) { document.getElementById('triage').hidden = true; return; }
  const t = document.getElementById('triage');
  t.hidden = false;
  t.querySelector('img').src = p.thumb;
  t.querySelector('#triage-actions').innerHTML =
    `${triageIdx + 1}/${state.photos.length}: ${p.rel_path}<br>
     <kbd>K</kbd> keep &nbsp; <kbd>X</kbd> reject &nbsp; <kbd>Esc</kbd> exit triage`;
}
async function triageAction(to) {
  const p = state.photos[triageIdx];
  if (p) await api('POST', '/api/action', {photo: p.rel_path, to});
  triageIdx++;
  if (triageIdx >= state.photos.length) {
    document.getElementById('triage').hidden = true;
    await loadState();
  } else showTriage();
}

// Keyboard
document.addEventListener('keydown', async e => {
  const triage = !document.getElementById('triage').hidden;
  const lb = !document.getElementById('lightbox').hidden;
  const inp = document.activeElement && document.activeElement.tagName === 'INPUT';
  if (inp) return;

  if (triage) {
    if (e.key === 'k' || e.key === 'K') triageAction('keep');
    if (e.key === 'x' || e.key === 'X') triageAction('reject');
    if (e.key === 'Escape') { document.getElementById('triage').hidden = true; }
    return;
  }
  if (lb) {
    if (e.key === 'Escape' || e.key === 'Enter') closeLightbox();
    if (e.key === 'ArrowRight') { state.focused = Math.min(state.focused + 1, state.photos.length - 1); openLightbox(state.focused); }
    if (e.key === 'ArrowLeft') { state.focused = Math.max(state.focused - 1, 0); openLightbox(state.focused); }
    if (e.key === 'g' || e.key === 'G') { await action('top-pick'); closeLightbox(); }
    if (e.key === 'x' || e.key === 'X') { await action('reject'); closeLightbox(); }
    return;
  }
  const n = state.photos.length;
  if (e.key === 'ArrowRight') { state.focused = Math.min(state.focused + 1, n - 1); renderGrid(); }
  if (e.key === 'ArrowLeft') { state.focused = Math.max(state.focused - 1, 0); renderGrid(); }
  if (e.key === 'Enter') openLightbox(state.focused);
  if (e.key === ' ') { e.preventDefault(); state.selected.has(state.focused) ? state.selected.delete(state.focused) : state.selected.add(state.focused); renderGrid(); }
  if (e.key === 'g' || e.key === 'G') await action('top-pick');
  if (e.key === 'x' || e.key === 'X') await action('reject');
  if (e.key === 'u' || e.key === 'U') { await api('POST', '/api/undo', {}); toast('Undone'); await loadState(); }
  if (e.key === 'c' || e.key === 'C') toggleChat();
  if (e.key === '?') alert('G: top-pick  X: reject  U: undo  Enter: lightbox  Space: select  C: chat  Arrows: navigate');
});

async function action(to) {
  const targets = state.selected.size ? [...state.selected] : [state.focused];
  for (const i of targets) {
    const p = state.photos[i];
    if (p) await api('POST', '/api/action', {photo: p.rel_path, to});
  }
  state.selected.clear();
  toast(`Moved to ${to}`);
  await loadState();
}

// Toast
function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2000);
}

// Chat
function toggleChat() {
  document.body.classList.toggle('chat-open');
}
document.getElementById('chat-send').addEventListener('click', sendChat);
document.getElementById('chat-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') sendChat();
});
async function sendChat() {
  const inp = document.getElementById('chat-input');
  const msg = inp.value.trim();
  if (!msg) return;
  inp.value = '';
  const log = document.getElementById('chat-log');
  log.innerHTML += `<div class="chat-msg user">you: ${msg}</div>`;
  const r = await api('POST', '/api/chat', {message: msg});
  log.innerHTML += `<div class="chat-msg bot">curator: ${r.reply || '…'}</div>`;
  log.scrollTop = log.scrollHeight;
}

// Init
loadState();
