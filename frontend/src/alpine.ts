import type { AccountView } from "./types";

// Small typed accessors for Alpine's magic properties, so components stay
// strictly typed without sprinkling `any` everywhere.

interface AlpineRefs {
  $refs: Record<string, HTMLElement>;
}

interface AlpineEl {
  $el: HTMLElement;
}

interface AlpineNextTick {
  $nextTick: () => Promise<void>;
}

export function refs(ctx: unknown): Record<string, HTMLElement> {
  return (ctx as AlpineRefs).$refs;
}

export function el(ctx: unknown): HTMLElement {
  return (ctx as AlpineEl).$el;
}

export function nextTick(ctx: unknown): Promise<void> {
  return (ctx as AlpineNextTick).$nextTick();
}

// Shared "live" state. A single SSE stream bumps `tick` (a heartbeat every
// component re-fetches on) and pushes the latest `account`; one pause button
// stops the whole dashboard.
export interface LiveStore {
  enabled: boolean;
  lastUpdated: string;
  tick: number;
  account: AccountView | null;
  stamp(): void;
  toggle(): void;
}

interface AlpineStores {
  $store: { live: LiveStore };
}

export function live(ctx: unknown): LiveStore {
  return (ctx as AlpineStores).$store.live;
}

export function makeLiveStore(): LiveStore {
  return {
    enabled: true,
    lastUpdated: "",
    tick: 0,
    account: null,
    stamp() {
      this.lastUpdated = new Date().toLocaleTimeString();
    },
    toggle() {
      this.enabled = !this.enabled;
    },
  };
}
