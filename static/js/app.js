const scriptTag = document.currentScript;
const VAPID_PUBLIC_KEY = scriptTag.dataset.vapidKey;

const choreForm = document.getElementById("choreForm");
const groupsEl = document.getElementById("groups");
const emptyState = document.getElementById("emptyState");
const pushBanner = document.getElementById("pushBanner");
const enablePushBtn = document.getElementById("enablePush");
const todayLabel = document.getElementById("todayLabel");
const todayStat = document.getElementById("todayStat");
const weekBarsEl = document.getElementById("weekBars");
const weekTotalEl = document.getElementById("weekTotal");

const fab = document.getElementById("fab");
const sheetOverlay = document.getElementById("sheetOverlay");
const cancelSheet = document.getElementById("cancelSheet");

const freqSegmented = document.getElementById("freqSegmented");
const frequencyInput = document.getElementById("frequency");
const weekdaySelect = document.getElementById("weekday");
const dayOfMonthInput = document.getElementById("dayOfMonth");
const intervalDaysInput = document.getElementById("intervalDays");
const intervalHint = document.getElementById("intervalHint");

const personChip = document.getElementById("personChip");
const personSheetOverlay = document.getElementById("personSheetOverlay");
const personInput = document.getElementById("personInput");
const partnerInput = document.getElementById("partnerInput");
const savePersonBtn = document.getElementById("savePerson");

const assigneeFilter = document.getElementById("assigneeFilter");
const assignSegmented = document.getElementById("assignSegmented");
const assignedToInput = document.getElementById("assignedTo");
let currentFilter = "mine";
let lastChores = [];

const timeTrigger = document.getElementById("timeTrigger");
const timeTriggerLabel = document.getElementById("timeTriggerLabel");
const reminderTimeInput = document.getElementById("reminderTime");
const timeSheetOverlay = document.getElementById("timeSheetOverlay");
const cancelTimeSheet = document.getElementById("cancelTimeSheet");
const confirmTimeSheet = document.getElementById("confirmTimeSheet");
const hourWheel = document.getElementById("hourWheel");
const minuteWheel = document.getElementById("minuteWheel");
const ampmWheel = document.getElementById("ampmWheel");

const WEEKDAY_NAMES = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];
const WEEKDAY_SHORT = ["M","T","W","T","F","S","S"];
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
  setReminderTime("09:00");
  [...assignSegmented.children].forEach((b) => b.classList.toggle("active", b.dataset.val === "me"));
  assignedToInput.value = "";
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
  intervalDaysInput.style.display = freq === "interval" ? "" : "none";
  intervalHint.style.display = freq === "interval" ? "" : "none";
}
freqSegmented.addEventListener("click", (e) => {
  const btn = e.target.closest(".seg-btn");
  if (btn) setFrequency(btn.dataset.val);
});

// ---------- Who's using this device ----------

function getPerson() {
  return localStorage.getItem("chorePerson") || "";
}
function setPerson(name) {
  localStorage.setItem("chorePerson", name);
  renderPersonChip();
}
function getPartner() {
  return localStorage.getItem("chorePartner") || "";
}
function setPartner(name) {
  localStorage.setItem("chorePartner", name);
}
function renderPersonChip() {
  const name = getPerson();
  personChip.textContent = name ? name : "Who's this?";
}
function openPersonSheet() {
  personInput.value = getPerson();
  partnerInput.value = getPartner();
  personSheetOverlay.classList.add("open");
  setTimeout(() => personInput.focus(), 250);
}
function closePersonSheet() {
  personSheetOverlay.classList.remove("open");
}
personChip.addEventListener("click", openPersonSheet);
personSheetOverlay.addEventListener("click", (e) => {
  if (e.target === personSheetOverlay) closePersonSheet();
});
savePersonBtn.addEventListener("click", () => {
  const name = personInput.value.trim();
  const partner = partnerInput.value.trim();
  if (name) setPerson(name);
  if (partner) setPartner(partner);
  closePersonSheet();
});
renderPersonChip();
if (!getPerson() || !getPartner()) openPersonSheet();

assigneeFilter.addEventListener("click", (e) => {
  const btn = e.target.closest(".seg-btn");
  if (!btn) return;
  currentFilter = btn.dataset.val;
  [...assigneeFilter.children].forEach((b) => b.classList.toggle("active", b === btn));
  renderChoreList();
});

assignSegmented.addEventListener("click", (e) => {
  const btn = e.target.closest(".seg-btn");
  if (!btn) return;
  [...assignSegmented.children].forEach((b) => b.classList.toggle("active", b === btn));
  assignedToInput.value = btn.dataset.val === "me" ? getPerson()
    : btn.dataset.val === "partner" ? getPartner() : "unassigned";
});

