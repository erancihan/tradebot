// Settings page: one form over config.yaml's editable keys, one Save button.
// The server validates by building every component the document names, so a
// refusal arrives as one readable sentence and is shown as-is. Nothing here
// ever holds a broker key; alert destinations arrive masked and a masked or
// blank value means "keep what the server has".

import { getSettings, saveSettings } from "../api/client";
import type { SettingsDoc, SettingsView } from "../types";
import { toDoc, toForm, type SettingsForm } from "./settingsForm";

export function settings() {
  return {
    loading: true,
    saving: false,
    error: "",
    notice: "",
    original: null as SettingsDoc | null,
    form: null as SettingsForm | null,
    choices: { markets: [] as string[], timeframes: [] as string[] },

    async init() {
      try {
        this.apply(await getSettings());
      } catch (err) {
        this.error = err instanceof Error ? err.message : String(err);
      } finally {
        this.loading = false;
      }
    },

    apply(view: SettingsView) {
      this.original = view.settings;
      this.form = toForm(view.settings);
      this.choices = view.choices;
    },

    async save() {
      if (!this.form || !this.original || this.saving) return;
      this.saving = true;
      this.error = "";
      this.notice = "";
      try {
        const view = await saveSettings(toDoc(this.form, this.original));
        this.apply(view);
        this.notice = view.notice ?? "Saved.";
      } catch (err) {
        this.error = err instanceof Error ? err.message : String(err);
      } finally {
        this.saving = false;
      }
    },
  };
}
