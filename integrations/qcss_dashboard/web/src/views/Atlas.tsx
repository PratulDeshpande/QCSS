import { useQuery } from "@tanstack/react-query";
import { Background, Controls, Handle, MarkerType, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Json } from "../api";
import { useRegistry } from "../registry";
import { useWorkbench } from "../state";
import { Badge, Button, Deep, Panel, SourceRef, StateBox, cx } from "../ui";

const POS: Record<string, [number, number]> = {
  clients: [0, 0], admin: [720, 0], adapters: [0, 130], runtime: [360, 130], config: [720, 130],
  compiler: [360, 260], router: [360, 390], executor: [0, 390], parameters: [720, 390],
  render: [0, 520], evolve: [360, 520], readout: [720, 520],
};
const VIEW: Record<string, string> = {
  lab: "/lab", boards: "/boards", program: "/program", physics: "/physics", timing: "/timing", signal: "/signal",
  chip: "/chip", readout: "/readout", config: "/config", admin: "/admin",
};

type ArchNode = { id: string; name: string; kind: string; view: string; packages: string[]; summary: string; detail: string; sources: string[] };

function Block({ data, selected }: NodeProps) {
  const d = data as unknown as ArchNode & { hot?: boolean };
  const tone = d.kind === "seam" ? "border-accent/70" : d.kind === "external" ? "border-dashed border-truth/70" : "border-line";
  return (
    <div className={cx("w-[220px] rounded-lg border bg-s2 px-3 py-2 text-left shadow-sm transition-shadow", tone,
      selected && "ring-2 ring-accent", d.hot && "shadow-[0_0_0_3px_color-mix(in_oklab,var(--series-2)_60%,transparent)]")}>
      <Handle type="target" position={Position.Top} className="!bg-mute" />
      <div className="flex items-center gap-2">
        <span className="text-[12.5px] font-semibold text-ink">{d.name}</span>
        <span className="ml-auto text-[9.5px] uppercase tracking-wider text-mute">{d.kind}</span>
      </div>
      <div className="mt-0.5 line-clamp-2 text-[10.5px] leading-snug text-ink2">{d.summary}</div>
      <Handle type="source" position={Position.Bottom} className="!bg-mute" />
    </div>
  );
}
const nodeTypes = { block: Block };

