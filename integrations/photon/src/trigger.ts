// Manual departure test: asks the local Keepsake backend to record a simulated possible departure.
// The running agent picks it up on its next poll and evaluates the real stored memories.
// Usage: npm run trigger:departure

import { KeepsakeClient, KeepsakeUnavailable } from "./keepsake.ts";

const url = (process.env.KEEPSAKE_API_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
try {
  const ev = await new KeepsakeClient(url).simulateDeparture();
  console.log(`Recorded simulated departure #${ev.id} at ${ev.at}. Watch the agent log for the outcome.`);
} catch (err) {
  console.error(err instanceof KeepsakeUnavailable ? err.message : err);
  process.exit(1);
}
