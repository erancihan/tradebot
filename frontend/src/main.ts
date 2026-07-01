// Entry point: register the Alpine components and start Alpine. This is the only
// script the page loads; all behaviour lives in imported, typed modules.

import Alpine from "alpinejs";

import type { LiveStore } from "./alpine";
import { makeLiveStore } from "./alpine";
import { arenaChart } from "./components/arena";
import { candleChart } from "./components/candleChart";
import { equityChart } from "./components/dashboard";
import { jobRunner } from "./components/jobRunner";
import { partialLoader } from "./components/partialLoader";
import { seasonChart } from "./components/seasonChart";
import { startSse } from "./sse";

declare global {
  interface Window {
    Alpine: typeof Alpine;
  }
}

Alpine.store("live", makeLiveStore());

Alpine.data("equityChart", equityChart);
Alpine.data("arenaChart", arenaChart);
Alpine.data("candleChart", candleChart);
Alpine.data("seasonChart", seasonChart);
Alpine.data("jobRunner", jobRunner);
Alpine.data("partialLoader", partialLoader);

window.Alpine = Alpine;
Alpine.start();

// Single SSE stream drives live updates for the whole dashboard.
startSse(Alpine.store("live") as LiveStore);
