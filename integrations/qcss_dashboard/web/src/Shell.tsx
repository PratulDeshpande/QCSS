import { useState, type ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { useRegistry, type Depth } from "./registry";
import { useWorkbench } from "./state";
import { cx } from "./ui";

type NavItem = { to: string; label: string; tag?: string; hint: string };
const GROUPS: { title: string; path?: boolean; items: NavItem[] }[] = [
  { title: "Overview", items: [{ to: "/", label: "Atlas", hint: "The whole architecture and a job's journey through it" }] },
  { title: "Configure", items: [{ to: "/config", label: "Config Studio", hint: "Every parameter of every layer, explained and editable" }] },
  {
    title: "Signal path", path: true, items: [
      { to: "/hardware", label: "Hardware & timing", tag: "A", hint: "The instrument's rules: grids, memories, NCOs, latencies" },
      { to: "/program", label: "Program & compiler", tag: "IR", hint: "Job → program IR → validator" },
      { to: "/signal", label: "Signal chain", tag: "seam 1", hint: "NCO, mixers, LO leakage, flux-line distortion" },
      { to: "/chip", label: "Chip truth", tag: "seam 2", hint: "The hidden transmons, drift, TLS defects, bursts" },
      { to: "/physics", label: "Physics & tiers", tag: "seam 3", hint: "Lifted gates, the tier router, the quantum state" },
      { to: "/readout", label: "Readout", tag: "seam 4", hint: "Resonator, ADC traces, IQ clouds, discrimination" },
      { to: "/timing", label: "Feedback & timing", tag: "DES", hint: "One shot's event timeline and the latency budget" },
      { to: "/boards", label: "Board faces", tag: "faces", hint: "How Qibolab, Qibosoq and QICK clients reach QCSS" },
    ],
  },
  {
    title: "Operate", items: [
      { to: "/admin", label: "Admin console", tag: "truth", hint: "Ground truth, scenarios, faults, live mode" },
      { to: "/lab", label: "Lab bench", tag: "lab", hint: "Run experiments exactly as a lab client" },
      { to: "/whatif", label: "What-if lab", hint: "Change any factor, compare the outcome" },
    ],
  },
  { title: "Learn", items: [{ to: "/learn", label: "Tours & glossary", hint: "Guided tours and every parameter, searchable" }] },
];

function Dot({ ok, label }: { ok: boolean | undefined; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] text-ink2" title={`${label}: ${ok ? "connected" : "unreachable"}`}>
      <span className={cx("h-2 w-2 rounded-full", ok ? "bg-good" : ok === false ? "bg-crit" : "bg-mute")} />
      {label}
      <span className="sr-only">{ok ? "connected" : "unreachable"}</span>
    </span>
  );
}

