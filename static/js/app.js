const scriptTag = document.currentScript;
const VAPID_PUBLIC_KEY = scriptTag.dataset.vapidKey;

const choreForm = document.getElementById("choreForm");
const groupsEl = document.getElementById("groups");
const emptyState = document.getElementById("emptyState");
const pushBanner = document.getElementById("pushBanner");
const enablePushBtn = document.getElementById("enablePush");
const todayLabel = document.getElementById("todayLabel");
const heatmapEl = document.getElementById("heatmap");
const heatmapTotalEl = document.getElementById("heatmapTotal");

const fab = document.getElementById("fab");
const sheetOverlay = document.getElementById("sheetOverlay");
const cancelSheet = document.getElementById("cancelSheet");

const freqSegmented = document.getElementById("freqSegmented");
const frequencyInput = document.getElementById("frequency");
const weekdaySelect = document.getElementById("weekday");
const dayOfMonthInput = document.getElementById("dayOfMonth");

const WEEKDAY_NAMES = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];
const TIME_GROUPS = [
  { key: "morning", label: "Morning", test: (h) => h < 12 },
  { key: "afternoon", label: "Afternoon", test: (h) => h >= 12 && h < 17 },
  { key: "evening", label: "Evening", test: (h) => h >= 17 },
];

todayLabel.textContent = new Date().toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" });

function openSheet() {
  sheetOverlay.classList.add("open");
}
function closeSheet() {
  sheetOverlay.classList.remove("open");
  choreForm.reset();
  setFrequency("daily");
}
fab.addEventListener("click", openSheet);
cancelSheet.addEventListener("click", closeSheet);
sheetOverlay.addEventListener("click", (e) => {
  if (e.target === sheetOverlay) closeSheet();
});

function setFrequency(freq) {
  frequencyInput.value = freq;
  [...freqSegmented.children].forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.val === freq);
  });
  weekdaySelect.style.display = freq === "weekly" ? "" : "none";
  dayOfMonthInput.style.display = freq === "monthly" ? "" : "none";
}
freqSegmented.addEventListener("click", (e) => {
  const btn = e.target.closest(".seg-btn");
  if (btn) setFrequency(btn.dataset.val);
});

async function toggleDone(chore) {
  const action = chore.done_today ? "undone" : "done";
  await fetch(`/api/chores/${chore.id}/${action}`, { method: "POST" });
  loadChores();
  loadHeatmap();
}

function isOverdue(chore) {
  if (chore.done_today || !chore.due_today) return false;
  const [h, m] = chore.reminder_time.split(":").map(Number);
  const reminderMinutes = h * 60 + m;
  const now = new Date();
  const nowMinutes = now.getHours() * 60 + now.getMinutes();
  return nowMinutes > reminderMinutes;
}

function buildChoreRow(chore) {
  const wrap = document.createElement("li");
  wrap.className = "chore-wrap";

  const swipeBg = document.createElement("div");
  swipeBg.className = "swipe-bg";
  swipeBg.textContent = chore.done_today ? "Undo" : "Done ✓";

  const overdue = isOverdue(chore);
  const li = document.createElement("li");
  li.className = "chore" + (chore.done_today ? " done" : "") + (overdue ? " overdue" : "");

  const check = document.createElement("button");
  check.className = "check" + (chore.done_today ? " checked" : "");
  check.textContent = "✓";
  check.addEventListener("click", () => {
    li.classList.add("pulse");
    toggleDone(chore);
  });

  const info = document.createElement("div");
  info.className = "chore-info";
  const metaText = chore.frequency === "daily"
    ? "Daily"
    : chore.frequency === "weekly"
      ? `Weekly · ${WEEKDAY_NAMES[chore.weekday]}`
      : `Monthly · day ${chore.day_of_month}`;
  const streakHtml = chore.streak > 0 ? `<span class="streak-badge">🔥${chore.streak}</span>` : "";
  const overdueHtml = overdue ? `<span class="overdue-badge">Overdue</span>` : "";
  info.innerHTML = `<span class="name">${chore.name}</span><span class="meta">${metaText} · ${chore.reminder_time} ${streakHtml} ${overdueHtml}</span>`;

  const delBtn = document.createElement("button");
  delBtn.className = "icon-btn";
  delBtn.textContent = "✕";
  delBtn.addEventListener("click", async () => {
    await fetch(`/api/chores/${chore.id}`, { method: "DELETE" });
    loadChores();
    loadHeatmap();
  });

  li.appendChild(check);
  li.appendChild(info);
  li.appendChild(delBtn);
  wrap.appendChild(swipeBg);
  wrap.appendChild(li);

  attachSwipe(li, swipeBg, chore);

  return wrap;
}

