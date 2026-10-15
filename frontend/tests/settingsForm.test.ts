// Settings form: the public URL round-trips, a trailing "/" is dropped, and
// an emptied field means "none".

import { toDoc, toForm } from "../src/components/settingsForm";
import type { SettingsDoc } from "../src/types";
import { check } from "./harness";

const doc: SettingsDoc = {
  mode: "paper", symbols: ["SPY"], timeframe: "1day", poll_seconds: 300, market: "us_equities",
  autopilot: { brief_minutes_before_open: null }, initial_cash: 10000,
  strategy: { name: "buy_and_hold", params: {} },
  portfolio: { selector: null, allocation: null, params: {}, overlays: [] },
  risk: {},
  notify: { webhook_url: null, ntfy_topic: "my…ic", ntfy_server: null,
            public_url: "http://192.168.1.20:8000" },
} as unknown as SettingsDoc;

const form = toForm(doc);
check(form.publicUrl === "http://192.168.1.20:8000", "the form shows the stored URL");
check(toDoc(form, doc).notify.public_url === "http://192.168.1.20:8000", "kept unchanged");

form.publicUrl = "  https://bot.example.net/ ";
check(toDoc(form, doc).notify.public_url === "https://bot.example.net", "trimmed, no trailing slash");

form.publicUrl = "";
check(toDoc(form, doc).notify.public_url === null, "empty means none");

const bare = toForm({ ...doc, notify: { webhook_url: null, ntfy_topic: null, ntfy_server: null } });
check(bare.publicUrl === "", "an older document without the key shows an empty field");
