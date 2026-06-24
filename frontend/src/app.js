/**
 * Main Alpine.js application.
 *
 * Provides the top-level `app()` component with routing, IPC helpers,
 * and shared state used by all sub-components.
 */

import Alpine from "alpinejs";
import { dashboard } from "./components/Dashboard.js";
import { leadTable } from "./components/LeadTable.js";
import { captchaModal } from "./components/CaptchaModal.js";
import { settingsPanel } from "./components/Settings.js";

/* ── IPC helpers ──────────────────────────────────────────────────── */

/**
 * True when running inside Tauri.  Determines IPC transport.
 * Uses a global set by the Tauri Polyfill or process.env.
 */
const IS_TAURI = typeof window !== "undefined" && window.__TAURI__;

/**
 * Send a JSON-RPC-style command to the Python sidecar and return the result.
 *
 * Inside Tauri this calls ``invoke("sidecar_command", { cmd })``.
 * During dev (no Tauri) it POSTs to a thin dev-proxy or falls back to
 * a mock delay.
 *
 * @param {string} method  IPC method name (e.g. ``"discovery.import_csv"``)
 * @param {object} params  Method parameters
 * @returns {Promise<any>}
 */
async function ipc(method, params = {}) {
  const payload = { method, params };

  if (IS_TAURI) {
    // In production Tauri forwards this to the sidecar via stdin/stdout.
    // The invoke call bridges through the Tauri Rust layer.
    const { invoke } = window.__TAURI__.core;
    return invoke("sidecar_command", { cmd: payload });
  }

  // Dev fallback (no Tauri): send to a local dev-proxy or simulate
  try {
    const resp = await fetch("http://localhost:1421/ipc", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) throw new Error(`IPC proxy returned ${resp.status}`);
    const data = await resp.json();
    if (data.error) throw new Error(data.error.message);
    return data.result;
  } catch {
    // No proxy running — return mock data for UI development
    return mockIpc(method, params);
  }
}

/**
 * Fallback mock responses so the frontend is usable without the sidecar.
 */
function mockIpc(method, _params) {
  switch (method) {
    case "ping":
      return { pong: true };
    case "settings.get":
      return { value: null };
    case "discovery.import_csv":
      return { imported: 47 };
    case "sidecar.poll_events":
      return [];
    default:
      return {};
  }
}

/* ── Main Alpine component ────────────────────────────────────────── */

function app() {
  return {
    // ── State ──────────────────────────────────────────────────────
    currentView: "dashboard",
    leads: [],
    isProcessing: false,
    captchaEvent: null,
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
      Alpine.store("ipc", { send: ipc });
      Alpine.store("app", this);

      // Register global event listener for CAPTCHA events from the sidecar
      window.addEventListener("captcha-detected", (e) => {
        this.captchaEvent = e.detail;
      });

      // Probe the sidecar
      try {
        await ipc("ping");
        console.log("[LeadGen] Sidecar connection OK");
      } catch {
        console.warn("[LeadGen] Sidecar not reachable — dev mock active");
      }

      // Start polling for sidecar events (e.g. captcha detection).
      // This runs every 2 seconds and dispatches captured events as
      // DOM custom events so the existing listeners fire.
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
            // Sidecar might not support polling yet
          }
        };
        setInterval(pollEvents, 2000);
      }
    },

    // ── Actions ────────────────────────────────────────────────────
    async startSearch() {
      this.isProcessing = true;
      this.status.discovery = "running";
      // The actual pipeline is triggered by the Dashboard component
    },

    stopSearch() {
      this.isProcessing = false;
      this.status.discovery = "idle";
    },

    async resumeAutomation() {
      this.captchaEvent = null;
      // TODO: signal the sidecar to resume from the saved session
      console.log("[LeadGen] Resuming automation…");
    },

    skipLead() {
      this.captchaEvent = null;
      console.log("[LeadGen] Skipping current lead.");
    },

    // ── Navigation ─────────────────────────────────────────────────
    viewDashboard() {
      this.currentView = "dashboard";
    },
    viewLeads() {
      this.currentView = "leads";
    },
    viewSettings() {
      this.currentView = "settings";
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
