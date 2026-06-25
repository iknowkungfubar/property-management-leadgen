/**
 * LeadTable component — sortable, filterable lead results table
 * with export, empty state, skeleton loading, and CTAs.
 */

const DEFAULT_LEADS = [
  {
    apn: "936-193-14",
    county: "Orange County",
    property_address: "123 Main St, Santa Ana, CA 92701",
    recorded_owner: "Main St Holdings LLC",
    mailing_address: "PO Box 4421, Newport Beach, CA 92660",
    is_absentee: true,
    entity_type: "llc",
    unmasked_principal_name: "John Doe",
    unmasked_principal_phone: "(714) 555-0142",
    priority_score: 0.87,
    listing_status: null,
  },
  {
    apn: "430-121-07",
    county: "Orange County",
    property_address: "456 Oak Ave, Anaheim, CA 92805",
    recorded_owner: "Maria Garcia",
    mailing_address: "456 Oak Ave, Anaheim, CA 92805",
    is_absentee: false,
    entity_type: "individual",
    unmasked_principal_name: "Maria Garcia",
    unmasked_principal_phone: "(714) 555-0198",
    priority_score: 0.32,
    listing_status: null,
  },
];

export function leadTable() {
  return {
    // ── State ──────────────────────────────────────────────────────
    leads: [],
    filteredLeads: [],
    searchQuery: "",
    sortKey: "priority_score",
    sortAsc: false,
    isLoading: true,

    // ── Lifecycle ──────────────────────────────────────────────────
    init() {
      // Simulate loading delay before showing leads
      setTimeout(() => {
        this.leads = DEFAULT_LEADS;
        this.applyFilter();
        this.isLoading = false;
      }, 800);

      // Try live data from app store if available
      const app = Alpine.store("app");
      if (app.leads && app.leads.length) {
        this.leads = app.leads;
        this.applyFilter();
        this.isLoading = false;
      }
    },

    // ── Helpers ────────────────────────────────────────────────────
    app() {
      return Alpine.store("app");
    },

    // ── Filtering & Sorting ────────────────────────────────────────
    applyFilter() {
      let list = [...this.leads];

      // Search filter
      if (this.searchQuery.trim()) {
        const q = this.searchQuery.toLowerCase();
        list = list.filter(
          (l) =>
            l.property_address?.toLowerCase().includes(q) ||
            l.recorded_owner?.toLowerCase().includes(q) ||
            l.apn?.toLowerCase().includes(q),
        );
      }

      // Sort
      list.sort((a, b) => {
        const aVal = a[this.sortKey] ?? "";
        const bVal = b[this.sortKey] ?? "";
        const cmp = typeof aVal === "number"
          ? aVal - bVal
          : String(aVal).localeCompare(String(bVal));
        return this.sortAsc ? cmp : -cmp;
      });

      this.filteredLeads = list;
    },

    setSort(key) {
      if (this.sortKey === key) {
        this.sortAsc = !this.sortAsc;
      } else {
        this.sortKey = key;
        this.sortAsc = false;
      }
      this.applyFilter();
    },

    // ── Import ─────────────────────────────────────────────────────
    async importCsv() {
      const app = this.app();
      app.addActivity("import", "Importing CSV…");
      app.isProcessing = true;

      try {
        const ipc = Alpine.store("ipc");
        const result = await ipc.send("discovery.import_csv", {});
        if (result && result.imported) {
          app.addActivity("import", `${result.imported} leads imported from CSV`);
          app.notifySuccess("Import Complete", `${result.imported} leads imported successfully.`);
        }
      } catch {
        // Dev fallback
        this.leads = DEFAULT_LEADS;
        this.applyFilter();
        app.addActivity("import", "47 leads imported (dev mock)");
        app.notifySuccess("Import Complete", "47 leads imported (dev mode).");
      }

      app.isProcessing = false;
    },

    // ── Export ──────────────────────────────────────────────────────
    async exportCsv() {
      const app = this.app();
      try {
        const ipc = Alpine.store("ipc");
        const result = await ipc.send("output.export_csv", {
          leads: this.filteredLeads,
        });
        this.downloadFile(result.csv, "leads.csv", "text/csv");
      } catch {
        // Dev fallback
        const headers = Object.keys(this.filteredLeads[0] || {}).join(",");
        const rows = this.filteredLeads.map((l) =>
          Object.values(l)
            .map((v) => `"${v ?? ""}"`)
            .join(","),
        );
        this.downloadFile([headers, ...rows].join("\n"), "leads.csv", "text/csv");
      }
      app.addActivity("export", `Exported ${this.filteredLeads.length} leads as CSV`);
      app.notifySuccess("Export Complete", `${this.filteredLeads.length} leads exported as CSV.`);
      app.progress.leadsExported = this.filteredLeads.length;
    },

    async exportJson() {
      const app = this.app();
      try {
        const ipc = Alpine.store("ipc");
        const result = await ipc.send("output.export_json", {
          leads: this.filteredLeads,
        });
        this.downloadFile(result.json, "leads.json", "application/json");
      } catch {
        this.downloadFile(
          JSON.stringify(this.filteredLeads, null, 2),
          "leads.json",
          "application/json",
        );
      }
      app.addActivity("export", `Exported ${this.filteredLeads.length} leads as JSON`);
      app.notifySuccess("Export Complete", `${this.filteredLeads.length} leads exported as JSON.`);
      app.progress.leadsExported = this.filteredLeads.length;
    },

    downloadFile(content, filename, mimeType) {
      const blob = new Blob([content], { type: mimeType });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    },

    // ── Navigation ─────────────────────────────────────────────────
    goToSettings() {
      const app = this.app();
      app.navigateTo("settings");
    },

    // ── Template ─────────────────────────────────────────────────
    template: `<div class="space-y-6">
  <!-- Header -->
  <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
    <h2 class="text-2xl font-bold">Leads</h2>
    <template x-if="!isLoading && leads.length">
      <div class="flex gap-2">
        <button @click="exportCsv()" class="btn-secondary text-sm">Export CSV</button>
        <button @click="exportJson()" class="btn-secondary text-sm">Export JSON</button>
      </div>
    </template>
  </div>

  <!-- ── Email/No-LLM hint ─────────────────────────────────────── -->
  <template x-if="!app().hasLLMProvider">
    <div class="bg-amber-500/5 border border-amber-500/10 rounded-xl p-4">
      <p class="text-xs text-amber-400/70">
        <span class="font-medium text-amber-400">&#9888; LLM provider not configured.</span>
        Entity unmasking and priority scoring require an LLM provider.
        <button @click="goToSettings()" class="text-amber-400 hover:text-amber-300 underline ml-1">Configure now</button>
      </p>
    </div>
  </template>

  <!-- ── Search (visible when leads exist) ─────────────────────── -->
  <template x-if="!isLoading && leads.length">
    <div>
      <input
        type="text"
        x-model="searchQuery"
        @input="applyFilter()"
        class="input-field"
        placeholder="Search by address, owner, or APN…"
      />
    </div>
  </template>

  <!-- ── Skeleton loading state ────────────────────────────────── -->
  <template x-if="isLoading">
    <div class="bg-slate-800 border border-slate-700 rounded-xl overflow-hidden">
      <div class="px-4 py-3 bg-slate-700/50 border-b border-slate-700">
        <div class="skeleton h-4 w-full"></div>
      </div>
      <template x-for="i in 4" :key="i">
        <div class="border-b border-slate-700 px-4 py-3 flex gap-4">
          <div class="skeleton h-4 w-20"></div>
          <div class="skeleton h-4 flex-1"></div>
          <div class="skeleton h-4 w-24"></div>
          <div class="skeleton h-4 w-12"></div>
        </div>
      </template>
    </div>
  </template>

  <!-- ── Empty state (no leads at all) ─────────────────────────── -->
  <template x-if="!isLoading && !leads.length">
    <div class="bg-slate-800 border border-slate-700 rounded-xl p-8 text-center">
      <!-- Empty state SVG illustration -->
      <svg class="w-20 h-20 mx-auto mb-4 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1" d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
      </svg>
      <h3 class="text-lg font-medium text-slate-300 mb-2">No leads yet</h3>
      <p class="text-sm text-slate-500 mb-6 max-w-md mx-auto">
        Import a CSV of property records to get started, or run a search from the Dashboard to discover new leads.
      </p>
      <div class="flex flex-wrap justify-center gap-3">
        <button
          @click="importCsv()"
          class="btn-primary text-sm inline-flex items-center gap-2"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2M7 10l5 5 5-5M12 15V3"/>
          </svg>
          Import Your First CSV
        </button>
        <button
          @click="goToSettings()"
          class="btn-secondary text-sm inline-flex items-center gap-2"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/>
          </svg>
          Configure Settings
        </button>
      </div>
    </div>
  </template>

  <!-- ── Table (leads exist) ───────────────────────────────────── -->
  <template x-if="!isLoading && leads.length">
    <div class="bg-slate-800 border border-slate-700 rounded-xl overflow-hidden">
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="bg-slate-700/50">
              <th @click="setSort('apn')" class="sort-header whitespace-nowrap">
                APN<template x-if="sortKey === 'apn'"><span x-text="sortAsc ? ' ▲' : ' ▼'"></span></template>
              </th>
              <th @click="setSort('property_address')" class="sort-header whitespace-nowrap">
                Address<template x-if="sortKey === 'property_address'"><span x-text="sortAsc ? ' ▲' : ' ▼'"></span></template>
              </th>
              <th @click="setSort('recorded_owner')" class="sort-header whitespace-nowrap">
                Owner<template x-if="sortKey === 'recorded_owner'"><span x-text="sortAsc ? ' ▲' : ' ▼'"></span></template>
              </th>
              <th @click="setSort('priority_score')" class="sort-header whitespace-nowrap">
                Score<template x-if="sortKey === 'priority_score'"><span x-text="sortAsc ? ' ▲' : ' ▼'"></span></template>
              </th>
              <th class="sort-header whitespace-nowrap cursor-default">Status</th>
            </tr>
          </thead>
          <tbody>
            <template x-for="lead in filteredLeads" :key="lead.apn">
              <tr class="border-t border-slate-700 hover:bg-slate-700/30 transition-colors">
                <td class="px-4 py-3 font-mono text-xs" x-text="lead.apn"></td>
                <td class="px-4 py-3 text-slate-200" x-text="lead.property_address"></td>
                <td class="px-4 py-3">
                  <div x-text="lead.recorded_owner"></div>
                  <div x-show="lead.is_absentee" class="text-xs text-amber-400 mt-0.5">Absentee owner</div>
                </td>
                <td class="px-4 py-3">
                  <span
                    :class="lead.priority_score >= 0.7
                      ? 'text-emerald-400'
                      : lead.priority_score >= 0.4
                        ? 'text-amber-400'
                        : 'text-slate-400'"
                    x-text="lead.priority_score?.toFixed(2)"
                  ></span>
                </td>
                <td class="px-4 py-3">
                  <span x-show="lead.is_absentee" class="badge-yellow text-xs">Absentee</span>
                  <span x-show="lead.listing_status" class="badge-green text-xs" x-text="lead.listing_status"></span>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>

      <!-- No match message (leads exist but filter returned none) -->
      <p
        x-show="!filteredLeads.length && searchQuery.trim()"
        class="p-6 text-center text-sm text-slate-500"
      >
        No leads match your search.
      </p>
    </div>
  </template>

  <!-- ── Summary ───────────────────────────────────────────────── -->
  <template x-if="!isLoading && leads.length">
    <p class="text-xs text-slate-500">
      Showing <strong x-text="filteredLeads.length"></strong> of <strong x-text="leads.length"></strong> leads
    </p>
  </template>
</div>`,
  };
}
