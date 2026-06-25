/**
 * Main Alpine.js application.
 *
 * Provides the top-level `app()` component with routing, IPC helpers,
 * error handling, first-run detection, and shared state.
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
  return ERROR_MESSAGES[code] || { title: "Error", detail: err.message || "Unknown error", action: null };
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
    notification: null,
    showSetupHint: false,
    hasLLMProvider: false,
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
    },

    // ── Lifecycle ──────────────────────────────────────────────────
    async init() {
      Alpine.store("ipc", { send: this._safeIpc.bind(this) });
      Alpine.store("app", this);

      window.addEventListener("captcha-detected", (e) => {
        this.captchaEvent = e.detail;
      });

      // Probe the sidecar
      try {
        await ipc("ping");
        this.hasSidecar = true;
        console.log("[LeadGen] Sidecar connection OK");
      } catch {
        this.hasSidecar = false;
        console.warn("[LeadGen] Sidecar not reachable — dev mock active");
      }

      // First-run detection: check if settings exist
      if (this.hasSidecar) {
        await this._checkFirstRun();
      } else {
        this.showSetupHint = true;
      }

      // Poll for sidecar events
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
            // Polling not supported yet
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
    },

    // ── First-run & health checks ──────────────────────────────────

    async _checkFirstRun() {
      try {
        const county = await ipc("settings.get", { key: "target_county" });
        if (!county || !county.value) {
          this.showSetupHint = true;
        }

        // Check if any LLM provider is configured
        const providers = await ipc("llm_settings.get", {});
        this.hasLLMProvider = Array.isArray(providers) && providers.some(p => p.api_key !== "****" && p.api_key !== "");
      } catch {
        this.showSetupHint = true;
      }
    },

    dismissHint() {
      this.showSetupHint = false;
    },

    // ── Safe IPC with error handling ───────────────────────────────

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
      this.notification = {
        ...formatted,
        id: Date.now(),
        timestamp: new Date().toLocaleTimeString(),
      };
      // Auto-dismiss after 8 seconds
      setTimeout(() => {
        if (this.notification && this.notification.id === formatted.id) {
          this.notification = null;
        }
      }, 8000);
    },

    dismissNotification() {
      this.notification = null;
    },

    navigateTo(view) {
      this.currentView = view;
      if (view === "settings") {
        // Re-check LLM status when opening settings
        this._checkFirstRun();
      }
    },

    // ── Actions ────────────────────────────────────────────────────
    async startSearch() {
      this.isProcessing = true;
      this.status.discovery = "running";
    },

    stopSearch() {
      this.isProcessing = false;
      this.status.discovery = "idle";
    },

    async resumeAutomation() {
      this.captchaEvent = null;
      console.log("[LeadGen] Resuming automation…");
    },

    skipLead() {
      this.captchaEvent = null;
      console.log("[LeadGen] Skipping current lead.");
    },

    // ── Navigation ─────────────────────────────────────────────────
    viewDashboard() { this.navigateTo("dashboard"); },
    viewLeads() { this.navigateTo("leads"); },
    viewSettings() { this.navigateTo("settings"); },
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
