// === Telegram Mini App ===
const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
}

const initData = tg?.initData || "";
const currentUser = tg?.initDataUnsafe?.user || { id: 0, first_name: "Dev" };

// Если открыто вне Telegram — показать инструкцию
if (!tg || !initData) {
  document.body.innerHTML = `
    <div style="font-family:'IBM Plex Mono',monospace;padding:40px 24px;max-width:400px;margin:0 auto">
      <div style="font-size:22px;font-weight:700;letter-spacing:-0.02em;margin-bottom:16px">МАЯК</div>
      <div style="font-size:14px;color:#737373;line-height:1.8;margin-bottom:32px">
        Это Telegram Mini App.<br>
        Открой через бота:
      </div>
      <a href="https://t.me/kouch_sessii_109_bot"
         style="display:block;background:#171717;color:#fff;text-decoration:none;font-family:'IBM Plex Mono',monospace;font-size:13px;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;padding:14px 20px;text-align:center">
        ОТКРЫТЬ БОТА
      </a>
    </div>
  `;
}

// === Состояние ===
let state = {
  year: new Date().getFullYear(),
  month: new Date().getMonth() + 1, // 1-12
  selectedDate: null,
  slots: [],
  daysWithSlots: new Set(),
};

const MONTH_NAMES = [
  "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"
];
const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

const ROLE_LABELS = {
  coach: "Коуч",
  client: "Клиент",
  curator: "Куратор",
  viewer: "Зритель",
};

const ROLE_DESCRIPTIONS = {
  coach: "проводит сессию",
  client: "в роли клиента",
  curator: "даёт обратную связь",
  viewer: "наблюдает",
};

// === API ===
async function apiFetch(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Init-Data": initData,
      ...options.headers,
    },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Ошибка ${res.status}`);
  }
  return res.json();
}

// === Экраны ===
function showScreen(id) {
  document.querySelectorAll(".screen").forEach((s) => s.classList.remove("active"));
  document.getElementById(id).classList.add("active");
}

// === Тост ===
let toastTimer = null;
function showToast(msg, isError = false) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.remove("hidden", "error");
  if (isError) el.classList.add("error");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), 2800);
}

// === Календарь ===
async function loadCalendar() {
  const grid = document.getElementById("calendar-grid");
  grid.innerHTML = `<div class="loading">загрузка...</div>`;
  document.getElementById("month-label").textContent =
    `${MONTH_NAMES[state.month - 1]} ${state.year}`;

  try {
    const data = await apiFetch(`/api/calendar/${state.year}/${state.month}`);
    state.daysWithSlots = new Set(data.days.map((d) => d.split("-")[2].replace(/^0/, "")));
    renderCalendar();
  } catch (e) {
    grid.innerHTML = `<div class="empty-state">не удалось загрузить<br>${e.message}</div>`;
  }
}

function renderCalendar() {
  const grid = document.getElementById("calendar-grid");
  const today = new Date();
  const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;

  // Первый день месяца (0=вс, 1=пн...)
  const firstDay = new Date(state.year, state.month - 1, 1).getDay();
  // Приводим к Пн=0
  const startOffset = (firstDay === 0 ? 6 : firstDay - 1);
  const daysInMonth = new Date(state.year, state.month, 0).getDate();

  let html = `<div class="weekdays">`;
  WEEKDAYS.forEach((d) => {
    html += `<div class="weekday-label">${d}</div>`;
  });
  html += `</div><div class="days-grid">`;

  // Пустые ячейки
  for (let i = 0; i < startOffset; i++) {
    html += `<div class="day-cell empty"></div>`;
  }

  for (let d = 1; d <= daysInMonth; d++) {
    const dateStr = `${state.year}-${String(state.month).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
    const hasSlots = state.daysWithSlots.has(String(d));
    const isToday = dateStr === todayStr;

    let cls = "day-cell";
    if (hasSlots) cls += " has-slots";
    if (isToday) cls += " today";

    const onclick = hasSlots ? `onclick="openDay('${dateStr}')"` : "";
    html += `<div class="${cls}" ${onclick}>${d}</div>`;
  }

  html += `</div>`;
  grid.innerHTML = html;
}

async function openDay(dateStr) {
  state.selectedDate = dateStr;
  const [, m, d] = dateStr.split("-");
  document.getElementById("slots-date-label").textContent =
    `${parseInt(d)} ${MONTH_NAMES[parseInt(m) - 1]}`;

  showScreen("screen-slots");
  await loadSlots(dateStr);
}

// === Слоты ===
async function loadSlots(dateStr) {
  const list = document.getElementById("slots-list");
  list.innerHTML = `<div class="loading">загрузка...</div>`;

  try {
    const data = await apiFetch(`/api/slots/${dateStr}`);
    state.slots = data.slots;
    renderSlots();
  } catch (e) {
    list.innerHTML = `<div class="empty-state">ошибка загрузки<br>${e.message}</div>`;
  }
}

function renderSlots() {
  const list = document.getElementById("slots-list");
  if (!state.slots.length) {
    list.innerHTML = `<div class="empty-state">на этот день<br>слотов нет</div>`;
    return;
  }

  list.innerHTML = state.slots.map((slot) => renderSlotCard(slot)).join("");
}

