/**
 * Settings panel — LLM provider selection, API keys, model config.
 */

const PROVIDERS = [
  { id: "anthropic", label: "Anthropic" },
  { id: "openai", label: "OpenAI" },
  { id: "openpipe", label: "OpenPipe" },
  { id: "local_ollama", label: "Local Ollama" },
];

const DEFAULT_MODELS = {
  anthropic: "claude-sonnet-4-20250514",
  openai: "gpt-4o",
  openpipe: "gpt-4o-mini",
  local_ollama: "llama3.2",
};

export function settingsPanel() {
  return {
    // ── State ──────────────────────────────────────────────────────
    providers: PROVIDERS,
    selectedProvider: "anthropic",
    apiKey: "",
    baseUrl: "",
    model: "",
    saveMessage: "",

    // ── Lifecycle ──────────────────────────────────────────────────
    async init() {
      const ipc = Alpine.store("ipc");
      try {
        // Load saved LLM settings
        // In production this comes from the llm_settings table via IPC.
        // For dev we seed defaults from localStorage.
        const saved = localStorage.getItem("leadgen_llm_settings");
        if (saved) {
          const parsed = JSON.parse(saved);
          this.selectedProvider = parsed.provider || "anthropic";
          this.apiKey = parsed.api_key || "";
          this.baseUrl = parsed.base_url || "";
          this.model = parsed.model || DEFAULT_MODELS[this.selectedProvider];
        } else {
          this.model = DEFAULT_MODELS[this.selectedProvider];
        }
      } catch {
        this.model = DEFAULT_MODELS[this.selectedProvider];
      }
    },

    // ── Actions ────────────────────────────────────────────────────
    onProviderChange() {
      // Reset model to default for the selected provider unless user has typed
      if (!this.model || DEFAULT_MODELS[this.selectedProvider]) {
        this.model = DEFAULT_MODELS[this.selectedProvider] || "";
      }
      // Clear base URL for well-known providers
      if (this.selectedProvider === "anthropic") this.baseUrl = "";
      if (this.selectedProvider === "openai") this.baseUrl = "";
    },

    async saveSettings() {
      this.saveMessage = "Saving…";

      const payload = {
        provider: this.selectedProvider,
        api_key: this.apiKey,
        base_url: this.baseUrl,
        model: this.model,
      };

      // Persist to localStorage for dev resilience
      localStorage.setItem("leadgen_llm_settings", JSON.stringify(payload));

      try {
        const ipc = Alpine.store("ipc");
        // Save to the llm_settings relational table via the sidecar.
        // The sidecar handles INSERT OR REPLACE into llm_settings with
        // the correct columns: provider, api_key, base_url, selected_model, is_active.
        for (const p of PROVIDERS) {
          const isActive = p.id === this.selectedProvider;
          await ipc.send("llm_settings.set", {
            provider: p.id,
            api_key: isActive ? this.apiKey : "",
            base_url: isActive ? this.baseUrl : "",
            selected_model: isActive ? this.model : (p.id === this.selectedProvider ? this.model : ""),
            is_active: isActive ? 1 : 0,
          });
        }

        this.saveMessage = "Saved successfully.";
      } catch (err) {
        this.saveMessage = `Save failed: ${err.message}`;
      }

      // Clear the message after a few seconds
      setTimeout(() => {
        this.saveMessage = "";
      }, 4000);
    },
  };
}
