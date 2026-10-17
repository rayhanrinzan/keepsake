// Manual reminder check over real stored memory (the P0 demo path). It never injects a placement
// or detection: the engine evaluates what Keepsake actually recorded and labels this "manual".
// Usage: npm run reminder:check            (developer trigger)
//        npm run reminder:check heading_out (same as texting "heading out")

import { KeepsakeClient, KeepsakeRefused, KeepsakeUnavailable } from "./keepsake.ts";

const url = (process.env.KEEPSAKE_API_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
const reason = process.argv[2] === "heading_out" ? "heading_out" : "manual";
try {
  const r = await new KeepsakeClient(url).check(reason);
  if (r.queued && r.alert) {
    console.log(`Queued reminder #${r.alert.id} (${r.alert.trigger}, ${r.alert.mode}) about: ` +
      r.alert.items.map((i) => `${i.name} (last seen ${i.last_seen}, photo #${i.snapshot_id})`).join(", "));
    console.log("The running agent sends it on its next poll; watch its log.");
  } else {
    console.log(`No reminder queued: ${r.blocked}`);
  }
  for (const s of r.skipped) console.log(`  skipped ${s.object_id}: ${s.reason}`);
} catch (err) {
  console.error(err instanceof KeepsakeUnavailable || err instanceof KeepsakeRefused ? err.message : err);
  process.exit(1);
}
