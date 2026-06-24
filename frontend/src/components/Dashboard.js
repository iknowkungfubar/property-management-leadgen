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
      // Pull persisted settings if available
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

      // TODO: trigger the full pipeline asynchronously
      console.log("[Dashboard] Starting search for", this.targetCounty);

      // Simulate progress updates
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
  };
}

/* ── template ─────────────────────────────────────────────────────── */
export const template = `
<div class="space-y-6">
  <!-- Header -->
  <div>
    <h2 class="text-2xl font-bold">Dashboard</h2>
    <p class="text-sm text-slate-400 mt-1">
      Target: <span class="text-white" x-text="targetCounty"></span>
    </p>
  </div>

  <!-- Agent status cards -->
  <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
    <!-- Discovery -->
    <div class="card">
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-sm font-medium text-slate-300">Discovery</h3>
        <span :class="Alpine.store('app').status.discovery === 'running' ? 'badge-yellow' : 'badge-green'"
              x-text="Alpine.store('app').status.discovery"></span>
      </div>
      <p class="text-xs text-slate-500">CSV import & APN normalization</p>
    </div>

    <!-- Entity Unmasking -->
    <div class="card">
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-sm font-medium text-slate-300">Entity Unmasking</h3>
        <span :class="Alpine.store('app').status.unmasking === 'running' ? 'badge-yellow' : 'badge-green'"
              x-text="Alpine.store('app').status.unmasking"></span>
      </div>
      <p class="text-xs text-slate-500">CA SoS lookup & principal extraction</p>
    </div>

    <!-- Market Intelligence -->
    <div class="card">
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-sm font-medium text-slate-300">Market Intelligence</h3>
        <span :class="Alpine.store('app').status.intelligence === 'running' ? 'badge-yellow' : 'badge-green'"
              x-text="Alpine.store('app').status.intelligence"></span>
      </div>
      <p class="text-xs text-slate-500">Vacancy risk & priority scoring</p>
    </div>

    <!-- Output Synthesis -->
    <div class="card">
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-sm font-medium text-slate-300">Synthesis</h3>
        <span class="badge-green" x-text="'idle'"></span>
      </div>
      <p class="text-xs text-slate-500">DNC filter & CRM export</p>
    </div>
  </div>

  <!-- Controls -->
  <div class="card flex items-center gap-4">
    <button
      @click="startSearch()"
      :disabled="Alpine.store('app').isProcessing"
      class="btn-primary flex items-center gap-2"
    >
      <svg x-show="!Alpine.store('app').isProcessing" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"/>
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
      </svg>
      <svg x-show="Alpine.store('app').isProcessing" class="w-4 h-4 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
      </svg>
      <span x-text="Alpine.store('app').isProcessing ? 'Processing…' : 'Start Search'"></span>
    </button>
    <button
      @click="stopSearch()"
      :disabled="!Alpine.store('app').isProcessing"
      class="btn-secondary"
    >Stop</button>
    <span class="text-xs text-slate-500 ml-auto">
      Found <strong x-text="Alpine.store('app').progress.leadsFound"></strong> ·
      Unmasked <strong x-text="Alpine.store('app').progress.leadsUnmasked"></strong> ·
      Scored <strong x-text="Alpine.store('app').progress.leadsScored"></strong>
    </span>
  </div>

  <!-- Configuration -->
  <div class="card">
    <h3 class="text-sm font-medium text-slate-300 mb-3">Target Area</h3>
    <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
      <div>
        <label class="block text-xs text-slate-400 mb-1">County</label>
        <select x-model="targetCounty" class="input-field">
          <option>Orange County</option>
          <option>Los Angeles County</option>
        </select>
      </div>
      <div>
        <label class="block text-xs text-slate-400 mb-1">ZIP Code (optional filter)</label>
        <input type="text" x-model="targetZip" class="input-field" placeholder="e.g. 92626" />
      </div>
    </div>
  </div>
</div>`;
