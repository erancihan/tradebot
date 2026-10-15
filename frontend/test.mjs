// Behaviour tests for the browser code, run in Node without a browser.
//
// Each `tests/*.test.ts` is bundled by esbuild (the same compiler the build
// uses) and imported; a test module throws, or rejects, to fail. The tests
// stub `fetch`, so they need no server. Typechecking stays with `tsc`.

import * as esbuild from "esbuild";
import { mkdtempSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const files = readdirSync("tests").filter((f) => f.endsWith(".test.ts")).sort();
const out = mkdtempSync(join(tmpdir(), "tradebot-fe-"));
let failed = 0;
try {
  for (const file of files) {
    const bundle = join(out, file.replace(/\.ts$/, ".mjs"));
    await esbuild.build({
      entryPoints: [join("tests", file)], bundle: true, format: "esm",
      platform: "node", target: ["node20"], outfile: bundle, logLevel: "warning",
    });
    try {
      await import(pathToFileURL(bundle).href);
      console.log(`ok   ${file}`);
    } catch (err) {
      failed += 1;
      console.error(`FAIL ${file}\n${err && err.stack ? err.stack : err}`);
    }
  }
} finally {
  rmSync(out, { recursive: true, force: true });
}
console.log(`${files.length - failed}/${files.length} frontend test files passed`);
process.exit(failed ? 1 : 0);
