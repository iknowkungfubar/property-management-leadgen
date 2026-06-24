/**
 * CaptchaModal component — handles CAPTCHA detection events from the sidecar.
 *
 * Renders a modal overlay when a CAPTCHA challenge is detected and provides
 * handlers for the user to skip the lead or resume automation after solving.
 */
export function captchaModal() {
  return {
    // ── State ──────────────────────────────────────────────────────
    target: "",
    stateId: "",
    showCaptcha: false,

    // ── Lifecycle ──────────────────────────────────────────────────
    init() {
      // Listen for CAPTCHA events dispatched by the sidecar IPC bridge
      window.addEventListener("captcha-detected", (e) => {
        this.target = e.detail?.target ?? "Unknown";
        this.stateId = e.detail?.state_id ?? "";
        this.showCaptcha = true;
      });
    },

    // ── Actions ────────────────────────────────────────────────────
    async resumeAutomation() {
      Alpine.store("app").captchaEvent = null;
      this.showCaptcha = false;
      console.log("[CaptchaModal] Resuming from state", this.stateId);
      // TODO: signal sidecar to restore browser session and continue
    },

    skipLead() {
      Alpine.store("app").captchaEvent = null;
      this.showCaptcha = false;
      console.log("[CaptchaModal] Skipping lead");
    },

    // ── Template ─────────────────────────────────────────────────
    template: `<div
  x-show="showCaptcha"
  class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
  style="display: none;"
>
  <div class="bg-slate-800 border border-slate-700 rounded-xl shadow-2xl max-w-lg w-full mx-4 p-6">
    <h2 class="text-xl font-semibold text-amber-400 mb-2">&#9888; CAPTCHA Detected</h2>
    <p class="text-sm text-slate-300 mb-4">
      An automation check was triggered on
      <span x-text="target" class="font-mono text-white"></span>.
    </p>
    <div class="bg-slate-900 rounded-lg p-4 mb-4 text-xs text-slate-400 font-mono">
      <p><span class="text-slate-500">state_id:</span> <span x-text="stateId"></span></p>
      <p class="mt-1 text-slate-500">Open the headed browser, resolve the challenge, then resume.</p>
    </div>
    <div class="flex gap-3 justify-end">
      <button
        @click="skipLead()"
        class="px-4 py-2 rounded-lg bg-slate-700 hover:bg-slate-600 text-sm transition-colors"
      >
        Skip Lead
      </button>
      <button
        @click="resumeAutomation()"
        class="px-4 py-2 rounded-lg bg-brand-600 hover:bg-brand-500 text-sm font-medium transition-colors"
      >
        Resume Automation
      </button>
    </div>
  </div>
</div>`,
  };
}
