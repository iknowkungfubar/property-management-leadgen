/**
 * Settings panel — LLM provider selection, API keys, model config.
 * Includes loading skeleton and save spinner.
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
    isSaving: false,
    isLoading: true,

    // ── Lifecycle ──────────────────────────────────────────────────
    async init() {
      const ipc = Alpine.store("ipc");
      try {
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
      // Simulate brief loading for smooth skeleton transition
      setTimeout(() => { this.isLoading = false; }, 400);
    },

    // ── Helpers ────────────────────────────────────────────────────
    app() {
      return Alpine.store("app");
    },

    // ── Actions ────────────────────────────────────────────────────
    onProviderChange() {
      if (!this.model || DEFAULT_MODELS[this.selectedProvider]) {
        this.model = DEFAULT_MODELS[this.selectedProvider] || "";
      }
      if (this.selectedProvider === "anthropic") this.baseUrl = "";
      if (this.selectedProvider === "openai") this.baseUrl = "";
    },

    async saveSettings() {
      this.isSaving = true;
      this.saveMessage = "Saving…";

      const payload = {
        provider: this.selectedProvider,
        api_key: this.apiKey,
        base_url: this.baseUrl,
        model: this.model,
      };

      const maskedPayload = {
        ...payload,
        api_key: this.apiKey ? this.apiKey.slice(0, 4) + "****" : "",
      };
      localStorage.setItem("leadgen_llm_settings", JSON.stringify(maskedPayload));

      try {
        const ipc = Alpine.store("ipc");
        await ipc.send("llm_settings.set", {
          provider: this.selectedProvider,
          api_key: this.apiKey,
          base_url: this.baseUrl,
          selected_model: this.model,
          is_active: 1,
        });

        this.saveMessage = "Saved successfully.";
        this.app().notifySuccess("Settings Saved", "LLM provider configuration updated.");
      } catch (err) {
        this.saveMessage = `Save failed: ${err.message}`;
        this.app().notifyError("Save Failed", err.message);
      }

      this.isSaving = false;
      setTimeout(() => { this.saveMessage = ""; }, 4000);
    },

    // ── Template ─────────────────────────────────────────────────
    template: `<div class="space-y-6">
  <h2 class="text-2xl font-bold">Settings</h2>

  <!-- ── Skeleton loading ──────────────────────────────────────── -->
  <template x-if="isLoading">
    <div class="bg-slate-800 border border-slate-700 rounded-xl p-5 space-y-4">
      <div class="skeleton h-5 w-32"></div>
      <div class="skeleton h-10 w-full"></div>
      <div class="skeleton h-10 w-full"></div>
      <div class="skeleton h-10 w-full"></div>
      <div class="skeleton h-10 w-full"></div>
      <div class="skeleton h-10 w-28"></div>
    </div>
  </template>

  <!-- ── Settings form ─────────────────────────────────────────── -->
  <template x-if="!isLoading">
    <div class="bg-slate-800 border border-slate-700 rounded-xl p-5">
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
          <input
            type="password"
            x-model="apiKey"
            class="input-field"
            placeholder="sk-…"
          />
        </div>
        <div>
          <label class="block text-xs text-slate-400 mb-1">Base URL</label>
          <input
            type="text"
            x-model="baseUrl"
            class="input-field"
            placeholder="https://api.anthropic.com"
          />
        </div>
        <div>
          <label class="block text-xs text-slate-400 mb-1">Model</label>
          <input
            type="text"
            x-model="model"
            class="input-field"
            placeholder="claude-sonnet-4-20250514"
          />
        </div>
        <div class="flex items-center gap-3 pt-2">
          <button
            @click="saveSettings()"
            :disabled="isSaving"
            class="btn-primary text-sm inline-flex items-center gap-2"
          >
            <template x-if="isSaving">
              <svg class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"/>
              </svg>
            </template>
            <span x-text="isSaving ? 'Saving…' : 'Save Settings'"></span>
          </button>
          <span
            x-show="saveMessage"
            x-text="saveMessage"
            :class="saveMessage.includes('fail') || saveMessage.includes('Fail') ? 'text-red-400' : 'text-emerald-400'"
            class="text-sm"
          ></span>
        </div>
      </div>
    </div>
  </template>
</div>`,
  };
}
