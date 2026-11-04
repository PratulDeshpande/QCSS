// Program & compiler, Physics & tiers, Feedback & timing: three windows onto one sandbox run of a real job.
import { useEffect, useState } from "react";
import { Bloch, Gantt, Heatmap, LineChart, type GanttRow } from "../charts";
import { useWorkbench } from "../state";
import { Badge, Button, Deep, Equation, InfoTip, KV, Panel, SourceRef, Stat, fmt } from "../ui";
import { DraftNote, NeedsRun, RunBar } from "./common";
import type { Json } from "../api";

const KIND_COLOR: Record<string, number> = { play: 0, acquire: 2, branch: 4, "frame:shift": 6, "frame:set": 6, "frame:reset": 6, "frame:freq": 3 };

function Title({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h1 className="text-[18px] font-semibold">{title}</h1>
      <p className="mt-1 max-w-4xl text-[13px] leading-relaxed text-ink2">{children}</p>
    </div>
  );
}

function JobEditor() {
  const { wb, set } = useWorkbench();
  const [text, setText] = useState("");
  const [err, setErr] = useState("");
  useEffect(() => { setText(wb.job ? JSON.stringify(wb.job, null, 2) : ""); }, [wb.job]);
  const apply = () => {
    try { set({ job: JSON.parse(text), jobName: wb.jobName.endsWith("(edited)") ? wb.jobName : `${wb.jobName} (edited)` }); setErr(""); }
    catch (e) { setErr(String((e as Error).message)); }
  };
  return (
    <Panel title={<span>Job (protobuf JSON) <InfoTip docKey="Job.num_shots" /></span>} subtitle="The exact message a lab client submits; edit and re-run to see the validator's verdict"
      actions={<Button onClick={apply}>Apply edits</Button>}>
      <textarea value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} aria-label="Job JSON"
        className="num h-72 w-full resize-y rounded-md border border-line bg-bg p-2 text-[11.5px] leading-snug" />
      {err && <p className="mt-1 text-[12px] text-crit">{err}</p>}
    </Panel>
  );
}

export function Program() {
  return (
    <div className="space-y-5">
      <Title title="Program & compiler">A job becomes a Program: waveforms are synthesized per generator, sweeps expand into points, every
        instruction lands on a channel bound to a generator, port and frame, and the validator checks every hardware rule. Pick a sweep point to
        see that point's program.</Title>
      <RunBar />
      <DraftNote />
      <div className="grid grid-cols-1 gap-5 2xl:grid-cols-[1fr_420px]">
        <NeedsRun>{(d) => <ProgramResult d={d} />}</NeedsRun>
        <JobEditor />
      </div>
    </div>
  );
}

