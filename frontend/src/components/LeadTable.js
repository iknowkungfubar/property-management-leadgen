/**
 * LeadTable component — sortable, filterable lead results table with export.
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

    // ── Lifecycle ──────────────────────────────────────────────────
    init() {
      this.leads = DEFAULT_LEADS;
      this.applyFilter();
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
        const cmp = typeof aVal === "number" ? aVal - bVal : String(aVal).localeCompare(String(bVal));
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

    // ── Export ──────────────────────────────────────────────────────
    async exportCsv() {
      try {
        const ipc = Alpine.store("ipc");
        const result = await ipc.send("output.export_csv", { leads: this.filteredLeads });
        this.downloadFile(result.csv, "leads.csv", "text/csv");
      } catch {
        // Dev fallback: generate CSV locally
        const headers = Object.keys(this.filteredLeads[0] || {}).join(",");
        const rows = this.filteredLeads.map((l) =>
          Object.values(l)
            .map((v) => `"${v ?? ""}"`)
            .join(","),
        );
        this.downloadFile([headers, ...rows].join("\n"), "leads.csv", "text/csv");
      }
    },

    async exportJson() {
      try {
        const ipc = Alpine.store("ipc");
        const result = await ipc.send("output.export_json", { leads: this.filteredLeads });
        this.downloadFile(result.json, "leads.json", "application/json");
      } catch {
        this.downloadFile(
          JSON.stringify(this.filteredLeads, null, 2),
          "leads.json",
          "application/json",
        );
      }
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

    // ── Template ─────────────────────────────────────────────────
    template: `<div class="space-y-6">
  <!-- Header -->
  <div class="flex items-center justify-between">
    <h2 class="text-2xl font-bold">Leads</h2>
    <div class="flex gap-2">
      <button @click="exportCsv()" class="btn-secondary text-sm">Export CSV</button>
      <button @click="exportJson()" class="btn-secondary text-sm">Export JSON</button>
    </div>
  </div>

  <!-- Search -->
  <div>
    <input type="text" x-model="searchQuery" @input="applyFilter()" class="input-field" placeholder="Search by address, owner, or APN…" />
  </div>

  <!-- Table -->
  <div class="card overflow-hidden !p-0">
    <table class="w-full text-sm">
      <thead>
        <tr class="bg-slate-700/50">
          <th @click="setSort('apn')" class="sort-header">
            APN<template x-if="sortKey === 'apn'"><span x-text="sortAsc ? ' ▲' : ' ▼'"></span></template>
          </th>
          <th @click="setSort('property_address')" class="sort-header">
            Address<template x-if="sortKey === 'property_address'"><span x-text="sortAsc ? ' ▲' : ' ▼'"></span></template>
          </th>
          <th @click="setSort('recorded_owner')" class="sort-header">
            Owner<template x-if="sortKey === 'recorded_owner'"><span x-text="sortAsc ? ' ▲' : ' ▼'"></span></template>
          </th>
          <th @click="setSort('priority_score')" class="sort-header">
            Score<template x-if="sortKey === 'priority_score'"><span x-text="sortAsc ? ' ▲' : ' ▼'"></span></template>
          </th>
          <th class="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">Status</th>
        </tr>
      </thead>
      <tbody>
        <template x-for="lead in filteredLeads" :key="lead.apn">
          <tr class="border-t border-slate-700 hover:bg-slate-700/30">
            <td class="px-4 py-3 font-mono text-xs" x-text="lead.apn"></td>
            <td class="px-4 py-3" x-text="lead.property_address"></td>
            <td class="px-4 py-3">
              <div x-text="lead.recorded_owner"></div>
              <div x-show="lead.is_absentee" class="text-xs text-amber-400 mt-0.5">Absentee owner</div>
            </td>
            <td class="px-4 py-3">
              <span :class="lead.priority_score >= 0.7 ? 'text-emerald-400' : lead.priority_score >= 0.4 ? 'text-amber-400' : 'text-slate-400'" x-text="lead.priority_score?.toFixed(2)"></span>
            </td>
            <td class="px-4 py-3">
              <span x-show="lead.is_absentee" class="badge-yellow text-xs">Absentee</span>
              <span x-show="lead.listing_status" class="badge-green text-xs" x-text="lead.listing_status"></span>
            </td>
          </tr>
        </template>
      </tbody>
    </table>
    <p x-show="!filteredLeads.length" class="p-6 text-center text-sm text-slate-500">No leads match your search.</p>
  </div>

  <!-- Summary -->
  <p class="text-xs text-slate-500">
    Showing <strong x-text="filteredLeads.length"></strong> of <strong x-text="leads.length"></strong> leads
  </p>
</div>`,
  };
}
