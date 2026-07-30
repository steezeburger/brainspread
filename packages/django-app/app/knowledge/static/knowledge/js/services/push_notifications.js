// Browser Web Push helper — wraps the PushManager/Notification APIs and
// the api.js endpoints so SettingsModal can drive subscribe/unsubscribe
// with a single call each. Reminders piggyback push delivery on top of
// the existing Discord channel (see knowledge.commands.send_due_reminders_command);
// this file only handles the client-side registration half.

// pushManager.subscribe() needs the VAPID public key as a raw
// Uint8Array, but the server hands it over as a URL-safe base64 string
// (see core.views.get_vapid_public_key) — same encoding the browser
// itself uses for subscription keys, so this is the standard conversion.
function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; i++) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

window.pushNotificationsService = {
  isSupported() {
    return (
      "serviceWorker" in navigator &&
      "PushManager" in window &&
      "Notification" in window
    );
  },

  // Null when the browser was never subscribed, or the user denied/hasn't
  // yet granted permission.
  async getSubscription() {
    if (!this.isSupported()) return null;
    const registration = await navigator.serviceWorker.ready;
    return registration.pushManager.getSubscription();
  },

  async subscribe() {
    if (!this.isSupported()) {
      throw new Error("push notifications are not supported in this browser");
    }

    const permission = await Notification.requestPermission();
    if (permission !== "granted") {
      throw new Error("notification permission was not granted");
    }

    const keyResult = await window.apiService.getVapidPublicKey();
    const vapidKey = keyResult?.data?.vapid_public_key;
    if (!vapidKey) {
      throw new Error("push notifications are not configured on the server");
    }

    const registration = await navigator.serviceWorker.ready;
    const subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(vapidKey),
    });

    const json = subscription.toJSON();
    await window.apiService.subscribePush({
      endpoint: json.endpoint,
      p256dh: json.keys.p256dh,
      auth: json.keys.auth,
    });
    return subscription;
  },

  async unsubscribe() {
    const subscription = await this.getSubscription();
    if (!subscription) return;
    const endpoint = subscription.endpoint;
    await subscription.unsubscribe();
    await window.apiService.unsubscribePush(endpoint);
  },
};