function attachSwipe(li, swipeBg, chore) {
  let startX = 0;
  let currentX = 0;
  let dragging = false;
  const threshold = 90;

  li.addEventListener("touchstart", (e) => {
    startX = e.touches[0].clientX;
    dragging = true;
    li.style.transition = "none";
  }, { passive: true });

  li.addEventListener("touchmove", (e) => {
    if (!dragging) return;
    currentX = e.touches[0].clientX - startX;
    if (currentX < 0) currentX = Math.max(currentX, -120);
    else currentX = Math.min(currentX, 120);
    li.style.transform = `translateX(${currentX}px)`;
    swipeBg.style.opacity = Math.min(Math.abs(currentX) / threshold, 1);
  }, { passive: true });

  li.addEventListener("touchend", () => {
    dragging = false;
    li.style.transition = "";
    swipeBg.style.opacity = "0";
    if (Math.abs(currentX) > threshold) {
      li.style.transform = "translateX(0)";
      toggleDone(chore);
    } else {
      li.style.transform = "translateX(0)";
    }
    currentX = 0;
  });
}

async function loadChores() {
  const res = await fetch("/api/chores");
  const chores = await res.json();
  groupsEl.innerHTML = "";
  emptyState.style.display = chores.length === 0 ? "" : "none";

  const grouped = { morning: [], afternoon: [], evening: [] };
  for (const chore of chores) {
    const hour = parseInt((chore.reminder_time || "09:00").split(":")[0], 10);
    const group = TIME_GROUPS.find((g) => g.test(hour)) || TIME_GROUPS[0];
    grouped[group.key].push(chore);
  }

  for (const group of TIME_GROUPS) {
    const items = grouped[group.key];
    if (items.length === 0) continue;
    const header = document.createElement("div");
    header.className = "group-header";
    header.textContent = group.label;
    groupsEl.appendChild(header);

    const ul = document.createElement("ul");
    for (const chore of items) {
      ul.appendChild(buildChoreRow(chore));
    }
    groupsEl.appendChild(ul);
  }
}

async function loadHeatmap() {
  const res = await fetch("/api/heatmap");
  const days = await res.json();
  heatmapEl.innerHTML = "";
  const todayIso = new Date().toISOString().slice(0, 10);
  let total = 0;
  const max = Math.max(1, ...days.map((d) => d.count));

  for (const day of days) {
    total += day.count;
    const cell = document.createElement("div");
    cell.className = "heatmap-cell" + (day.date === todayIso ? " today" : "");
    if (day.count > 0) {
      const intensity = day.count / max;
      const alpha = 0.25 + intensity * 0.75;
      cell.style.background = `rgba(59, 130, 246, ${alpha.toFixed(2)})`;
    }
    cell.title = `${day.date}: ${day.count} done`;
    heatmapEl.appendChild(cell);
  }
  heatmapTotalEl.textContent = `${total} done in 12 weeks`;
}

choreForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = document.getElementById("name").value.trim();
  const frequency = frequencyInput.value;
  const reminder_time = document.getElementById("reminderTime").value || "09:00";
  const payload = { name, frequency, reminder_time };
  if (frequency === "weekly") payload.weekday = parseInt(weekdaySelect.value, 10);
  if (frequency === "monthly") payload.day_of_month = parseInt(dayOfMonthInput.value, 10) || 1;

  const res = await fetch("/api/chores", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (res.ok) {
    closeSheet();
    loadChores();
    loadHeatmap();
  }
});

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = atob(base64);
  return Uint8Array.from([...rawData].map((c) => c.charCodeAt(0)));
}

async function setupPush() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) return;

  const registration = await navigator.serviceWorker.register("/static/sw.js");
  const existingSub = await registration.pushManager.getSubscription();

  if (existingSub || Notification.permission === "denied") return;

  pushBanner.style.display = "flex";
  enablePushBtn.addEventListener("click", async () => {
    const permission = await Notification.requestPermission();
    if (permission !== "granted") return;
    const sub = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC_KEY),
    });
    await fetch("/api/subscribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(sub.toJSON()),
    });
    pushBanner.style.display = "none";
  });
}

loadChores();
loadHeatmap();
setupPush();
