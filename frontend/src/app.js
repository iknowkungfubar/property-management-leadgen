/**
 * Main Alpine.js application.
 *
 * Provides the top-level `app()` component with routing, IPC helpers,
 * notification system, keyboard shortcuts, sidebar state, and activity feed.
 */

import Alpine from "alpinejs";
import { dashboard } from "./components/Dashboard.js";
import { leadTable } from "./components/LeadTable.js";
import { captchaModal } from "./components/CaptchaModal.js";
import { settingsPanel } from "./components/Settings.js";

/* ── Error message catalogue ───────────────────────────────────────── */

const ERROR_MESSAGES = {
  "-10000": {
    title: "Authentication Error",
    detail: "Your API key is invalid or expired. Update it in Settings.",
    action: "settings",
  },
  "-20000": {
    title: "Rate Limited",
    detail: "Too many requests. Waiting before retrying.",
    action: null,
  },
  "-30000": {
    title: "Not Found",
    detail: "The requested resource could not be found.",
    action: null,
  },
  "-40000": {
    title: "Internal Error",
    detail: "Something went wrong. Please try again.",
    action: null,
  },
  "-50000": {
    title: "Missing Information",
    detail: "Please check your input and try again.",
    action: null,
  },
  "-60000": {
    title: "Unknown Command",
    detail: "This feature is not available.",
    action: null,
  },
};


function formatError(err) {
  if (typeof err === "string") {
    return { title: "Error", detail: err, action: null };
  }
  const code = String(err.code || -40000);
  return ERROR_MESSAGES[code] || {
    title: "Error",
    detail: err.message || "Unknown error",
    action: null,
  };
}


/* ── IPC helpers ──────────────────────────────────────────────────── */

const IS_TAURI = typeof window !== "undefined" && window.__TAURI__;

/**
 * Send a JSON-RPC-style command to the Python sidecar and return the result.
 */
async function ipc(method, params = {}) {
  const payload = { method, params };

  if (IS_TAURI) {
    const { invoke } = window.__TAURI__.core;
    return invoke("sidecar_command", { cmd: payload });
  }

  try {
    const resp = await fetch("http://localhost:1420/ipc", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) throw new Error(`IPC proxy returned ${resp.status}`);
    const data = await resp.json();
    if (data.error) throw data.error;
    return data.result;
  } catch {
    return mockIpc(method, params);
  }
}

function mockIpc(method, _params) {
  switch (method) {
    case "ping": return { pong: true };
    case "settings.get": return { value: null };
    case "discovery.import_csv": return { imported: 47 };
    case "sidecar.poll_events": return [];
    default: return {};
  }
}


/* ── Keyboard shortcuts ───────────────────────────────────────────── */

const SHORTCUTS = {
  "d": "dashboard",
  "l": "leads",
  ",": "settings",
};

function handleKeyboard(e, navFn) {
  if (!(e.ctrlKey || e.metaKey)) return;
  const view = SHORTCUTS[e.key];
  if (view) {
    e.preventDefault();
    navFn(view);
  }
}


/* ── Notification helpers ─────────────────────────────────────────── */

let _notificationId = 0;

function nextNotifId() {
  _notificationId += 1;
  return _notificationId;
}


/* ── Main Alpine component ────────────────────────────────────────── */

