/*
 * service-worker.js: shows the push reminders (Sunday planning, meetings) on a device where someone chose
 * "Enable reminders" in the portal header (portal-enhancements.js registers this file).
 *
 * portal-reminders (portal-api reminders.py) sends a message through the browser's push service; this worker turns it
 * into a notification. A click on the notification opens the page it names in the portal tab (or a new tab).
 * nginx serves this file with "no-cache", so a new version reaches every device on its next visit.
 */

// Take over open portal tabs straight away. Otherwise the tab in which reminders were just enabled is not
// controlled by this worker until it is reloaded, and a click on a reminder could not open the page there.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

// A reminder arrives: { title, body, tag, url }. The same tag replaces an older notification instead of stacking.
self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data.json();
  } catch {}
  event.waitUntil(
    self.registration.showNotification(data.title || "GFM Mission System", {
      body: data.body || "Open the portal for your mission update.",
      tag: data.tag || "mission-update",
      icon: "/mission-icon.svg",
      badge: "/mission-icon.svg",
      data: { url: data.url || "/#overview" },
    })
  );
});

// The portal tab itself, not one of the pages shown inside it (they are windows of this site too).
function portalTab(windows) {
  return windows.find((client) => client.frameType !== "nested" && new URL(client.url).origin === self.location.origin);
}

// Opens the reminder's page: in the portal tab when one is open, otherwise in a new tab. Only pages of this portal.
async function openReminderPage(url) {
  const windows = await clients.matchAll({ type: "window", includeUncontrolled: true });
  const existing = portalTab(windows);
  if (!existing) return clients.openWindow(url);
  // navigate() works only in tabs this worker controls; otherwise bring the tab forward as it is.
  try {
    const moved = await existing.navigate(url);
    return (moved || existing).focus();
  } catch {
    return existing.focus().catch(() => clients.openWindow(url));
  }
}

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL(event.notification.data?.url || "/#overview", self.location.origin).href;
  if (new URL(url).origin !== self.location.origin) return;
  event.waitUntil(openReminderPage(url));
});
