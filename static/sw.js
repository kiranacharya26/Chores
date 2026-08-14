self.addEventListener("push", (event) => {
  let data = { title: "Chore Builder", body: "You have a chore due." };
  if (event.data) {
    try { data = event.data.json(); } catch (e) { data.body = event.data.text(); }
  }
  const options = {
    body: data.body,
    icon: "/static/icons/icon-192.png",
    badge: "/static/icons/icon-192.png",
    data: { chore_id: data.chore_id },
  };
  if (data.chore_id) {
    options.actions = [
      { action: "done", title: "✓ Done" },
      { action: "snooze", title: "Snooze 1h" },
    ];
  }
  event.waitUntil(self.registration.showNotification(data.title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const choreId = event.notification.data && event.notification.data.chore_id;

  if (choreId && (event.action === "done" || event.action === "snooze")) {
    const url = event.action === "done"
      ? `/api/chores/${choreId}/done`
      : `/api/chores/${choreId}/snooze`;
    const body = event.action === "snooze" ? JSON.stringify({ minutes: 60 }) : undefined;
    event.waitUntil(
      fetch(url, {
        method: "POST",
        headers: event.action === "snooze" ? { "Content-Type": "application/json" } : undefined,
        body,
      })
    );
    return;
  }

  event.waitUntil(clients.openWindow("/"));
});