function ProgramResult({ d }: { d: Json }) {
  const ops: Json[] = d.program.ops;
  const gantt: GanttRow[] = ops.map((o) => ({
    row: o.channel_id ?? o.frame_id ?? o.kind, start: o.start_ns, end: o.start_ns + Math.max(o.duration_ns, 0.5),
    label: o.kind === "play" ? `${o.waveform_id} ×${fmt(o.amplitude, 2)}` : o.kind, color: KIND_COLOR[o.kind] ?? 7,
    marker: !o.duration_ns, note: o.path,
  }));
  const wfs = Object.entries(d.waveforms as Json);
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-4 rounded-lg border border-line bg-s1 p-4 md:grid-cols-5">
        <Stat label="sweep points" value={d.plan.n_points} hint={`showing point ${d.plan.point} ${JSON.stringify(d.plan.indices)}`} />
        <Stat label="program length" value={fmt(d.program.duration_ns, 1)} unit="ns" />
        <Stat label="qubits simulated" value={d.plan.qubits.join(", ")} />
        <Stat label="calibration epoch" value={d.plan.epoch} hint="pinned at planning" />
        <Stat label="warnings" value={d.warnings.length} tone={d.warnings.length ? "warn" : "good"} />
      </div>
      {d.warnings.length > 0 && <ul className="text-[12px] text-warn">{d.warnings.map((w: string) => <li key={w}>⚠ {w}</li>)}</ul>}
      <Panel title="Program timeline" subtitle="Absolute start ticks per channel, in ns; hover for the proto field path">
        <Gantt items={gantt} />
      </Panel>
      <Panel title="Instructions" subtitle="The compiled IR, with the generator, port and frame each one runs on">
        <div className="overflow-x-auto">
          <table className="num w-full text-[11.5px]">
            <thead className="text-left text-[10.5px] text-mute"><tr><th className="py-1">path</th><th>op</th><th>channel → generator / port / frame</th><th>start ns</th><th>dur ns</th><th>detail</th></tr></thead>
            <tbody>{ops.map((o, i) => (
              <tr key={i} className="border-t border-line">
                <td className="py-0.5 text-mute">{o.path}{o.arm && ` (${o.arm})`}</td><td className="text-ink">{o.kind}</td>
                <td>{o.channel_id ?? o.frame_id} {o.generator_id && <span className="text-mute">→ {o.generator_id} / {o.port_id} / {o.frame_id}</span>}</td>
                <td>{fmt(o.start_ns, 2)}</td><td>{fmt(o.duration_ns, 2)}</td>
                <td className="text-ink2">{o.kind === "play" ? `${o.waveform_id} A=${fmt(o.amplitude, 3)} φ=${fmt(o.phase_offset, 3)}` : o.kind === "acquire" ? `${o.mode} → r${o.register} "${o.result_key}"` : o.value !== undefined ? fmt(o.value, 4) : ""}</td>
              </tr>))}</tbody>
          </table>
        </div>
      </Panel>
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        {wfs.map(([id, w]: [string, any]) => (
          <Panel key={id} title={`Waveform “${id}”`} subtitle={`${w.i.length} samples × ${fmt(w.dt_ns, 3)} ns on ${w.generator_id}`}
            explain={<Deep at="expert"><span>{JSON.stringify(w.spec)}</span></Deep>}>
            <LineChart x={w.i.map((_: number, k: number) => k * w.dt_ns)} lines={[{ label: "I (in-phase)", y: w.i }, { label: "Q (quadrature, e.g. DRAG)", y: w.q }]}
              xLabel="time (ns)" yLabel="envelope" height={180} />
          </Panel>
        ))}
        {Object.entries(d.ports as Json).map(([pid, p]: [string, any]) => (
          <Panel key={pid} title={<span>Port {pid} stream <InfoTip docKey="PortSpec.full_scale_per_path" /></span>}
            subtitle={`peak ${fmt(p.peak, 3)} of full scale ${p.full_scale} (${p.policy})`}
            explain={<>The validator sums every generator on the port after NCO modulation and checks |I| and |Q| separately against full scale. {p.peak > p.full_scale ? <b className="text-crit">This point saturates.</b> : "This point stays within range."}</>}>
            <LineChart x={p.t_ns} lines={[{ label: "I", y: p.i }, { label: "Q", y: p.q }, { label: "+full scale", y: p.t_ns.map(() => p.full_scale), dash: true, color: 7, width: 1 }]}
              xLabel="time (ns)" yLabel="DAC (FS)" height={180} />
          </Panel>
        ))}
      </div>
    </div>
  );
}

const TIER_CARDS = [
  { id: "T0", name: "Surrogate", limit: "any size", what: "Classical bits; lifted gates move populations via |U|², T1 decay only. Fastest.", src: "src/qcss/physics/surrogate_t0.py" },
  { id: "T1A", name: "Stabilizer (Stim)", limit: "Clifford circuits", what: "Nearest Clifford plus a Pauli-twirled residual; idle noise from Ghosh PTA. Scales to surface codes.", src: "src/qcss/physics/stim_t1a.py" },
  { id: "T1B", name: "Statevector", limit: "≤ 26 qubits", what: "Exact gates with quantum-jump amplitude damping (T1 up/down) and dephasing.", src: "src/qcss/physics/statevector_t1b.py" },
  { id: "T2", name: "Lindblad qutrits", limit: "≤ 4 qutrits", what: "Pulse-level master equation with leakage to |2⟩, couplings and flux; required for leaky pulses, overlapping pulses and raw traces.", src: "src/qcss/physics/lindblad_t2.py" },
];

export function Physics() {
  return (
    <div className="space-y-5">
      <Title title="Physics & tiers">A planning dry run lifts every pulse into the gate it performs. The router then picks the cheapest engine that is
        still faithful. Leakage above 0.03, overlapping pulses on a shared qubit, raw-trace readout or more than 26 qubits push a job up the ladder.</Title>
      <RunBar />
      <DraftNote />
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
        {TIER_CARDS.map((t) => <TierCard key={t.id} t={t} />)}
      </div>
      <NeedsRun>{(d) => <PhysicsResult d={d} />}</NeedsRun>
    </div>
  );
}