// ---------- Time wheel picker ----------

function setReminderTime(hhmm) {
  reminderTimeInput.value = hhmm;
  const [h24, m] = hhmm.split(":").map(Number);
  const period = h24 >= 12 ? "PM" : "AM";
  const h12 = ((h24 + 11) % 12) + 1;
  timeTriggerLabel.textContent = `${h12}:${String(m).padStart(2, "0")} ${period}`;
}

const HOURS = Array.from({ length: 12 }, (_, i) => i + 1); // 1..12
const MINUTES = Array.from({ length: 12 }, (_, i) => i * 5); // 0,5,...,55
const PERIODS = ["AM", "PM"];
const ITEM_HEIGHT = 44;

function buildWheel(el, items, formatter) {
  el.innerHTML = "";
  const padTop = document.createElement("div");
  padTop.className = "wheel-pad";
  el.appendChild(padTop);
  items.forEach((val) => {
    const item = document.createElement("div");
    item.className = "wheel-item";
    item.textContent = formatter(val);
    item.dataset.val = val;
    el.appendChild(item);
  });
  const padBottom = document.createElement("div");
  padBottom.className = "wheel-pad";
  el.appendChild(padBottom);
}

function wheelSelectedIndex(el) {
  return Math.round(el.scrollTop / ITEM_HEIGHT);
}

function scrollWheelTo(el, index, smooth) {
  if (smooth) {
    el.scrollTo({ top: index * ITEM_HEIGHT, behavior: "smooth" });
  } else {
    el.scrollTop = index * ITEM_HEIGHT;
  }
}

function highlightWheel(el) {
  const idx = wheelSelectedIndex(el);
  [...el.querySelectorAll(".wheel-item")].forEach((item, i) => {
    item.classList.toggle("selected", i === idx);
  });
  return idx;
}

function setupWheel(el) {
  let debounceTimer = null;
  el.addEventListener("scroll", () => {
    highlightWheel(el);
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      const idx = wheelSelectedIndex(el);
      scrollWheelTo(el, idx, true);
      highlightWheel(el);
    }, 120);
  });
}

buildWheel(hourWheel, HOURS, (v) => v);
buildWheel(minuteWheel, MINUTES, (v) => String(v).padStart(2, "0"));
buildWheel(ampmWheel, PERIODS, (v) => v);
setupWheel(hourWheel);
setupWheel(minuteWheel);
setupWheel(ampmWheel);

function openTimeSheet() {
  const [h24, m] = reminderTimeInput.value.split(":").map(Number);
  const period = h24 >= 12 ? "PM" : "AM";
  const h12 = ((h24 + 11) % 12) + 1;
  const minuteIdx = Math.round(m / 5) % 12;

  timeSheetOverlay.classList.add("open");
  // set scroll positions without animation once the sheet is visible
  requestAnimationFrame(() => {
    scrollWheelTo(hourWheel, HOURS.indexOf(h12), false);
    scrollWheelTo(minuteWheel, minuteIdx, false);
    scrollWheelTo(ampmWheel, PERIODS.indexOf(period), false);
    highlightWheel(hourWheel);
    highlightWheel(minuteWheel);
    highlightWheel(ampmWheel);
  });
}
function closeTimeSheet() {
  timeSheetOverlay.classList.remove("open");
}
timeTrigger.addEventListener("click", openTimeSheet);
cancelTimeSheet.addEventListener("click", closeTimeSheet);
timeSheetOverlay.addEventListener("click", (e) => {
  if (e.target === timeSheetOverlay) closeTimeSheet();
});
confirmTimeSheet.addEventListener("click", () => {
  const h12 = HOURS[wheelSelectedIndex(hourWheel)];
  const m = MINUTES[wheelSelectedIndex(minuteWheel)];
  const period = PERIODS[wheelSelectedIndex(ampmWheel)];
  let h24 = h12 % 12;
  if (period === "PM") h24 += 12;
  setReminderTime(`${String(h24).padStart(2, "0")}:${String(m).padStart(2, "0")}`);
  closeTimeSheet();
});

// ---------- Chore list ----------

