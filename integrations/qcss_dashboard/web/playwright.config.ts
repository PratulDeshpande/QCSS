import { defineConfig, devices } from "@playwright/test";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

// End-to-end against the real thing: the bridge (with an embedded QCSS chassis, frozen lab clock for speed) serves
// the built frontend. Run `npm run build` first. One worker: each journey drives one shared chassis.
const workspace = path.join(os.tmpdir(), `qcss-dashboard-e2e-${Date.now()}`);
const repo = path.resolve(here, "../../..");

export default defineConfig({
  testDir: "e2e",
  workers: 1,
  timeout: 120_000,
  expect: { timeout: 60_000 },
  reporter: [["list"]],
  use: { baseURL: "http://127.0.0.1:8799", trace: "retain-on-failure", screenshot: "only-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
  webServer: {
    command: `uv run python -m qcss_dashboard.cli --port 8799 --workspace "${workspace}" --time-scale 0 --static "${path.join(here, "dist")}"`,
    cwd: repo,
    env: { PYTHONPATH: path.join(repo, "integrations", "qcss_dashboard", "src") },
    url: "http://127.0.0.1:8799/api/health",
    timeout: 120_000,
    reuseExistingServer: false,
  },
});