function renderSlotCard(slot) {
  const r = slot.roles;
  const myBooking = getMyRole(slot);

  const roleRows = [
    { key: "coach", label: "Коуч", limit: 1, taken: r.coach },
    { key: "client", label: "Клиент", limit: 1, taken: r.client },
    { key: "curator", label: "Куратор", limit: 1, taken: r.curator },
  ];

  const rolesHtml = roleRows.map(({ key, label, limit, taken }) => {
    const isMine = myBooking?.role === key;
    const statusText = isMine
      ? `<span class="role-status mine">ты <span class="my-role-badge">${label.toLowerCase()}</span></span>`
      : taken >= limit
      ? `<span class="role-status taken">занято</span>`
      : `<span class="role-status free">свободно</span>`;

    return `<div class="role-row">
      <span class="role-name">${label}</span>
      ${statusText}
    </div>`;
  }).join("");

  const viewerRow = (() => {
    const isMine = myBooking?.role === "viewer";
    const count = r.viewer;
    const text = isMine
      ? `<span class="role-status mine">ты зритель</span>`
      : count > 0
      ? `<span class="role-status viewer-count">${count} чел.</span>`
      : `<span class="role-status free">свободно</span>`;
    return `<div class="role-row">
      <span class="role-name">Зрители</span>
      ${text}
    </div>`;
  })();

  const actionBtn = myBooking
    ? `<button class="btn-cancel" onclick="cancelBooking(${slot.id})">ОТМЕНИТЬ ЗАПИСЬ</button>`
    : `<button class="btn-book" onclick="openRoleModal(${slot.id})">ЗАПИСАТЬСЯ</button>`;

  return `<div class="slot-card" id="slot-${slot.id}">
    <div class="slot-time">${slot.time}</div>
    <div class="slot-roles">
      ${rolesHtml}
      ${viewerRow}
    </div>
    ${actionBtn}
  </div>`;
}

function getMyRole(slot) {
  // Проверяем через локальное состояние (обновляется после бронирования)
  return slot._myRole || null;
}

// === Модал ролей ===
let pendingSlotId = null;

function openRoleModal(slotId) {
  pendingSlotId = slotId;
  const slot = state.slots.find((s) => s.id === slotId);
  if (!slot) return;

  document.getElementById("role-slot-info").textContent =
    `${state.selectedDate} · ${slot.time}`;

  const r = slot.roles;
  const roles = [
    { key: "coach", label: "Коуч", desc: "проводит сессию", taken: r.coach >= 1 },
    { key: "client", label: "Клиент", desc: "в роли клиента", taken: r.client >= 1 },
    { key: "curator", label: "Куратор", desc: "даёт обратную связь", taken: r.curator >= 1 },
    { key: "viewer", label: "Зритель", desc: "наблюдает", taken: false },
  ];

  const btns = roles.map(({ key, label, desc, taken }) => {
    const disabledAttr = taken ? "disabled" : "";
    const takenText = taken ? "занято" : "";
    const isViewer = key === "viewer";
    return `<button class="btn-role ${isViewer ? "viewer-role" : ""}"
      ${disabledAttr} onclick="bookRole('${key}')">
      <span>${label}</span>
      <span class="role-tag">${taken ? takenText : desc}</span>
    </button>`;
  }).join("");

  document.getElementById("role-buttons").innerHTML = btns;
  document.getElementById("modal-role").classList.remove("hidden");
}

function closeModal() {
  document.getElementById("modal-role").classList.add("hidden");
  pendingSlotId = null;
}

async function bookRole(role) {
  if (!pendingSlotId) return;
  closeModal();

  try {
    await apiFetch("/api/book", {
      method: "POST",
      body: JSON.stringify({ slot_id: pendingSlotId, role }),
    });

    // Обновляем локальное состояние
    const slot = state.slots.find((s) => s.id === pendingSlotId);
    if (slot) {
      if (role !== "viewer") slot.roles[role]++;
      else slot.roles.viewer++;
      slot._myRole = { role };
    }

    showToast(`Записан как ${ROLE_LABELS[role].toLowerCase()}`);
    renderSlots();
    if (tg) tg.HapticFeedback?.notificationOccurred("success");
  } catch (e) {
    showToast(e.message, true);
    if (tg) tg.HapticFeedback?.notificationOccurred("error");
  }
}

async function cancelBooking(slotId) {
  try {
    await apiFetch(`/api/book/${slotId}`, { method: "DELETE" });

    const slot = state.slots.find((s) => s.id === slotId);
    if (slot && slot._myRole) {
      const role = slot._myRole.role;
      if (role !== "viewer") slot.roles[role] = Math.max(0, slot.roles[role] - 1);
      else slot.roles.viewer = Math.max(0, slot.roles.viewer - 1);
      slot._myRole = null;
    }

    showToast("Запись отменена");
    renderSlots();
  } catch (e) {
    showToast(e.message, true);
  }
}

// === Навигация ===
document.getElementById("prev-month").addEventListener("click", () => {
  state.month--;
  if (state.month < 1) { state.month = 12; state.year--; }
  loadCalendar();
});

document.getElementById("next-month").addEventListener("click", () => {
  state.month++;
  if (state.month > 12) { state.month = 1; state.year++; }
  loadCalendar();
});

document.getElementById("back-to-calendar").addEventListener("click", () => {
  showScreen("screen-calendar");
});

document.getElementById("modal-cancel").addEventListener("click", closeModal);

// Закрыть модал по тапу вне карточки
document.getElementById("modal-role").addEventListener("click", (e) => {
  if (e.target === e.currentTarget) closeModal();
});

// === Запуск ===
loadCalendar();