async function toggleDone(chore) {
  const action = chore.done_today ? "undone" : "done";
  const body = action === "done" ? JSON.stringify({ person: getPerson() }) : undefined;
  await fetch(`/api/chores/${chore.id}/${action}`, {
    method: "POST",
    headers: action === "done" ? { "Content-Type": "application/json" } : undefined,
    body,
  });
  loadChores();
  loadWeek();
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
      : chore.frequency === "monthly"
        ? `Monthly · day ${chore.day_of_month}`
        : `Every ${chore.interval_days}d`;
  const streakHtml = chore.streak > 0 ? `<span class="streak-badge">🔥${chore.streak}</span>` : "";
  const overdueHtml = overdue ? `<span class="overdue-badge">Overdue</span>` : "";
  const myName = getPerson();
  const doneByHtml = (chore.done_today && chore.done_by && chore.done_by !== myName)
    ? `<span class="done-by-badge">✓ ${chore.done_by}</span>` : "";
  const showAssignee = currentFilter === "all";
  const isUnassigned = chore.assigned_to === "unassigned";
  const assigneeHtml = showAssignee
    ? isUnassigned
      ? `<span class="assignee-tag unassigned">Unassigned</span>`
      : `<span class="assignee-tag">${chore.assigned_to}</span>`
    : "";
  info.innerHTML = `<span class="name">${chore.name}</span><span class="meta">${metaText} · ${chore.reminder_time} ${streakHtml} ${overdueHtml} ${doneByHtml} ${assigneeHtml}</span>`;

  const delBtn = document.createElement("button");
  delBtn.className = "icon-btn";
  delBtn.textContent = "✕";
  delBtn.addEventListener("click", async () => {
    await fetch(`/api/chores/${chore.id}`, { method: "DELETE" });
    loadChores();
    loadWeek();
  });

  li.appendChild(check);
  li.appendChild(info);
  if (showAssignee && isUnassigned) {
    const claimBtn = document.createElement("button");
    claimBtn.className = "claim-btn";
    claimBtn.textContent = "Claim";
    claimBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      await fetch(`/api/chores/${chore.id}/claim`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ person: getPerson() }),
      });
      loadChores();
    });
    li.appendChild(claimBtn);
  }
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
  lastChores = await res.json();
  renderChoreList();
}

function renderChoreList() {
  const chores = lastChores.filter((c) => {
    if (currentFilter === "all") return true;
    if (currentFilter === "mine") return c.assigned_to === getPerson();
    return c.assigned_to === getPartner(); // "theirs"
  });
  groupsEl.innerHTML = "";
  emptyState.style.display = chores.length === 0 ? "" : "none";

  const dueToday = chores.filter((c) => c.due_today);
  const doneToday = dueToday.filter((c) => c.done_today);
  todayStat.textContent = dueToday.length ? `${doneToday.length}/${dueToday.length} today` : "";

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

async function loadWeek() {
  const res = await fetch("/api/week");
  const days = await res.json();
  weekBarsEl.innerHTML = "";
  const todayIso = new Date().toISOString().slice(0, 10);

  let totalDone = 0, totalDue = 0;
  for (const day of days) {
    totalDone += day.done;
    totalDue += day.total;

    const col = document.createElement("div");
    col.className = "week-day" + (day.date === todayIso ? " is-today" : "");

    const track = document.createElement("div");
    track.className = "week-bar-track";
    const fill = document.createElement("div");
    const ratio = day.total > 0 ? day.done / day.total : 0;
    fill.className = "week-bar-fill" + (day.total > 0 && day.done === day.total ? " full" : "") + (day.total === 0 ? " empty" : "");
    fill.style.height = day.total > 0 ? `${Math.max(ratio * 100, 6)}%` : "3px";
    track.appendChild(fill);

    const label = document.createElement("div");
    label.className = "week-day-label";
    label.textContent = WEEKDAY_SHORT[day.weekday];

    const count = document.createElement("div");
    count.className = "week-day-count";
    count.textContent = day.total > 0 ? `${day.done}/${day.total}` : "–";

    col.appendChild(track);
    col.appendChild(label);
    col.appendChild(count);
    weekBarsEl.appendChild(col);
  }
  weekTotalEl.textContent = totalDue > 0 ? `${totalDone}/${totalDue} this week` : "";
}

choreForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = document.getElementById("name").value.trim();
  const frequency = frequencyInput.value;
  const reminder_time = reminderTimeInput.value || "09:00";
  const payload = { name, frequency, reminder_time };
  payload.assigned_to = assignedToInput.value || getPerson();
  if (frequency === "weekly") payload.weekday = parseInt(weekdaySelect.value, 10);
  if (frequency === "monthly") payload.day_of_month = parseInt(dayOfMonthInput.value, 10) || 1;
  if (frequency === "interval") payload.interval_days = parseInt(intervalDaysInput.value, 10) || 3;

  const res = await fetch("/api/chores", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (res.ok) {
    closeSheet();
    loadChores();
    loadWeek();
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
    const subJson = sub.toJSON();
    subJson.person = getPerson();
    await fetch("/api/subscribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(subJson),
    });
    pushBanner.style.display = "none";
  });
}

setReminderTime("09:00");
loadChores();
loadWeek();
setupPush();
