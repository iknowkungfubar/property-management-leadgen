/**
 * CaptchaModal component — handles CAPTCHA detection events from the sidecar.
 *
 * The overlay is rendered in ``index.html``; this component exposes the
 * callback handlers shared by the main app.
 */
export function captchaModal() {
  return {
    // ── State ──────────────────────────────────────────────────────
    target: "",
    stateId: "",

    // ── Lifecycle ──────────────────────────────────────────────────
    init() {
      // Listen for CAPTCHA events dispatched by the sidecar IPC bridge
      window.addEventListener("captcha-detected", (e) => {
        this.target = e.detail?.target ?? "Unknown";
        this.stateId = e.detail?.state_id ?? "";
      });
    },

    // ── Actions ────────────────────────────────────────────────────
    async resumeAutomation() {
      const app = Alpine.store("app");
      app.captchaEvent = null;
      console.log("[CaptchaModal] Resuming from state", this.stateId);
      // TODO: signal sidecar to restore browser session and continue
    },

    skipLead() {
      const app = Alpine.store("app");
      app.captchaEvent = null;
      console.log("[CaptchaModal] Skipping lead");
    },
  };
}