function app() {
  return {
    // ── State ──────────────────────────────────────────────────────
    currentView: "dashboard",
    leads: [],
    isProcessing: false,
    hasSidecar: false,
    captchaEvent: null,
    _pollTimer: null,

    /* Notification stack */
    notifications: [],

    /* Setup hint */
    showSetupHint: false,
    hasLLMProvider: false,

    /* Sidebar */
    sidebarOpen: false,

    /* Loading / skeleton */
    isLoading: false,

    /* Activity feed */
    activityFeed: [],

    /* Agent status */
    status: {
      discovery: "idle",
      unmasking: "idle",
      intelligence: "idle",
      synthesis: "idle",
    },
    progress: {
      leadsFound: 0,
      leadsUnmasked: 0,
      leadsScored: 0,
      leadsExported: 0,
    },

    /* ── Computed helpers (called from template) ─────────────────── */

    sortedActivity() {
      return [...this.activityFeed].slice(-20).reverse();
    },

    totalLeads() {
      return this.leads.length || this.progress.leadsFound || 0;
    },

    /* ── Lifecycle ────────────────────────────────────────────────── */

    async init() {
      Alpine.store("ipc", { send: this._safeIpc.bind(this) });
      Alpine.store("app", this);

      window.addEventListener("captcha-detected", (e) => {
        this.captchaEvent = e.detail;
      });

      /* Keyboard shortcut listener */
      this._keyHandler = (e) => handleKeyboard(e, this.navigateTo.bind(this));
      document.addEventListener("keydown", this._keyHandler);

      /* Probe the sidecar */
      try {
        await ipc("ping");
        this.hasSidecar = true;
        this.addActivity("system", "Sidecar connected");
        console.log("[LeadGen] Sidecar connection OK");
      } catch {
        this.hasSidecar = false;
        console.warn("[LeadGen] Sidecar not reachable — dev mock active");
      }

      /* First-run detection */
      if (this.hasSidecar) {
        await this._checkFirstRun();
      } else {
        this.showSetupHint = true;
      }

      /* Poll for sidecar events */
      if (IS_TAURI) {
        const pollEvents = async () => {
          try {
            const events = await ipc("sidecar.poll_events", {});
            for (const evt of (events || [])) {
              if (evt.event === "captcha_detected") {
                window.dispatchEvent(
                  new CustomEvent("captcha-detected", { detail: evt }),
                );
              }
            }
          } catch {
            /* polling not supported yet */
          }
        };
        this._pollTimer = setInterval(pollEvents, 2000);
      }
    },

    destroy() {
      if (this._pollTimer) {
        clearInterval(this._pollTimer);
        this._pollTimer = null;
      }
      if (this._keyHandler) {
        document.removeEventListener("keydown", this._keyHandler);
        this._keyHandler = null;
      }
    },

    /* ── First-run & health checks ────────────────────────────────── */

    async _checkFirstRun() {
      try {
        const county = await ipc("settings.get", { key: "target_county" });
        if (!county || !county.value) {
          this.showSetupHint = true;
        }

        const providers = await ipc("llm_settings.get", {});
        this.hasLLMProvider = Array.isArray(providers) &&
          providers.some((p) => p.api_key !== "****" && p.api_key !== "");
      } catch {
        this.showSetupHint = true;
      }
    },

    dismissHint() {
      this.showSetupHint = false;
    },

    /* ── Notification system ──────────────────────────────────────── */

    addNotification(type, title, detail, action) {
      const id = nextNotifId();
      this.notifications.push({
        id,
        type: type || "info",
        title,
        detail: detail || "",
        action: action || null,
        timestamp: new Date().toLocaleTimeString(),
      });

      /* Auto-dismiss after 6 seconds */
      setTimeout(() => {
        this.dismissNotification(id);
      }, 6000);

      /* Keep at most 6 visible */
      if (this.notifications.length > 6) {
        this.notifications.shift();
      }
    },

    notifySuccess(title, detail) {
      this.addNotification("success", title, detail);
    },

    notifyError(title, detail) {
      this.addNotification("error", title, detail);
    },

    notifyWarning(title, detail) {
      this.addNotification("warning", title, detail);
    },

    notifyInfo(title, detail) {
      this.addNotification("info", title, detail);
    },

    dismissNotification(id) {
      const idx = this.notifications.findIndex((n) => n.id === id);
      if (idx !== -1) {
        this.notifications.splice(idx, 1);
      }
    },

    /* ── Activity feed ────────────────────────────────────────────── */

    addActivity(action, detail) {
      this.activityFeed.push({
        id: nextNotifId(),
        action,
        detail: detail || "",
        timestamp: new Date().toLocaleTimeString(),
        iso: new Date().toISOString(),
      });
      /* Keep last 100 entries */
      if (this.activityFeed.length > 100) {
        this.activityFeed.splice(0, this.activityFeed.length - 100);
      }
    },

    /* ── Safe IPC with error handling ─────────────────────────────── */

    async _safeIpc(method, params = {}) {
      try {
        return await ipc(method, params);
      } catch (err) {
        this.showError(err);
        throw err;
      }
    },

    showError(err) {
      const formatted = formatError(err);
      this.notifyError(formatted.title, formatted.detail);
    },

    /* ── Sidebar ──────────────────────────────────────────────────── */

    toggleSidebar() {
      this.sidebarOpen = !this.sidebarOpen;
    },

    closeSidebar() {
      this.sidebarOpen = false;
    },

    /* ── Navigation ───────────────────────────────────────────────── */

    navigateTo(view) {
      this.currentView = view;
      this.closeSidebar();

      if (view === "settings") {
        this._checkFirstRun();
      }
    },

    viewDashboard() { this.navigateTo("dashboard"); },
    viewLeads() { this.navigateTo("leads"); },
    viewSettings() { this.navigateTo("settings"); },

    /* ── Actions ──────────────────────────────────────────────────── */

    async startSearch() {
      this.isProcessing = true;
      this.isLoading = true;
      this.status.discovery = "running";
      this.addActivity("search", `Starting search in target area…`);
    },

    stopSearch() {
      this.isProcessing = false;
      this.isLoading = false;
      this.status.discovery = "idle";
      this.addActivity("stop", "Search stopped by user");
    },

    async resumeAutomation() {
      this.captchaEvent = null;
      console.log("[LeadGen] Resuming automation…");
    },

    skipLead() {
      this.captchaEvent = null;
      console.log("[LeadGen] Skipping current lead.");
    },
  };
}


/* ── Register with Alpine ─────────────────────────────────────────── */

Alpine.data("dashboard", dashboard);
Alpine.data("leadTable", leadTable);
Alpine.data("captchaModal", captchaModal);
Alpine.data("settingsPanel", settingsPanel);
Alpine.data("app", app);

Alpine.store("ipc", { send: ipc });
Alpine.store("app", {
  currentView: "dashboard",
  isProcessing: false,
  captchaEvent: null,
});

Alpine.start();
