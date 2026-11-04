import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api, type Json } from "../api";
import { LineChart } from "../charts";
import { fmtDuration } from "../Shell";
import { useWorkbench } from "../state";
import { Badge, Button, InfoTip, LabBadge, NumberField, Panel, Select, StateBox, Toggle, TruthBadge, cx, fmt } from "../ui";

type Hist = { t: number; f: number[]; t1: number[] };

export function Admin() {
  const qc = useQueryClient();
  const { live } = useWorkbench();
  const cal = useQuery({ queryKey: ["calibration", live?.calibration_epoch], queryFn: () => api.get<Json>("/lab/calibration") });
  const audit = useQuery({ queryKey: ["audit"], queryFn: () => api.get<Json>("/audit"), refetchInterval: 5000 });
  const [qubit, setQubit] = useState(0);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const hist = useRef<Hist[]>([]);
  const [, force] = useState(0);
  useEffect(() => {
    const qs: Json[] | undefined = live?.truth?.qubits;
    if (!qs) return;
    hist.current = [...hist.current.slice(-299), { t: live!.truth.lab_time_s, f: qs.map((q) => q.frequency_hz), t1: qs.map((q) => q.t1_s * 1e6) }];
    force((n) => n + 1);
  }, [live]);
  const act = useMutation({
    mutationFn: (body: Json) => api.post<Json>("/admin/action", body),
    onSuccess: (r) => { setMsg({ ok: true, text: r.done }); qc.invalidateQueries({ queryKey: ["audit"] }); },
    onError: (e) => setMsg({ ok: false, text: String((e as Error).message) }),
  });
  const run = (body: Json, confirmText?: string) => { if (!confirmText || window.confirm(confirmText)) act.mutate(body); };
  const truth: Json[] = live?.truth?.qubits ?? [];
  const props: Json[] = live?.truth?.properties?.qubits ?? [];
  const calq = new Map((cal.data?.qubits ?? []).map((c: Json) => [c.qubit_index, c]));
  const mode = live?.mode;
  const [drift, setDrift] = useState({ df_hz: 200e3, t1_factor: 0.7 });
  const [tls, setTls] = useState({ coupling_hz: 0.5e6, linewidth_hz: 1e6, detuning_hz: 0 });
  const [burst, setBurst] = useState(2e6);
  const [fault, setFault] = useState({ fault: "reboot", count: 1, duration_s: 2 });
  const [jobId, setJobId] = useState("");
  const inspect = useMutation({ mutationFn: (id: string) => api.get<Json>(`/admin/inspect/${id}`) });
  const h = hist.current;
  return (
    <div className="space-y-5">
      <div>
        <h1 className="flex items-center gap-2 text-[18px] font-semibold">Admin console <TruthBadge /></h1>
        <p className="mt-1 max-w-4xl text-[13px] text-ink2">The operator's side door: the admin channel has its own port and token, held by the bridge. It reads the hidden truth and changes the
          lab under the lab's feet: kill or detune qubits, drop a defect into resonance, fire a cosmic ray, misbehave like an instrument. Calibration is <em>not</em> here: only the lab writes it.</p>
      </div>
      <StateBox state={!live ? "loading" : live.truth ? "ok" : "error"} error={live?.admin_error ?? "admin channel unreachable"}>
        <Panel title="Truth vs belief" subtitle={`lab time ${fmtDuration(live?.truth?.lab_time_s ?? 0)} · calibration epoch ${cal.data?.calibration_epoch ?? "—"}`}
          explain={<>Left: what the chip really is right now (<TruthBadge />). Right: what the lab's calibration says (<LabBadge />). The gap is miscalibration: a drive Δ of a few hundred kHz already spoils a π pulse, which is why the technician recalibrates on a schedule.</>}>
          <table className="num w-full text-[12px]">
            <thead className="text-left text-[10.5px] text-mute"><tr><th className="py-1">qubit</th><th>true f01</th><th>calibrated drive</th><th>Δ (kHz)</th><th>true T1</th><th>T2*</th><th>P(1|0)</th><th>P(0|1)</th><th>1q error</th><th>state</th></tr></thead>
            <tbody>{truth.map((t, i) => {
              const c = calq.get(t.qubit_index) as Json | undefined;
              const d = c?.drive_frequency_hz ? (t.frequency_hz - c.drive_frequency_hz) / 1e3 : null;
              const p = props[i] ?? {};
              return (
                <tr key={t.qubit_index} className={cx("border-t border-line", t.dead && "text-crit")}>
                  <td className="py-0.5">q{t.qubit_index}</td><td>{fmt(t.frequency_hz / 1e9, 6)} GHz</td>
                  <td>{c?.drive_frequency_hz ? `${fmt(c.drive_frequency_hz / 1e9, 6)} GHz` : "—"}</td>
                  <td className={d !== null && Math.abs(d) > 100 ? "text-warn" : ""}>{d === null ? "—" : fmt(d, 1)}</td>
                  <td>{fmt(t.t1_s * 1e6, 1)} µs</td><td>{fmt((p.t2_star_s ?? 0) * 1e6, 1)} µs</td>
                  <td>{fmt(p.prob_meas1_prep0, 4)}</td><td>{fmt(p.prob_meas0_prep1, 4)}</td><td>{fmt(p.single_qubit_gate_error, 5)}</td>
                  <td>{t.dead ? <Badge tone="crit">dead</Badge> : <Badge tone="good">alive</Badge>}</td>
                </tr>
              );
            })}</tbody>
          </table>
        </Panel>
        {h.length > 2 && (
          <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
            <Panel title="Live frequency drift" subtitle="True f01 minus its first value in this session, as the lab clock runs">
              <LineChart x={h.map((s) => s.t)} xLabel="lab time (s)" yLabel="Δf (kHz)" height={190}
                lines={truth.map((t, i) => ({ label: `q${t.qubit_index}`, y: h.map((s) => (s.f[i] - h[0].f[i]) / 1e3) }))} />
            </Panel>
            <Panel title="Live T1" subtitle="True T1 per qubit, including scenarios">
              <LineChart x={h.map((s) => s.t)} xLabel="lab time (s)" yLabel="T1 (µs)" height={190}
                lines={truth.map((t, i) => ({ label: `q${t.qubit_index}`, y: h.map((s) => s.t1[i]) }))} />
            </Panel>
          </div>
        )}
        <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
          <Panel title="Scenarios" subtitle="Change the hidden chip now; every action is audited"
            actions={<Select value={String(qubit)} onChange={(v) => setQubit(Number(v))} options={truth.map((t) => String(t.qubit_index))} label="qubit" />}>
            <div className="space-y-4">
              <div className="flex flex-wrap gap-2">
                <Button kind="danger" onClick={() => run({ action: "kill", qubit }, `Kill qubit ${qubit}? It decays within ~100 ns and moves −200 MHz until revived.`)}>Kill qubit</Button>
                <Button onClick={() => run({ action: "revive", qubit })}>Revive</Button>
                <Button onClick={() => run({ action: "freeze", frozen: true })}>Freeze drift</Button>
                <Button onClick={() => run({ action: "freeze", frozen: false })}>Resume drift</Button>
                <Button kind="ghost" onClick={() => run({ action: "clear" }, "Clear every scenario (kills, steps, defects, bursts)?")}>Clear all scenarios</Button>
              </div>
              <div className="flex flex-wrap items-end gap-2 border-t border-line pt-3">
                <NumberField label="Δf" value={drift.df_hz / 1e3} onChange={(v) => setDrift({ ...drift, df_hz: v * 1e3 })} unit="kHz" docKey="DriftStepRequest.delta_frequency_hz" />
                <NumberField label="T1 ×" value={drift.t1_factor} step={0.1} min={0.01} onChange={(v) => setDrift({ ...drift, t1_factor: v })} docKey="DriftStepRequest.t1_factor" />
                <Button onClick={() => run({ action: "drift", qubit, ...drift })}>Drift step</Button>
              </div>
              <div className="flex flex-wrap items-end gap-2 border-t border-line pt-3">
                <NumberField label="g" value={tls.coupling_hz / 1e6} step={0.1} onChange={(v) => setTls({ ...tls, coupling_hz: v * 1e6 })} unit="MHz" docKey="TlsCollisionRequest.coupling_hz" />
                <NumberField label="γ" value={tls.linewidth_hz / 1e6} step={0.1} onChange={(v) => setTls({ ...tls, linewidth_hz: v * 1e6 })} unit="MHz" docKey="TlsCollisionRequest.linewidth_hz" />
                <NumberField label="Δ" value={tls.detuning_hz / 1e6} step={0.1} onChange={(v) => setTls({ ...tls, detuning_hz: v * 1e6 })} unit="MHz" docKey="TlsCollisionRequest.detuning_hz" />
                <Button onClick={() => run({ action: "tls", qubit, ...tls })}>TLS collision</Button>
              </div>
              <div className="flex flex-wrap items-end gap-2 border-t border-line pt-3">
                <NumberField label="peak Γ" value={burst / 1e6} step={0.5} onChange={(v) => setBurst(v * 1e6)} unit="/µs" docKey="BurstRequest.peak_gamma_per_s" />
                <Button onClick={() => run({ action: "burst", qubit, peak_gamma_per_s: burst })}>Cosmic-ray burst</Button>
              </div>
            </div>
          </Panel>
          <div className="space-y-5">
            <Panel title="Live mode" subtitle="How the chassis runs right now (SetMode)">
              {mode && (
                <div className="flex flex-wrap items-end gap-3">
                  <NumberField label="time_scale" value={mode.time_scale} step={1} min={0} docKey="Mode.time_scale" onChange={(v) => Number.isFinite(v) && run({ action: "mode", time_scale: v })} />
                  <Toggle checked={mode.deterministic} onChange={(v) => run({ action: "mode", deterministic: v })} label={<span>deterministic (replay job seeds) <InfoTip docKey="Mode.deterministic" /></span>} />
                  <Select value={tierName(mode.tier_policy)} onChange={(v) => run({ action: "mode", tier: v })} options={["requested", "auto", "t0", "t1a", "t1b", "t2"]} label={<span>tier policy <InfoTip docKey="Mode.tier_policy" /></span>} />
                  <span className="text-[11px] text-mute">global seed {live?.global_seed}</span>
                </div>
              )}
            </Panel>
            <Panel title="Instrument faults" subtitle="Make the instrument misbehave on the lab link; clients see only a bare 'instrument fault'">
              <div className="flex flex-wrap items-end gap-2">
                <Select value={fault.fault} onChange={(v) => setFault({ ...fault, fault: v })} options={["hang", "drop", "reboot", "slow_upload"]} label={<span>fault <InfoTip docKey="InjectInstrumentFaultRequest.fault" /></span>} />
                <NumberField label="count" value={fault.count} onChange={(v) => setFault({ ...fault, count: v })} min={1} width="w-16" />
                <NumberField label="duration" value={fault.duration_s} onChange={(v) => setFault({ ...fault, duration_s: v })} unit="s" width="w-16" />
                <Button kind="danger" onClick={() => run({ action: "fault", ...fault }, `Inject ${fault.fault}? Running jobs may fail.`)}>Inject</Button>
                <Button onClick={() => run({ action: "clear_faults" })}>Clear faults</Button>
              </div>
            </Panel>
            <Panel title="Inspect a job" subtitle="The real tier, noise fidelity and failure reason, hidden from the lab">
              <div className="flex gap-2">
                <input value={jobId} onChange={(e) => setJobId(e.target.value)} placeholder="job id (see Lab bench)" aria-label="job id" className="h-7 flex-1 rounded-md border border-line bg-s2 px-2 text-[12px]" />
                <Button onClick={() => inspect.mutate(jobId)} disabled={!jobId}>Inspect</Button>
              </div>
              {inspect.data && <pre className="num mt-2 overflow-x-auto rounded bg-bg p-2 text-[11px] text-ink2">{JSON.stringify(inspect.data, null, 2)}</pre>}
              {inspect.error && <p className="mt-2 text-[12px] text-crit">{String((inspect.error as Error).message)}</p>}
            </Panel>
          </div>
        </div>
        {msg && <p role="status" className={cx("text-[12px]", msg.ok ? "text-good" : "text-crit")}>{msg.ok ? "✓" : "✕"} {msg.text}</p>}
        <Panel title="Audit log" subtitle="Every admin action, config save, calibration write and restart (workspace/audit.log)">
          <ul className="num max-h-56 space-y-0.5 overflow-y-auto text-[11.5px]">
            {[...(audit.data?.entries ?? [])].reverse().map((e: Json, i: number) => (
              <li key={i} className={e.ok ? "text-ink2" : "text-crit"}>{new Date(e.ts * 1000).toLocaleTimeString()} · {e.action} {JSON.stringify(e.args)} · {e.result}</li>
            ))}
            {!audit.data?.entries?.length && <li className="text-mute">No actions yet.</li>}
          </ul>
        </Panel>
      </StateBox>
    </div>
  );
}

function tierName(t: string | undefined): string {
  if (!t || t === "FIDELITY_TIER_UNSPECIFIED") return "requested";
  return t.replace("FIDELITY_TIER_", "").split("_")[0].toLowerCase();
}
