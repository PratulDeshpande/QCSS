import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, type Json } from "../api";
import { useWorkbench } from "../state";
import { Badge, Deep, InfoTip, KV, Panel, Select, SourceRef, Stat, StateBox, fmt } from "../ui";
import { DraftNote, ProfilePicker } from "./common";

/** Tick ruler: where each generator's samples, real-time grid and NCO grid fall on the integer tick axis. */
function TickRuler({ hw, ns }: { hw: Json; ns: number }) {
  const gens: Json[] = hw.generators.slice(0, 6);
  const W = 900, left = 150, lane = 30, ticks = Math.round(ns / hw.tick_ns);
  const sx = (t: number) => left + (t / ticks) * (W - left - 10);
  const marks = (step: number) => Array.from({ length: Math.floor(ticks / step) + 1 }, (_, k) => k * step).filter((t) => t <= ticks);
  return (
    <svg viewBox={`0 0 ${W} ${lane * (gens.length * 3 + 1) + 20}`} className="w-full" role="img" aria-label="tick ruler">
      <text x={left - 8} y={14} textAnchor="end" fontSize={11} fill="var(--text-secondary)">tick ({fmt(hw.tick_ns, 4)} ns)</text>
      {ticks <= 400 && marks(1).map((t) => <line key={t} x1={sx(t)} x2={sx(t)} y1={6} y2={18} stroke="var(--grid)" />)}
      {gens.map((g, i) => {
        const y0 = lane * (1 + i * 3);
        const rows: [string, number, number][] = [["DAC sample", g.ticks_per_sample, 1], ["real-time grid", g.rt_grid_ticks, 3], ["NCO grid", Math.round(g.nco_grid_ns / hw.tick_ns), 2]];
        return (
          <g key={g.generator_id}>
            <text x={4} y={y0 + 14} fontSize={11} fill="var(--text-primary)">{g.generator_id}</text>
            {rows.map(([label, step, color], r) => (
              <g key={label}>
                <text x={left - 8} y={y0 + r * 10 + 12} textAnchor="end" fontSize={9.5} fill="var(--text-muted)">{label} · {step}</text>
                {step > 0 && marks(step).slice(0, 400).map((t) => <rect key={t} x={sx(t) - 1} y={y0 + r * 10 + 4} width={2} height={8} rx={1} fill={`var(--series-${color})`} />)}
              </g>
            ))}
          </g>
        );
      })}
    </svg>
  );
}

