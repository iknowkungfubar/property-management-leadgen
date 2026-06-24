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
  };
}
