/**
 * Dashboard component — agent status, search controls, progress summary.
 */
export function dashboard() {
  return {
    // ── State ──────────────────────────────────────────────────────
    targetCounty: "Orange County",
    targetZip: "",

    // ── Lifecycle ──────────────────────────────────────────────────
    init() {
      this.loadSettings();
    },

    async loadSettings() {
      try {
        const ipc = Alpine.store("ipc");
        const { value: county } = await ipc.send("settings.get", {
          key: "target_county",
        });
        if (county) this.targetCounty = county;
      } catch {
        // dev fallback — use defaults
      }
    },

    // ── Actions ────────────────────────────────────────────────────
    async startSearch() {
      const app = Alpine.store("app");
      app.isProcessing = true;
      app.status.discovery = "running";

      console.log("[Dashboard] Starting search for", this.targetCounty);

      setTimeout(() => {
        app.progress.leadsFound = 47;
        app.progress.leadsUnmasked = 23;
        app.progress.leadsScored = 18;
        app.status.discovery = "idle";
        app.status.unmasking = "idle";
        app.status.intelligence = "idle";
        app.isProcessing = false;
      }, 2000);
    },

    stopSearch() {
      Alpine.store("app").stopSearch();
    },

    // ── Template ──────────────────────────────────────────────────
    template: `
<div class="space-y-6">
  <div>
    <h2 class="text-2xl font-bold">Dashboard</h2>
    <p class="text-sm text-slate-400 mt-1">
      Target: <span class="text-white" x-text="targetCounty"></span>
    </p>
  </div>
  <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
    <div class="bg-slate-800 rounded-xl p-4 border border-slate-700">
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-sm font-medium text-slate-300">Discovery</h3>
        <span :class="Alpine.store('app').status.discovery === 'running' ? 'bg-yellow-500/10 text-yellow-400' : 'bg-emerald-500/10 text-emerald-400'" class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border" x-text="Alpine.store('app').status.discovery"></span>
      </div>
      <p class="text-xs text-slate-500">CSV import &amp; APN normalization</p>
    </div>
    <div class="bg-slate-800 rounded-xl p-4 border border-slate-700">
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-sm font-medium text-slate-300">Entity Unmasking</h3>
        <span :class="Alpine.store('app').status.unmasking === 'running' ? 'bg-yellow-500/10 text-yellow-400' : 'bg-emerald-500/10 text-emerald-400'" class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border" x-text="Alpine.store('app').status.unmasking"></span>
      </div>
      <p class="text-xs text-slate-500">CA SoS lookup &amp; principal extraction</p>
    </div>
    <div class="bg-slate-800 rounded-xl p-4 border border-slate-700">
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-sm font-medium text-slate-300">Market Intelligence</h3>
        <span :class="Alpine.store('app').status.intelligence === 'running' ? 'bg-yellow-500/10 text-yellow-400' : 'bg-emerald-500/10 text-emerald-400'" class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border" x-text="Alpine.store('app').status.intelligence"></span>
      </div>
      <p class="text-xs text-slate-500">Vacancy risk &amp; priority scoring</p>
    </div>
    <div class="bg-slate-800 rounded-xl p-4 border border-slate-700">
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-sm font-medium text-slate-300">Synthesis</h3>
        <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border bg-emerald-500/10 text-emerald-400">idle</span>
      </div>
      <p class="text-xs text-slate-500">DNC filter &amp; CRM export</p>
    </div>
  </div>
  <div class="bg-slate-800 rounded-xl p-4 border border-slate-700 flex items-center gap-4">
    <button @click="startSearch()" :disabled="Alpine.store('app').isProcessing" class="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-brand-600 hover:bg-brand-500 text-sm font-medium transition-colors disabled:opacity-50">
      <span x-text="Alpine.store('app').isProcessing ? 'Processing\u2026' : 'Start Search'"></span>
    </button>
    <button @click="stopSearch()" :disabled="!Alpine.store('app').isProcessing" class="px-4 py-2 rounded-lg bg-slate-700 hover:bg-slate-600 text-sm transition-colors disabled:opacity-50">Stop</button>
    <span class="text-xs text-slate-500 ml-auto">Found <strong x-text="Alpine.store('app').progress.leadsFound"></strong> &middot; Unmasked <strong x-text="Alpine.store('app').progress.leadsUnmasked"></strong> &middot; Scored <strong x-text="Alpine.store('app').progress.leadsScored"></strong></span>
  </div>
  <div class="bg-slate-800 rounded-xl p-4 border border-slate-700">
    <h3 class="text-sm font-medium text-slate-300 mb-3">Target Area</h3>
    <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
      <div>
        <label class="block text-xs text-slate-400 mb-1">County</label>
        <select x-model="targetCounty" class="w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-white">
          <option>Orange County</option>
          <option>Los Angeles County</option>
        </select>
      </div>
      <div>
        <label class="block text-xs text-slate-400 mb-1">ZIP Code (optional filter)</label>
        <input type="text" x-model="targetZip" class="w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-white" placeholder="e.g. 92626" />
      </div>
    </div>
  </div>
</div>`,
  };
}