export function Hardware() {
  const { configBody, wb } = useWorkbench();
  const q = useQuery({ queryKey: ["hw", configBody()], queryFn: () => api.post<Json>("/views/hardware", configBody()) });
  const [span, setSpan] = useState("64");
  const hw = q.data;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="text-[18px] font-semibold">Hardware & timing</h1>
          <p className="mt-1 max-w-4xl text-[13px] text-ink2">The instrument as rules. Every time in QCSS is an integer number of ticks; generators play on their own grids; feedback has a fixed latency. A job that breaks any of these is refused with the same field path a real driver would report.</p>
        </div>
        <ProfilePicker />
      </div>
      <DraftNote />
      <StateBox state={q.isPending ? "loading" : q.isError ? "error" : "ok"} error={q.error} onRetry={() => q.refetch()}>
        {hw && (
          <>
            <div className="grid grid-cols-2 gap-4 rounded-lg border border-line bg-s1 p-4 md:grid-cols-5">
              <Stat label="instrument" value={hw.profile_name} hint={hw.vendor} />
              <Stat label="tick" value={fmt(hw.tick_hz / 1e9, 4)} unit="GHz" hint={`exact "${hw.tick_hz_exact}"`} />
              <Stat label="generators" value={hw.generators.length} hint={`${hw.ports.length} ports`} />
              <Stat label="readout ToF" value={fmt(Object.values(hw.tof as Json)[0]?.ns, 1)} unit="ns" hint="internal + output + cable" />
              <Stat label="acq modes" value={hw.acquisition.modes.length} hint={hw.acquisition.modes.join(", ")} />
            </div>
            <Panel title={<span>Tick ruler <InfoTip docKey="ClockSpec.tick_hz" /></span>} subtitle="The least common multiple of every clock: each event lands exactly on a tick"
              actions={<Select value={span} onChange={setSpan} options={["16", "64", "256", "1024"]} label="span (ns)" />}
              explain={<>Each generator has three grids: its <b>DAC sample</b> period, the <b>real-time instruction grid</b> a Play must start on, and the <b>NCO grid</b> phase/frequency updates must land on. A start tick off the grid is a validation error.</>}>
              <TickRuler hw={hw} ns={Number(span)} />
            </Panel>
            <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
              <Panel title="Ports and generators" subtitle="Generators sum on a port; the port checks full scale per I/Q path">
                <div className="space-y-2">
                  {hw.ports.map((p: Json) => (
                    <div key={p.port_id} className="rounded-md border border-line bg-s2/50 p-2.5">
                      <div className="flex flex-wrap items-center gap-2 text-[12px]">
                        <span className="font-mono text-ink">{p.port_id}</span><Badge>{p.kind}</Badge>
                        {p.lo_hz && <span className="num text-mute">LO {fmt(p.lo_hz / 1e9, 3)} GHz</span>}
                        <span className="num text-mute">FS {p.full_scale} · {p.saturation_policy}</span>
                        {!p.verified && <Badge tone="warn">unverified</Badge>}
                      </div>
                      <div className="mt-1.5 flex flex-wrap gap-1.5">
                        {p.generators.map((gid: string) => {
                          const g = hw.generators.find((x: Json) => x.generator_id === gid);
                          return <span key={gid} className="rounded border border-line bg-s1 px-1.5 py-0.5 text-[11px] text-ink2" title={`channels: ${g?.channels.join(", ")}`}>{gid}<span className="ml-1 text-mute">{g?.channels.join(" ")}</span></span>;
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              </Panel>
              <Panel title="Generators" subtitle="Per-sequencer limits the validator enforces">
                <div className="overflow-x-auto">
                  <table className="num w-full text-[11.5px]">
                    <thead className="text-left text-[10.5px] text-mute"><tr>
                      <th className="py-1">generator</th><th>Sa/s</th><th>grid ns <InfoTip docKey="GeneratorSpec.rt_granularity_ticks" /></th><th>min ns</th><th>NCO grid <InfoTip docKey="GeneratorSpec.nco_grid_ticks" /></th><th>wave mem <InfoTip docKey="GeneratorSpec.wave_mem_samples" /></th><th>instr <InfoTip docKey="GeneratorSpec.instr_mem" /></th><th>overlap</th>
                    </tr></thead>
                    <tbody>{hw.generators.map((g: Json) => (
                      <tr key={g.generator_id} className="border-t border-line">
                        <td className="py-1 font-mono text-ink2">{g.generator_id}{g.is_readout && <span className="ml-1 text-accent">RO</span>}</td>
                        <td>{fmt(g.sample_rate_hz / 1e9, 3)}G</td><td>{fmt(g.rt_grid_ns, 2)}</td><td>{fmt(g.min_duration_ns, 2)}</td>
                        <td>{fmt(g.nco_grid_ns, 2)}</td><td>{g.wave_mem_samples} ({fmt(g.wave_mem_us, 1)} µs)</td><td>{g.instr_mem}</td><td>{g.overlap_policy}</td>
                      </tr>))}</tbody>
                  </table>
                </div>
              </Panel>
              <Panel title={<span>Feedback latency <InfoTip docKey="LatencyEntry.latency_ticks" /></span>} subtitle="From the last ADC sample in to the first DAC sample out, readout generator → deciding generator">
                <div className="overflow-x-auto">
                  <table className="num text-[11.5px]">
                    <thead><tr><th className="pr-2 text-left text-[10.5px] text-mute">src \ dst</th>{[...new Set(hw.latency_matrix.map((e: Json) => e.dst))].map((d) => <th key={d as string} className="px-1 text-[10px] font-normal text-mute">{d as string}</th>)}</tr></thead>
                    <tbody>{[...new Set(hw.latency_matrix.map((e: Json) => e.src))].map((s) => (
                      <tr key={s as string}><td className="pr-2 font-mono text-ink2">{s as string}</td>
                        {hw.latency_matrix.filter((e: Json) => e.src === s).map((e: Json) => (
                          <td key={e.dst} className="px-1 text-center" title={`${e.routing}${e.jitter_ticks ? ` ± ${e.jitter_ticks} ticks` : ""}`}>
                            <span className={e.latency_ns === null ? "text-crit" : "text-ink"}>{e.latency_ns === null ? "✕" : fmt(e.latency_ns, 0)}</span>
                          </td>))}
                      </tr>))}</tbody>
                  </table>
                  <p className="mt-2 text-[11px] text-mute">ns · ✕ = no route (a branch there is refused) · hover for the routing class</p>
                </div>
              </Panel>
              <Panel title="Acquisition" subtitle="What the readout inputs can do">
                <KV rows={[
                  ["modes", hw.acquisition.modes.join(", ")], ["discriminated states", hw.acquisition.max_states],
                  ["integration grid", `${fmt(hw.acquisition.integration_grid_ns, 2)} ns`], ["max square window", `${fmt(hw.acquisition.max_square_us, 2)} µs`],
                  ["max weighted window", `${fmt(hw.acquisition.max_weighted_us, 3)} µs`], ["weight sets", hw.acquisition.max_weight_sets],
                  ["min spacing", `${fmt(hw.acquisition.min_spacing_ns, 1)} ns`], ["convention", hw.acquisition.convention],
                  ...Object.entries(hw.tof as Json).map(([c, t]: [string, any]) => [`ToF ${c}`, `${fmt(t.ns, 1)} ns (${t.ticks} ticks)`] as [string, string]),
                ]} />
              </Panel>
            </div>
            <Panel title="Validator rules" subtitle="What is checked, and which profile fields each rule reads">
              <div className="grid grid-cols-1 gap-2 lg:grid-cols-2">
                {hw.rules.map((r: Json) => (
                  <div key={r.rule} className="rounded-md border border-line bg-s2/40 p-2.5 text-[12px]">
                    <div className="font-medium text-ink">{r.rule}</div>
                    <p className="text-ink2">{r.checks}</p>
                    <div className="mt-1 flex flex-wrap gap-1.5">{r.fields.map((f: string) => <span key={f} className="inline-flex items-center gap-1 font-mono text-[10.5px] text-mute">{f.split(".")[1]}<InfoTip docKey={f} /></span>)}</div>
                    <Deep at="source"><div className="mt-1"><SourceRef path={r.source} /></div></Deep>
                  </div>
                ))}
              </div>
            </Panel>
            <Panel title="Channel bindings" subtitle={`How ${wb.device || "the default 5 qubits"} map onto this instrument (round-robin by role)`}>
              <table className="num w-full text-[11.5px]">
                <thead className="text-left text-[10.5px] text-mute"><tr><th className="py-1">channel</th><th>kind</th><th>generator</th><th>port</th><th>frame</th><th>qubits</th></tr></thead>
                <tbody>{hw.bindings.map((b: Json) => <tr key={b.channel_id} className="border-t border-line"><td className="py-0.5 font-mono text-ink">{b.channel_id}</td><td>{b.kind}</td><td>{b.generator_id}</td><td>{b.port_id}</td><td>{b.frame_id}</td><td>{b.qubits.join(", ")}</td></tr>)}</tbody>
              </table>
            </Panel>
          </>
        )}
      </StateBox>
    </div>
  );
}
