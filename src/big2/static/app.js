"use strict";

const TYPE_LABELS = {
  SINGLE: "單張", PAIR: "對子", TRIPLE: "三條", STRAIGHT: "順子",
  FULL_HOUSE: "葫蘆", FOUR_OF_A_KIND: "鐵支", STRAIGHT_FLUSH: "同花順",
};

// Seat 0 (the human, when present) is always assigned the first slot in
// each list — that slot is styled (see style.css) as the wide, face-up,
// clickable seat regardless of who's actually sitting there.
const SEAT_POSITIONS = {
  2: ["pos-bottom", "pos-top"],
  3: ["pos-bottom", "pos-left", "pos-right"],
  4: ["pos-bottom", "pos-left", "pos-top", "pos-right"],
};

// The deal is symmetric per player count (see game.deal), so we know every
// seat's starting hand size before the first event ever arrives.
const INITIAL_COUNTS = { 2: 26, 3: 17, 4: 13 };

const MAX_VISIBLE_BACKS = 8;
const ANIMATION_DELAY_MS = 550;
const FLY_MS = 500;

const els = {
  setupScreen: document.getElementById("setup-screen"),
  gameScreen: document.getElementById("game-screen"),
  gameoverScreen: document.getElementById("gameover-screen"),
  loading: document.getElementById("loading-overlay"),
  setupPlayers: document.getElementById("setup-players"),
  setupHuman: document.getElementById("setup-human"),
  setupStart: document.getElementById("setup-start"),
  setupError: document.getElementById("setup-error"),
  table: document.getElementById("table"),
  pool: document.getElementById("pool"),
  controlsBar: document.getElementById("controls-bar"),
  log: document.getElementById("log"),
  turnMsg: document.getElementById("turn-msg"),
  playBtn: document.getElementById("play-btn"),
  passBtn: document.getElementById("pass-btn"),
  moveError: document.getElementById("move-error"),
  winnerMsg: document.getElementById("winner-msg"),
  restartBtn: document.getElementById("restart-btn"),
};

let seatNames = [];
let seatEls = [];
let hasHuman = false;
const HUMAN_SEAT = 0;
let selected = new Set();

// -- generic helpers ---------------------------------------------------------

function showScreen(name) {
  for (const [key, el] of Object.entries({ setup: els.setupScreen, game: els.gameScreen, gameover: els.gameoverScreen })) {
    el.classList.toggle("hidden", key !== name);
  }
}

function showLoading(visible) {
  els.loading.classList.toggle("hidden", !visible);
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `連線失敗 (${res.status})`);
  return data;
}

function comboLabel(combo) {
  return combo ? (TYPE_LABELS[combo.type] || combo.type) : "";
}

function renderCard(card, mini) {
  const el = document.createElement("div");
  el.className = `card ${mini ? "mini" : ""} ${card.color}`;
  el.innerHTML = `<span class="rank">${card.rank}</span><span class="suit">${card.suit}</span>`;
  return el;
}

function renderCardBack() {
  const el = document.createElement("div");
  el.className = "card mini back";
  return el;
}

// -- table / seats ------------------------------------------------------------

function buildTable(names, hasHumanFlag) {
  seatNames = names;
  hasHuman = hasHumanFlag;
  els.table.querySelectorAll(".seat").forEach((el) => el.remove());

  const positions = SEAT_POSITIONS[names.length];
  seatEls = names.map((name, i) => {
    const seat = document.createElement("div");
    seat.className = `seat ${positions[i]}`;
    seat.innerHTML = `
      <div class="seat-label">
        <span class="seat-name">${name}</span>
        <span class="seat-count"></span>
      </div>
      <div class="hand-mound"></div>
      <div class="pass-bubble hidden">過牌</div>
    `;
    els.table.appendChild(seat);
    return seat;
  });
}

function setSeatCount(seatIndex, count) {
  seatEls[seatIndex].querySelector(".seat-count").textContent = count;
}

function renderAIMound(seatIndex, count) {
  const mound = seatEls[seatIndex].querySelector(".hand-mound");
  mound.innerHTML = "";
  const visible = Math.min(count, MAX_VISIBLE_BACKS);
  for (let i = 0; i < visible; i++) mound.appendChild(renderCardBack());
}