export function Atlas() {
  const arch = useQuery({ queryKey: ["architecture"], queryFn: () => api.get<Json>("/architecture") });
  const examples = useQuery({ queryKey: ["examples"], queryFn: () => api.get<Json>("/examples") });
  const { reg } = useRegistry();
  const { wb, set, explain } = useWorkbench();
  const [sel, setSel] = useState<string>("runtime");
  const stageHot = useMemo(() => {
    const map: Record<string, string[]> = { plan: ["runtime", "compiler", "router"], lift: ["router"], render: ["executor", "render"],
      evolve: ["evolve", "parameters"], stream: ["readout", "runtime", "adapters"] };
    return new Set((explain.data?.stages ?? []).flatMap((s: Json) => map[s.id] ?? []));
  }, [explain.data]);
  const nodes: Node[] = useMemo(() => (arch.data?.nodes ?? []).map((n: ArchNode) => ({
    id: n.id, type: "block", position: { x: POS[n.id]?.[0] ?? 0, y: POS[n.id]?.[1] ?? 0 },
    data: { ...n, hot: stageHot.has(n.id) }, selected: n.id === sel,
  })), [arch.data, sel, stageHot]);
  const edges: Edge[] = useMemo(() => (arch.data?.edges ?? []).map((e: Json, i: number) => ({
    id: `e${i}`, source: e.from, target: e.to, label: e.label, animated: true, type: "smoothstep",
    labelStyle: { fill: "var(--text-muted)", fontSize: 10 }, labelBgStyle: { fill: "var(--surface-1)" },
    style: { stroke: "var(--text-muted)", strokeWidth: 1.5 }, markerEnd: { type: MarkerType.ArrowClosed, color: "var(--text-muted)" },
  })), [arch.data]);
  const node = (arch.data?.nodes ?? []).find((n: ArchNode) => n.id === sel) as ArchNode | undefined;
  const follow = () => {
    const rabi = examples.data?.jobs?.rabi_amplitude_q0;
    if (rabi && !wb.job) set({ job: rabi, jobName: "rabi_amplitude_q0" });
    setTimeout(explain.run, 0);
  };
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-[18px] font-semibold">The virtual lab, layer by layer</h1>
        <p className="mt-1 max-w-4xl text-[13px] leading-relaxed text-ink2">
          QCSS stands in for the control electronics <em>and</em> the superconducting chip behind them. A quantum OS reaches it
          through Qibolab or a board protocol exactly as it would reach a real lab, and must not be able to tell the difference.
          It enforces the instrument's real hardware rules, hides a drifting chip the lab has to calibrate against, and behaves
          like a lab in time. Click any block to see what it does, where it lives in the code, and which view explores it.
        </p>
      </div>
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1fr_380px]">
        <Panel title="Architecture map" subtitle="Hexagonal core: adapters outside, one wiring layer (runtime), four physics seams inside">
          <StateBox state={arch.isPending ? "loading" : arch.isError ? "error" : "ok"} error={arch.error}>
            <div className="h-[600px] rounded-md border border-line bg-bg">
              <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView colorMode={document.documentElement.dataset.theme === "light" ? "light" : "dark"} minZoom={0.4} nodesDraggable
                onNodeClick={(_, n) => setSel(n.id)} proOptions={{ hideAttribution: true }}>
                <Background color="var(--grid)" gap={20} />
                <Controls showInteractive={false} />
              </ReactFlow>
            </div>
          </StateBox>
        </Panel>
        <div className="space-y-5">
          <Panel title={node?.name ?? "Select a block"} subtitle={node?.packages.join(" · ")}
            actions={node && VIEW[node.view] ? <Link to={VIEW[node.view]}><Button kind="primary">Open view →</Button></Link> : undefined}>
            {node ? (
              <div className="space-y-2 text-[12.5px] leading-relaxed text-ink2">
                <p className="text-ink">{node.summary}</p>
                <Deep at="expert"><p>{node.detail}</p></Deep>
                <Deep at="source"><div className="flex flex-wrap gap-1.5">{node.sources.map((s) => <SourceRef key={s} path={s} />)}</div></Deep>
              </div>
            ) : <p className="text-mute">Click a block on the map.</p>}
          </Panel>
          <Panel title="Follow a job through the pipeline" subtitle="Runs a real job in the sandbox and times every stage"
            actions={<Button kind="primary" onClick={follow} disabled={explain.isPending}>{explain.isPending ? "Running…" : "▶ Follow a job"}</Button>}>
            <ol className="space-y-2">
              {(arch.data?.pipeline ?? []).map((s: Json, i: number) => {
                const st = (explain.data?.stages ?? []).find((x: Json) => x.id === s.id || (s.id === "readout" && x.id === "evolve"));
                return (
                  <li key={s.id} className="flex gap-3">
                    <span className={cx("mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full border text-[10px]", st ? "border-good text-good" : "border-line text-mute")}>{i + 1}</span>
                    <div className="min-w-0">
                      <div className="text-[12.5px] font-medium text-ink">{s.name} {st && <span className="num ml-1 text-[11px] text-mute">{st.ms.toFixed(0)} ms</span>}</div>
                      <div className="text-[12px] text-ink2">{st ? st.summary : s.summary}</div>
                      <Deep at="source"><SourceRef path={s.source} /></Deep>
                    </div>
                  </li>
                );
              })}
            </ol>
            {explain.error ? <div className="mt-2"><StateBox state="error" error={explain.error} /></div> : null}
            {explain.data?.valid === false && <p className="mt-2 text-[12px] text-crit">The job was refused at {explain.data.stage}: {explain.data.violations?.[0]?.description}</p>}
          </Panel>
        </div>
      </div>
      <Panel title="Where every parameter lives" subtitle="Five layers, each owned by a different actor and changing at a different time">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-5">
          {(reg?.layers ?? []).map((l) => {
            const n = reg?.fields.filter((f) => f.layer === l.id).length ?? 0;
            const inert = reg?.fields.filter((f) => f.layer === l.id && f.inert).length ?? 0;
            return (
              <Link key={l.id} to={`/config?layer=${l.id}`} className="rounded-md border border-line bg-s2 p-3 hover:border-accent">
                <div className="flex items-center gap-2"><Badge tone={l.id === "B" ? "truth" : "accent"}>{l.id}</Badge><span className="text-[12.5px] font-semibold text-ink">{l.name}</span></div>
                <p className="mt-1.5 text-[11.5px] leading-snug text-ink2">{l.summary}</p>
                <p className="mt-2 text-[11px] text-mute">owner: {l.owner}<br />applies: {l.when}</p>
                <p className="num mt-1 text-[11px] text-mute">{n} fields{inert ? ` · ${inert} inert` : ""}</p>
              </Link>
            );
          })}
        </div>
      </Panel>
    </div>
  );
}
