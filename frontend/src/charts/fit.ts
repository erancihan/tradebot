// Keep a chart sized to its box. ECharts measures once, at init: a box that
// x-show reveals in the same tick still reads 0 wide (the chart then draws at
// its 100px fallback), and a phone turned sideways changes the width without
// re-measuring. A ResizeObserver follows the box itself; the window "resize"
// event is the fallback where there is no observer.

export interface Resizable {
  resize(): void;
}

export function fitToBox(box: Element, chart: () => Resizable | null): void {
  const resize = () => chart()?.resize();
  if (typeof ResizeObserver === "undefined") {
    window.addEventListener("resize", resize);
    return;
  }
  new ResizeObserver(resize).observe(box);
}
