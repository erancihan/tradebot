import * as esbuild from "esbuild";

const watch = process.argv.includes("--watch");

const options = {
  entryPoints: ["src/main.ts"],
  bundle: true,
  format: "esm",
  target: ["es2020"],
  outfile: "../tradebot/web/static/js/app.js",
  sourcemap: true,
  // Minify production builds; keep dev/watch builds readable.
  minify: !watch,
  logLevel: "info",
};

if (watch) {
  const ctx = await esbuild.context(options);
  await ctx.watch();
  console.log("esbuild: watching for changes…");
} else {
  await esbuild.build(options);
}
