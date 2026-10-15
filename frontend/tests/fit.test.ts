// fitToBox: a chart drawn while its box was hidden is resized once the box
// gets its width, and on every later change (an orientation flip).

import { fitToBox } from "../src/charts/fit";
import { check } from "./harness";

type Callback = () => void;
const observed: Element[] = [];
let fire: Callback = () => {};
(globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
  constructor(cb: Callback) {
    fire = cb;
  }
  observe(box: Element) {
    observed.push(box);
  }
};

let resizes = 0;
const box = {} as Element;
let chart: { resize(): void } | null = null;
fitToBox(box, () => chart);
check(observed.length === 1 && observed[0] === box, "observes the chart's own box");
fire();
check(resizes === 0, "no chart yet, nothing to resize");
chart = { resize: () => (resizes += 1) };
fire();
fire();
check(resizes === 2, `each box change resizes the chart: ${resizes}`);

// Without an observer it falls back to the window's resize event.
delete (globalThis as { ResizeObserver?: unknown }).ResizeObserver;
const listeners: Callback[] = [];
(globalThis as { window?: unknown }).window = {
  addEventListener: (_: string, cb: Callback) => listeners.push(cb),
};
fitToBox(box, () => chart);
listeners.forEach((cb) => cb());
check(listeners.length === 1 && resizes === 3, "window resize is the fallback");
// The test files share one process: leave no fake window for echarts to find.
delete (globalThis as { window?: unknown }).window;
