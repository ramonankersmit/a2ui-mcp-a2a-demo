import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));

const src = path.resolve(scriptDir, "../../../specification/0.8/json");
const dest = path.resolve(scriptDir, "../src/0.8/schemas");

fs.mkdirSync(dest, { recursive: true });

for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
  if (!entry.isFile() || !entry.name.endsWith(".json")) {
    continue;
  }

  fs.copyFileSync(path.join(src, entry.name), path.join(dest, entry.name));
}
