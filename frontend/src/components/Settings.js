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
        // Save only the active provider to the llm_settings table.
        // Non-active providers keep their existing values in the DB.
        await ipc.send("llm_settings.set", {
          provider: this.selectedProvider,
          api_key: this.apiKey,
          base_url: this.baseUrl,
          selected_model: this.model,
          is_active: 1,
        });

        this.saveMessage = "Saved successfully.";
      } catch (err) {
        this.saveMessage = `Save failed: ${err.message}`;
      }

      // Clear the message after a few seconds
      setTimeout(() => {
        this.saveMessage = "";
      }, 4000);
    },

    // ── Template ─────────────────────────────────────────────────
    template: `<div class="space-y-6">
  <h2 class="text-2xl font-bold">Settings</h2>

  <div class="card">
    <h3 class="text-sm font-medium text-slate-300 mb-4">LLM Provider</h3>
    <div class="space-y-4">
      <div>
        <label class="block text-xs text-slate-400 mb-1">Provider</label>
        <select x-model="selectedProvider" @change="onProviderChange()" class="input-field">
          <template x-for="p in providers" :key="p.id">
            <option :value="p.id" x-text="p.label"></option>
          </template>
        </select>
      </div>
      <div>
        <label class="block text-xs text-slate-400 mb-1">API Key</label>
        <input type="password" x-model="apiKey" class="input-field" placeholder="sk-…" />
      </div>
      <div>
        <label class="block text-xs text-slate-400 mb-1">Base URL</label>
        <input type="text" x-model="baseUrl" class="input-field" placeholder="https://api.anthropic.com" />
      </div>
      <div>
        <label class="block text-xs text-slate-400 mb-1">Model</label>
        <input type="text" x-model="model" class="input-field" placeholder="claude-sonnet-4-20250514" />
      </div>
      <div class="flex items-center gap-3">
        <button @click="saveSettings()" class="btn-primary">Save Settings</button>
        <span x-show="saveMessage" x-text="saveMessage" :class="saveMessage.includes('fail') ? 'text-red-400' : 'text-emerald-400'" class="text-sm"></span>
      </div>
    </div>
  </div>
</div>`,
  };
}
