/**
 * Dashboard component — KPI cards, agent status, search controls,
 * activity feed, loading skeletons, and responsive layout.
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
        // dev fallback — defaults
      }
    },

    // ── Helpers ────────────────────────────────────────────────────
    app() {
      return Alpine.store("app");
    },

    // ── Actions ────────────────────────────────────────────────────
    async startSearch() {
      const a = this.app();
      a.startSearch();
      a.addActivity("search", `Starting search in ${this.targetCounty}…`);

      // Simulated async search
      setTimeout(() => {
        a.progress.leadsFound = 47;
        a.progress.leadsUnmasked = 23;
        a.progress.leadsScored = 18;
        a.status.discovery = "done";
        a.status.unmasking = "done";
        a.status.intelligence = "done";
        a.isProcessing = false;
        a.isLoading = false;
        a.addActivity("import", "47 leads imported and normalized");
        a.addActivity("search", "Search complete — 18 priority leads scored");
        a.notifySuccess("Search Complete", `Found ${a.progress.leadsFound} leads in ${this.targetCounty}.`);
      }, 3000);
    },

    stopSearch() {
      const a = this.app();
      a.stopSearch();
    },

    // ── Template ──────────────────────────────────────────────────
    template: `
<!-- ── Dashboard ───────────────────────────────────────────────── -->
<div class="space-y-6">

  <!-- Header -->
  <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
    <div>
      <h2 class="text-2xl font-bold text-white">Dashboard</h2>
      <p class="text-sm text-slate-400 mt-1">
        Target: <span class="text-white font-medium" x-text="targetCounty"></span>
      </p>
    </div>
    <div class="flex items-center gap-2 text-xs text-slate-500">
      <span class="status-dot" :class="'status-dot-' + (app().isProcessing ? 'running' : 'idle')"></span>
      <span x-text="app().isProcessing ? 'Processing…' : 'Idle'"></span>
    </div>
  </div>

  <!-- ── KPI Cards ─────────────────────────────────────────────── -->
  <template x-if="app().isLoading">
    <!-- Skeleton state -->
    <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
      <template x-for="i in 4" :key="i">
        <div class="card-accent bg-slate-800 border border-slate-700 rounded-xl p-4">
          <div class="skeleton h-10 w-10 rounded-lg mb-3"></div>
          <div class="skeleton h-5 w-16 mb-2"></div>
          <div class="skeleton h-3 w-24"></div>
        </div>
      </template>
    </div>
  </template>
  <template x-if="!app().isLoading">
    <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
      <!-- Leads Found -->
      <div class="card-accent bg-slate-800 border border-slate-700 rounded-xl p-4">
        <div class="flex items-center gap-3 mb-3">
          <div class="kpi-icon bg-brand-500/10 text-brand-400">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/>
            </svg>
          </div>
          <div class="text-2xl font-bold text-white" x-text="app().progress.leadsFound"></div>
        </div>
        <p class="text-xs text-slate-400">Leads Found</p>
      </div>

      <!-- Unmasked -->
      <div class="card-accent bg-slate-800 border border-slate-700 rounded-xl p-4">
        <div class="flex items-center gap-3 mb-3">
          <div class="kpi-icon bg-sky-500/10 text-sky-400">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z"/>
            </svg>
          </div>
          <div class="text-2xl font-bold text-white" x-text="app().progress.leadsUnmasked"></div>
        </div>
        <p class="text-xs text-slate-400">Unmasked</p>
      </div>

      <!-- Scored -->
      <div class="card-accent bg-slate-800 border border-slate-700 rounded-xl p-4">
        <div class="flex items-center gap-3 mb-3">
          <div class="kpi-icon bg-amber-500/10 text-amber-400">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/>
            </svg>
          </div>
          <div class="text-2xl font-bold text-white" x-text="app().progress.leadsScored"></div>
        </div>
        <p class="text-xs text-slate-400">Scored</p>
      </div>

      <!-- Exported -->
      <div class="card-accent bg-slate-800 border border-slate-700 rounded-xl p-4">
        <div class="flex items-center gap-3 mb-3">
          <div class="kpi-icon bg-violet-500/10 text-violet-400">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
            </svg>
          </div>
          <div class="text-2xl font-bold text-white" x-text="app().progress.leadsExported"></div>
        </div>
        <p class="text-xs text-slate-400">Exported</p>
      </div>
    </div>
  </template>

  <!-- ── Agent Status + Controls ─────────────────────────────────── -->
  <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
    <!-- Agent status cards -->
    <div class="lg:col-span-2 grid grid-cols-2 gap-4">
      <!-- Discovery -->
      <div class="bg-slate-800 rounded-xl p-4 border border-slate-700">
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-sm font-medium text-slate-300">Discovery</h3>
          <span class="inline-flex items-center text-xs font-medium">
            <span class="status-dot" :class="'status-dot-' + app().status.discovery"></span>
            <span x-text="app().status.discovery"></span>
          </span>
        </div>
        <p class="text-xs text-slate-500">CSV import &amp; APN normalization</p>
      </div>

      <!-- Entity Unmasking -->
      <div class="bg-slate-800 rounded-xl p-4 border border-slate-700">
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-sm font-medium text-slate-300">Entity Unmasking</h3>
          <span class="inline-flex items-center text-xs font-medium">
            <span class="status-dot" :class="'status-dot-' + app().status.unmasking"></span>
            <span x-text="app().status.unmasking"></span>
          </span>
        </div>
        <p class="text-xs text-slate-500">CA SoS lookup &amp; principal extraction</p>
      </div>

      <!-- Market Intelligence -->
      <div class="bg-slate-800 rounded-xl p-4 border border-slate-700">
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-sm font-medium text-slate-300">Market Intelligence</h3>
          <span class="inline-flex items-center text-xs font-medium">
            <span class="status-dot" :class="'status-dot-' + app().status.intelligence"></span>
            <span x-text="app().status.intelligence"></span>
          </span>
        </div>
        <p class="text-xs text-slate-500">Vacancy risk &amp; priority scoring</p>
      </div>

      <!-- Synthesis -->
      <div class="bg-slate-800 rounded-xl p-4 border border-slate-700">
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-sm font-medium text-slate-300">Synthesis</h3>
          <span class="inline-flex items-center text-xs font-medium">
            <span class="status-dot" :class="'status-dot-' + app().status.synthesis"></span>
            <span x-text="app().status.synthesis"></span>
          </span>
        </div>
        <p class="text-xs text-slate-500">DNC filter &amp; CRM export</p>
      </div>
    </div>

    <!-- Controls & Progress -->
    <div class="bg-slate-800 rounded-xl p-4 border border-slate-700 space-y-4">
      <h3 class="text-sm font-medium text-slate-300">Controls</h3>
      <div class="flex flex-wrap gap-2">
        <button
          @click="startSearch()"
          :disabled="app().isProcessing"
          class="btn-primary text-sm inline-flex items-center gap-2"
        >
          <template x-if="app().isProcessing">
            <svg class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"/>
            </svg>
          </template>
          <span x-text="app().isProcessing ? 'Processing…' : 'Start Search'"></span>
        </button>
        <button
          @click="stopSearch()"
          :disabled="!app().isProcessing"
          class="btn-secondary text-sm"
        >
          Stop
        </button>
      </div>

      <!-- Progress bar -->
      <template x-if="app().isProcessing">
        <div>
          <div class="flex items-center justify-between text-xs text-slate-400 mb-1">
            <span>Search in progress…</span>
            <span x-text="app().progress.leadsFound + ' leads'"></span>
          </div>
          <div class="progress-bar">
            <div class="progress-bar-fill" style="width: 60%"></div>
          </div>
        </div>
      </template>

      <!-- Progress summary -->
      <div class="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
        <span>Found <strong class="text-white" x-text="app().progress.leadsFound"></strong></span>
        <span>Unmasked <strong class="text-white" x-text="app().progress.leadsUnmasked"></strong></span>
        <span>Scored <strong class="text-white" x-text="app().progress.leadsScored"></strong></span>
      </div>
    </div>
  </div>

  <!-- ── Target Area ─────────────────────────────────────────────── -->
  <div class="bg-slate-800 rounded-xl p-4 border border-slate-700">
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
        <input
          type="text"
          x-model="targetZip"
          class="input-field"
          placeholder="e.g. 92626"
        />
      </div>
    </div>
  </div>

  <!-- ── Activity Feed ──────────────────────────────────────────── -->
  <div class="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
    <div class="px-4 py-3 border-b border-slate-700 flex items-center justify-between">
      <h3 class="text-sm font-medium text-slate-300">Activity Feed</h3>
      <template x-if="app().activityFeed.length">
        <span class="text-xs text-slate-500" x-text="app().activityFeed.length + ' events'"></span>
      </template>
    </div>
    <div class="divide-y divide-slate-700/50" style="max-height: 320px; overflow-y: auto;">
      <template x-for="evt in app().sortedActivity()" :key="evt.id">
        <div class="px-4 py-2.5 flex items-start gap-3 hover:bg-slate-700/20 transition-colors">
          <!-- Search icon -->
          <template x-if="evt.action === 'search'">
            <svg class="w-4 h-4 text-sky-400 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
            </svg>
          </template>
          <!-- Stop icon -->
          <template x-if="evt.action === 'stop'">
            <svg class="w-4 h-4 text-red-400 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </template>
          <!-- Import/download icon -->
          <template x-if="evt.action === 'import'">
            <svg class="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2M7 10l5 5 5-5M12 15V3"/>
            </svg>
          </template>
          <!-- Export icon -->
          <template x-if="evt.action === 'export'">
            <svg class="w-4 h-4 text-violet-400 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19V5m-7 7l7 7 7-7"/>
            </svg>
          </template>
          <!-- System/check icon -->
          <template x-if="evt.action === 'system'">
            <svg class="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
            </svg>
          </template>
          <!-- Default icon for unknown actions -->
          <template x-if="!['search','stop','import','export','system'].includes(evt.action)">
            <svg class="w-4 h-4 text-slate-500 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
            </svg>
          </template>
          <div class="flex-1 min-w-0">
            <p class="text-xs text-slate-300 truncate" x-text="evt.detail"></p>
            <p class="text-[10px] text-slate-600 mt-0.5" x-text="evt.timestamp"></p>
          </div>
        </div>
      </template>
      <template x-if="!app().activityFeed.length">
        <p class="px-4 py-6 text-center text-xs text-slate-500">
          No activity yet. Start a search to see events appear here.
        </p>
      </template>
    </div>
  </div>
</div>`,
  };
}
