// Settings page: one form over config.yaml's editable keys, one Save button.
// The server validates by building every component the document names, so a
// refusal arrives as one readable sentence and is shown as-is. Nothing here
// ever holds a broker key; alert destinations arrive masked and a masked or
// blank value means "keep what the server has". A save posts the file version
// the page loaded; a 409 means the file changed meanwhile and says to reload.
//
// The strategy, selector and allocator pickers come from the registries
// (/api/strategies, /api/stack); picking one resets its params to that
// component's defaults. The pickers set the name themselves rather than via
// x-model, so loading a saved document never fires a "changed" reset.

import { getSettings, getStack, getStrategies, saveSettings } from "../api/client";
import type { SettingsDoc, SettingsView, StackSpecs, StrategyParam, StrategySpec } from "../types";
import { defaults, toDoc, toForm, type SettingsForm } from "./settingsForm";

export type PickerKind = "strategy" | "selector" | "allocation";

const PARAMS_KEY = {
  strategy: "strategyParams",
  selector: "selectorParams",
  allocation: "allocationParams",
} as const;

export function settings() {
  return {
    loading: true,
    saving: false,
    error: "",
    notice: "",
    original: null as SettingsDoc | null,
    // The file's version this page last saw; posted back with a save.
    version: undefined as string | undefined,
    form: null as SettingsForm | null,
    choices: { markets: [] as string[], timeframes: [] as string[] },
    strategies: [] as StrategySpec[],
    stack: { selectors: [], allocators: [] } as StackSpecs,

    async init() {
      try {
        const [view, strategies, stack] = await Promise.all([getSettings(), getStrategies(), getStack()]);
        this.strategies = strategies;
        this.stack = stack;
        this.apply(view);
      } catch (err) {
        this.error = err instanceof Error ? err.message : String(err);
      } finally {
        this.loading = false;
      }
    },

    apply(view: SettingsView) {
      this.original = view.settings;
      this.version = view.version;
      const form = toForm(view.settings);
      // Show every form-able param, the ones the file leaves at default too.
      for (const kind of ["strategy", "selector", "allocation"] as const) {
        form[PARAMS_KEY[kind]] = { ...defaults(this.specsFor(kind, form[kind])), ...form[PARAMS_KEY[kind]] };
      }
      this.form = form;
      this.choices = view.choices;
    },

    catalog(kind: PickerKind): StrategySpec[] {
      if (kind === "strategy") return this.strategies;
      return kind === "selector" ? this.stack.selectors : this.stack.allocators;
    },

    specsFor(kind: PickerKind, name: string): StrategyParam[] {
      return this.catalog(kind).find((spec) => spec.name === name)?.params ?? [];
    },

    params(kind: PickerKind): StrategyParam[] {
      return this.form ? this.specsFor(kind, this.form[kind]) : [];
    },

    // Registry names, plus the current one when only the file can express it
    // (e.g. `explicit` weights), so a save never silently drops it.
    options(kind: PickerKind): string[] {
      const names = this.catalog(kind).map((spec) => spec.name);
      const current = this.form?.[kind] ?? "";
      return current && !names.includes(current) ? [...names, current] : names;
    },

    pick(kind: PickerKind, name: string) {
      if (!this.form) return;
      this.form[kind] = name;
      this.form[PARAMS_KEY[kind]] = defaults(this.specsFor(kind, name));
    },

    async save() {
      if (!this.form || !this.original || this.saving) return;
      this.saving = true;
      this.error = "";
      this.notice = "";
      try {
        const view = await saveSettings({ ...toDoc(this.form, this.original), version: this.version });
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
