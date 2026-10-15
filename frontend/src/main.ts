// Entry point: register the Alpine components and start Alpine. This is the only
// script the page loads; all behaviour lives in imported, typed modules.

import Alpine from "alpinejs";

import type { LiveStore } from "./alpine";
import { makeLiveStore } from "./alpine";
import { arenaChart } from "./components/arena";
import { autopilot } from "./components/autopilot";
import { candleChart } from "./components/candleChart";
import { equityChart } from "./components/dashboard";
import { discover } from "./components/discover";
import { history } from "./components/history";
import { jobRunner } from "./components/jobRunner";
import { moreSheet } from "./components/moreSheet";
import { partialLoader } from "./components/partialLoader";
import { seasonChart } from "./components/seasonChart";
import { settings } from "./components/settings";
import { today } from "./components/today";
import { whatIf } from "./components/whatif";
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
Alpine.data("today", today);
Alpine.data("discover", discover);
Alpine.data("autopilot", autopilot);
Alpine.data("history", history);
Alpine.data("whatIf", whatIf);
Alpine.data("jobRunner", jobRunner);
Alpine.data("moreSheet", moreSheet);
Alpine.data("partialLoader", partialLoader);
Alpine.data("settings", settings);

window.Alpine = Alpine;
Alpine.start();

// Single SSE stream drives live updates for the whole dashboard.
startSse(Alpine.store("live") as LiveStore);