function TierCard({ t }: { t: (typeof TIER_CARDS)[number] }) {
  const { explain } = useWorkbench();
  const active = explain.data?.plan?.tier === t.id;
  return (
    <div className={`rounded-lg border p-3 ${active ? "border-accent bg-accent/10" : "border-line bg-s1"}`}>
      <div className="flex items-center gap-2"><Badge tone={active ? "accent" : "neutral"}>{t.id}</Badge><span className="text-[12.5px] font-semibold">{t.name}</span><span className="ml-auto text-[11px] text-mute">{t.limit}</span></div>
      <p className="mt-1.5 text-[12px] leading-snug text-ink2">{t.what}</p>
      <Deep at="source"><div className="mt-1"><SourceRef path={t.src} /></div></Deep>
      {active && <p className="mt-1.5 text-[11.5px] text-accent">chosen for this job: {explain.data?.plan?.reason}</p>}
    </div>
  );
}

function PhysicsResult({ d }: { d: Json }) {
  const st = d.state;
  const tr = st.trajectory;
  const q0 = st.qubits[0];
  const pts: Json[] = d.results.points;
  const keys = Object.keys(pts[0]?.p1 ?? {});
  const lift: Json[] = d.lift;
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1fr_300px]">
        <Panel title="State through the pulses" subtitle={`Re-evolved slice by slice on the Lindblad (T2) engine, qubit ${q0}`}
          explain={<>Populations of |0⟩, |1⟩ and the leakage level |2⟩ while the drive plays. A π pulse moves population from |0⟩ to |1⟩; a short pulse without DRAG leaks into |2⟩ because the 1–2 transition is only E<sub>C</sub> away.</>}>
          {tr.t_ns.length ? (
            <LineChart x={tr.t_ns} xLabel="time (ns)" yLabel="population" height={220} yRange={[0, 1]}
              lines={[0, 1, 2].map((lv) => ({ label: `P(|${lv}⟩)`, y: tr.populations.map((p: number[][]) => p[0][lv]) }))} />
          ) : <p className="text-[12px] text-mute">{tr.note}</p>}
        </Panel>
        <Panel title="Bloch sphere" subtitle="qubit subspace of the qutrit">
          {tr.bloch?.length ? <Bloch vec={tr.bloch[tr.bloch.length - 1][0]} path={tr.bloch.map((b: number[][]) => b[0])} label={`q${q0} at end of drive ·`} />
            : st.bloch ? <Bloch vec={st.bloch[0]} label={`q${q0}`} /> : <p className="text-[12px] text-mute">Bloch view needs the T2 engine.</p>}
        </Panel>
      </div>
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <Panel title="Before readout" subtitle={`Populations from the ${st.tier} engine with acquisitions removed`}>
          <Heatmap m={st.populations} rowLabels={st.qubits.map((q: number) => `q${q}`)} colLabels={["|0⟩", "|1⟩", "|2⟩"]} title="P(level)" />
          {st.rho_abs && <div className="mt-3"><Heatmap m={st.rho_abs} rowLabels={st.rho_abs.map((_: unknown, i: number) => `${i}`)} colLabels={st.rho_abs.map((_: unknown, i: number) => `${i}`)} title="|ρ| (density matrix magnitudes)" digits={2} /></div>}
        </Panel>
        <Panel title={<span>Lifted gates <InfoTip docKey="Job.requested_tier" /></span>} subtitle="What each pulse actually did, from the planning dry run (gate tiers)">
          {lift.length === 0 ? <p className="text-[12px] text-mute">No lifts: this job runs pulse-level (T2) or has no drive.</p> : (
            <div className="space-y-3">
              {lift.slice(0, 6).map((e, i) => (
                <div key={i} className="flex flex-wrap items-start gap-4 border-t border-line pt-2 first:border-0 first:pt-0">
                  <KV rows={[["pulse", e.name], ["qubits", e.qubits.join(", ")], ["time", `${fmt(e.t_start_ns, 1)}–${fmt(e.t_end_ns, 1)} ns`],
                    ["leakage", <span className={e.leakage > 0.03 ? "text-crit" : "text-good"}>{fmt(e.leakage, 5)} {e.leakage > 0.03 ? "> 0.03 → T2" : "≤ 0.03"}</span>],
                    ["nearest Clifford", e.is_clifford ? `F = ${fmt(e.clifford_fidelity, 5)}` : "none ≥ 0.99"]]} />
                  {e.unitary.length <= 4 && <Heatmap m={e.unitary.map((r: number[][]) => r.map(([re, im]) => Math.hypot(re, im)))} rowLabels={e.unitary.map((_: unknown, k: number) => `${k}`)} colLabels={e.unitary.map((_: unknown, k: number) => `${k}`)} title="|U|" digits={2} />}
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>
      <Panel title="Measured outcome per sweep point" subtitle={`${d.results.shots} shots each, chunked and streamed exactly as the chassis does`}>
        <LineChart x={pts.map((_: Json, i: number) => i)} xLabel="sweep point" yLabel="P(label ≥ 1)" height={200} yRange={[0, 1]}
          lines={keys.map((k) => ({ label: k, y: pts.map((p) => p.p1[k]), points: true }))} />
      </Panel>
    </div>
  );
}

export function Timing() {
  return (
    <div className="space-y-5">
      <Title title="Feedback & timing">Every shot is one discrete-event timeline in integer ticks. Same-tick events are ordered frame update &lt;
        acquisition complete &lt; branch decision &lt; playback. A measurement result exists only after time of flight plus integration, and a branch can
        use it only after the routing latency.</Title>
      <RunBar />
      <NeedsRun>{(d) => <TimingResult d={d} />}</NeedsRun>
    </div>
  );
}

function TimingResult({ d }: { d: Json }) {
  const shot = d.shot;
  const items: GanttRow[] = [
    ...d.program.ops.filter((o: Json) => o.kind === "play" || o.kind === "acquire").map((o: Json) => ({
      row: o.channel_id, start: o.start_ns, end: o.start_ns + o.duration_ns, label: o.kind === "play" ? o.waveform_id : "integrate", color: KIND_COLOR[o.kind], note: o.path })),
    ...shot.timeline.map((e: Json) => ({ row: "events", start: e.ns, end: e.ns, label: e.event, color: e.event.startsWith("acq_done") ? 2 : e.event.startsWith("branch") ? 4 : 0, marker: true })),
  ];
  const acq = d.program.ops.find((o: Json) => o.kind === "acquire");
  const done = shot.acquisitions[0];
  const segs: Json[] = shot.segments.filter((s: Json) => s.kind === "drive");
  return (
    <div className="space-y-5">
      <Panel title="One shot, recorded" subtitle={`Shot ends at ${fmt(shot.end_ns, 1)} ns; hover markers for each event`}>
        <Gantt items={items} />
        <ul className="num mt-3 grid grid-cols-1 gap-x-6 text-[11.5px] text-ink2 md:grid-cols-2">
          {shot.timeline.map((e: Json, i: number) => <li key={i}><span className="text-mute">{fmt(e.ns, 2)} ns</span> · {e.event}</li>)}
        </ul>
      </Panel>
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <Panel title="When is a result available?" subtitle="The validator and executor use the same arithmetic"
          explain={<Equation block tex={"t_{ready} = t_{acq} + ToF + T_{int},\\qquad t_{decision} \\ge t_{ready} + latency(src \\to dst)"} />}>
          {acq && done ? (
            <KV rows={[["acquisition starts", `${fmt(acq.start_ns, 2)} ns`], ["integration", `${fmt(acq.duration_ns, 2)} ns`],
              ["result ready (incl. ToF)", `${fmt(done.end_ns, 2)} ns`], ["implied ToF", `${fmt(done.end_ns - acq.start_ns - acq.duration_ns, 2)} ns`],
              ["true level → label", `${done.level} → ${done.label}`], ["IQ", `${fmt(done.iq[0], 4)}, ${fmt(done.iq[1], 4)}`]]} />
          ) : <p className="text-[12px] text-mute">No acquisition in this job.</p>}
          <p className="mt-2 text-[11.5px] text-mute">The feedback latency matrix is on the Hardware & timing view.</p>
        </Panel>
        <Panel title="What the qubit saw" subtitle="Rendered drive Ω(t) after NCO, mixers and LO, in the qubit's rotating frame"
          explain={<Deep at="expert"><span>Ω is in rad/ns; |Ω|/2π is the instantaneous Rabi frequency. With ideal mixers this is the envelope times the frame phase; hidden mixer errors add an image term.</span></Deep>}>
          {segs.length ? <LineChart x={segs[0].t_ns} xLabel="time (ns)" yLabel="Ω (rad/ns)" height={200}
            lines={[{ label: "Re Ω", y: segs[0].re }, { label: "Im Ω", y: segs[0].im }]} /> : <p className="text-[12px] text-mute">No drive segment rendered.</p>}
        </Panel>
      </div>
    </div>
  );
}