function TopBar({ onMenu }: { onMenu: () => void }) {
  const { live, liveError } = useWorkbench();
  const { depth, setDepth } = useRegistry();
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme ?? "dark");
  const mode = live?.mode;
  const labTime = live?.truth?.lab_time_s as number | undefined;
  const tier = mode?.tier_policy ? String(mode.tier_policy).replace("FIDELITY_TIER_", "").split("_")[0] : "—";
  const toggleTheme = () => {
    const t = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = t;
    setTheme(t);
  };
  return (
    <header className="flex min-h-11 shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-b border-line bg-s1 px-4 py-1.5">
      <button onClick={onMenu} className="rounded-md border border-line bg-s2 px-2 py-1 text-[12px] md:hidden" aria-label="Open the layer menu">☰ layers</button>
      <Dot ok={live?.lab?.ok} label="lab link" />
      <Dot ok={live?.admin?.ok} label="admin channel" />
      {live?.chassis && <span className="hidden text-[11px] text-mute xl:inline">embedded chassis · <span className="text-ink2">{live.chassis.profile}</span> · <span className="text-ink2">{live.chassis.device}</span></span>}
      <span className="num text-[11px] text-mute" title="Lab clock: wall time × time_scale since the chip was cooled down">
        lab time <span className="text-ink">{labTime !== undefined ? fmtDuration(labTime) : "—"}</span>
      </span>
      <span className="num text-[11px] text-mute" title="Calibration epoch: bumped by every compare-and-swap write">
        cal epoch <span className="text-ink">{live?.calibration_epoch ?? "—"}</span>
      </span>
      {mode && <span className="num hidden text-[11px] text-mute lg:inline">×{mode.time_scale} · {mode.deterministic ? "deterministic" : "entropy"} · tier {tier === "UNSPECIFIED" ? "requested" : tier}</span>}
      {liveError && <span className="text-[11px] text-warn">⚠ {liveError}</span>}
      <div className="ml-auto flex items-center gap-2">
        <span className="text-[11px] text-mute">explain</span>
        <div role="radiogroup" aria-label="Explanation depth" className="flex overflow-hidden rounded-md border border-line">
          {(["plain", "expert", "source"] as Depth[]).map((d) => (
            <button key={d} role="radio" aria-checked={depth === d} onClick={() => setDepth(d)}
              className={cx("px-2.5 py-1 text-[11px] capitalize", depth === d ? "bg-accent text-white" : "bg-s2 text-ink2 hover:bg-s3")}>{d}</button>
          ))}
        </div>
        <button onClick={toggleTheme} className="rounded-md border border-line bg-s2 px-2 py-1 text-[11px] text-ink2 hover:bg-s3" aria-label="Toggle colour theme">
          {theme === "dark" ? "☾ dark" : "☀ light"}
        </button>
      </div>
    </header>
  );
}

export function fmtDuration(s: number): string {
  if (s < 120) return `${s.toFixed(1)} s`;
  if (s < 7200) return `${(s / 60).toFixed(1)} min`;
  if (s < 172800) return `${(s / 3600).toFixed(2)} h`;
  return `${(s / 86400).toFixed(2)} d`;
}

export function Shell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="flex h-full">
      {open && <div className="fixed inset-0 z-30 bg-black/50 md:hidden" onClick={() => setOpen(false)} aria-hidden />}
      <nav aria-label="QCSS layers" onClick={(e) => { if ((e.target as HTMLElement).closest("a")) setOpen(false); }}
        className={cx("w-60 shrink-0 flex-col overflow-y-auto border-r border-line bg-s1 max-md:fixed max-md:inset-y-0 max-md:left-0 max-md:z-40 md:flex", open ? "flex" : "hidden")}>
        <div className="border-b border-line px-4 py-3">
          <div className="text-[14px] font-semibold tracking-wide text-ink">QCSS Explorer</div>
          <div className="text-[11px] text-mute">virtual superconducting lab · operator view</div>
        </div>
        {GROUPS.map((g) => (
          <div key={g.title} className="px-2 pt-3">
            <div className="px-2 pb-1 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-mute">{g.title}</div>
            <ul className={cx(g.path && "relative ml-3 border-l border-dashed border-line")}>
              {g.items.map((it) => (
                <li key={it.to}>
                  <NavLink to={it.to} end title={it.hint}
                    className={({ isActive }) => cx("group relative flex items-center gap-2 rounded-md px-2 py-1.5 text-[12.5px]",
                      g.path && "ml-2", isActive ? "bg-s3 text-ink" : "text-ink2 hover:bg-s2")}>
                    {({ isActive }) => (
                      <>
                        {g.path && <span className={cx("absolute -left-[13px] h-2 w-2 rounded-full border", isActive ? "border-accent bg-accent" : "border-line bg-s1")} />}
                        <span className="flex-1 truncate">{it.label}</span>
                        {it.tag && <span className={cx("rounded px-1 text-[9.5px] uppercase tracking-wider", it.tag === "truth" ? "text-truth" : "text-mute")}>{it.tag}</span>}
                      </>
                    )}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
        <div className="mt-auto border-t border-line p-3 text-[10.5px] leading-snug text-mute">
          Operator surface: shows the chip's hidden truth. Lab clients never see this; nothing here changes the lab link.
        </div>
      </nav>
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar onMenu={() => setOpen(true)} />
        <main className="min-h-0 flex-1 overflow-y-auto p-5">{children}</main>
      </div>
    </div>
  );
}