function renderHumanHand(cards) {
  const seat = seatEls[HUMAN_SEAT];
  const mound = seat.querySelector(".hand-mound");
  selected.clear();
  mound.innerHTML = "";
  cards.forEach((card, i) => {
    const el = renderCard(card, false);
    const index = i + 1;
    el.addEventListener("click", () => {
      if (seat.classList.contains("disabled")) return;
      el.classList.toggle("selected");
      if (selected.has(index)) selected.delete(index); else selected.add(index);
    });
    mound.appendChild(el);
  });
}

function setHumanSeatEnabled(enabled) {
  seatEls[HUMAN_SEAT].classList.toggle("disabled", !enabled);
}

function showPassBubble(seatIndex) {
  const bubble = seatEls[seatIndex].querySelector(".pass-bubble");
  bubble.classList.remove("hidden", "show");
  void bubble.offsetWidth;
  bubble.classList.add("show");
  setTimeout(() => bubble.classList.add("hidden"), 1100);
}

// -- flying-card animation ----------------------------------------------------

function flyCardsToPool(seatIndex, cards) {
  const mound = seatEls[seatIndex].querySelector(".hand-mound");
  const startRect = mound.getBoundingClientRect();
  const startX = startRect.left + startRect.width / 2;
  const startY = startRect.top + startRect.height / 2;
  const poolRect = els.pool.getBoundingClientRect();
  const endX = poolRect.left + poolRect.width / 2;
  const endY = poolRect.top + poolRect.height / 2;

  cards.forEach((card, i) => {
    const clone = renderCard(card, false);
    clone.classList.add("flying");
    clone.style.left = `${startX - 23}px`;
    clone.style.top = `${startY - 32}px`;
    clone.style.transform = "translate(0, 0) rotate(0deg)";
    document.body.appendChild(clone);

    const offset = (i - (cards.length - 1) / 2) * 18;
    requestAnimationFrame(() => {
      clone.style.transform = `translate(${endX - startX + offset}px, ${endY - startY}px) rotate(${offset}deg)`;
    });
    setTimeout(() => clone.remove(), FLY_MS + 30);
  });

  els.pool.innerHTML = "";
  cards.forEach((card) => els.pool.appendChild(renderCard(card, false)));
}

// -- log ---------------------------------------------------------------------

function resetLog() {
  els.log.innerHTML = "";
}

function appendLogRow(event) {
  const row = document.createElement("div");
  row.className = "log-row";

  const who = document.createElement("span");
  who.className = "who";
  who.textContent = event.player;
  row.appendChild(who);

  if (event.kind === "pass") {
    const pill = document.createElement("span");
    pill.className = "pass-pill";
    pill.textContent = "過牌";
    row.appendChild(pill);
  } else {
    const desc = document.createElement("span");
    desc.className = "desc";
    desc.textContent = comboLabel(event.combo);
    row.appendChild(desc);
    for (const card of event.combo.cards) row.appendChild(renderCard(card, true));
  }

  els.log.appendChild(row);
  els.log.scrollTop = els.log.scrollHeight;
}

// -- event playback ------------------------------------------------------------

function applyEvent(event) {
  const seatIndex = seatNames.indexOf(event.player);
  const isHumanSeat = hasHuman && seatIndex === HUMAN_SEAT;

  if (event.kind === "pass") {
    showPassBubble(seatIndex);
  } else {
    flyCardsToPool(seatIndex, event.combo.cards);
    if (isHumanSeat) {
      // The full re-render with the server's new hand only happens once the
      // whole batch finishes animating; drop the played cards from view now
      // so they don't linger next to their flying clones.
      seatEls[HUMAN_SEAT].querySelectorAll(".hand-mound .card.selected").forEach((el) => el.remove());
    }
  }
  setSeatCount(seatIndex, event.remaining[event.player]);
  if (!isHumanSeat) renderAIMound(seatIndex, event.remaining[event.player]);
  appendLogRow(event);
}

function playEvents(events, onDone) {
  let i = 0;
  function step() {
    if (i >= events.length) { onDone(); return; }
    applyEvent(events[i++]);
    setTimeout(step, ANIMATION_DELAY_MS);
  }
  step();
}

// -- turn state -----------------------------------------------------------

function applyState(state) {
  if (state.finished) {
    els.controlsBar.classList.add("hidden");
    if (hasHuman) setHumanSeatEnabled(false);
    els.winnerMsg.textContent = `贏家：${state.winner_name}`;
    showScreen("gameover");
    return;
  }

  if (state.current_is_human) {
    renderHumanHand(state.human_hand);
    setHumanSeatEnabled(true);

    if (state.must_play_3c) {
      els.turnMsg.textContent = "輪到你，第一手必須包含梅花3";
    } else if (state.is_leading) {
      els.turnMsg.textContent = "輪到你，可自由出牌";
    } else {
      els.turnMsg.textContent = `輪到你，請壓過：${comboLabel(state.required)}`;
    }
    els.passBtn.disabled = state.is_leading;
    els.playBtn.disabled = false;
    els.moveError.textContent = "";
    els.controlsBar.classList.remove("hidden");
  } else {
    setHumanSeatEnabled(false);
  }
}

// -- actions --------------------------------------------------------------

/** Replay the supplied response, then fetch one AI turn at a time.
 * data contains events and state; updates the table and controls until a
 * human turn or winner. Displays AI request errors without enabling moves
 * on an AI turn. Resolves once playback stops.
 */
async function playTurns(data) {
  els.controlsBar.classList.remove("hidden");
  els.playBtn.disabled = true;
  els.passBtn.disabled = true;
  if (hasHuman) setHumanSeatEnabled(false);
  try {
    while (true) {
      await new Promise((resolve) => playEvents(data.events, resolve));
      if (data.state.finished || data.state.current_is_human) {
        applyState(data.state);
        return;
      }
      // Refresh the human hand after its move, before waiting on the next AI.
      if (hasHuman) renderHumanHand(data.state.human_hand);
      els.turnMsg.textContent = hasHuman ? "等待 AI 出牌…" : "觀戰中，等待 AI 出牌…";
      data = await postJSON("/api/ai_turn", {});
    }
  } catch (err) {
    els.turnMsg.textContent = err.message;
  }
}

async function submitMove(indices) {
  els.playBtn.disabled = true;
  els.passBtn.disabled = true;
  els.moveError.textContent = "";
  setHumanSeatEnabled(false);
  try {
    const data = await postJSON("/api/move", { indices });
    await playTurns(data);
  } catch (err) {
    els.moveError.textContent = err.message;
    els.playBtn.disabled = false;
    els.passBtn.disabled = false;
    setHumanSeatEnabled(true);
  }
}

async function startGame() {
  const players = parseInt(els.setupPlayers.value, 10);
  const human = parseInt(els.setupHuman.value, 10);
  els.setupError.textContent = "";
  els.setupStart.disabled = true;
  showLoading(true);
  try {
    const data = await postJSON("/api/new_game", { players, human });
    showLoading(false);

    resetLog();
    els.pool.innerHTML = "";
    els.controlsBar.classList.add("hidden");
    buildTable(data.state.seat_names, human === 1);

    const initialCount = INITIAL_COUNTS[players];
    seatNames.forEach((name, i) => {
      setSeatCount(i, initialCount);
      if (hasHuman && i === HUMAN_SEAT) {
        renderHumanHand(data.state.human_hand);
        setHumanSeatEnabled(false);
      } else {
        renderAIMound(i, initialCount);
      }
    });

    showScreen("game");
    await playTurns(data);
  } catch (err) {
    showLoading(false);
    els.setupError.textContent = err.message;
  } finally {
    els.setupStart.disabled = false;
  }
}

// -- wiring --------------------------------------------------------------

els.setupStart.addEventListener("click", startGame);
els.playBtn.addEventListener("click", () => submitMove([...selected].sort((a, b) => a - b)));
els.passBtn.addEventListener("click", () => submitMove([]));
els.restartBtn.addEventListener("click", () => {
  resetLog();
  els.table.querySelectorAll(".seat").forEach((el) => el.remove());
  els.pool.innerHTML = "";
  showScreen("setup");
});
