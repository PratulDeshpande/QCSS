import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, type Json } from "../api";
import { IQScatter, LineChart } from "../charts";
import { Badge, Button, KV, LabBadge, NumberField, Panel, Select, StateBox, fmt } from "../ui";

export type ExpParams = { kind: string; qubit: number; points: number; shots: number; tier: string; pi_amplitude?: number; max_delay_us?: number; detuning_mhz?: number; span_mhz?: number };

export function ExperimentForm({ p, set }: { p: ExpParams; set: (p: ExpParams) => void }) {
  const ex = useQuery({ queryKey: ["experiments"], queryFn: () => api.get<Json>("/experiments") });
  const meta = ex.data?.experiments?.[p.kind];
  const num = (k: keyof ExpParams, label: string, unit?: string, step?: number) => (
    <NumberField label={label} unit={unit} step={step} value={(p[k] as number) ?? NaN} width="w-20"
      onChange={(v) => set({ ...p, [k]: Number.isFinite(v) ? v : undefined })} />
  );
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-end gap-3">
        <Select value={p.kind} onChange={(k) => set({ ...p, kind: k })} label="experiment"
          options={Object.entries(ex.data?.experiments ?? {}).map(([k, v]: [string, any]) => ({ value: k, label: v.name }))} />
        <Select value={String(p.qubit)} onChange={(v) => set({ ...p, qubit: Number(v) })} options={["0", "1", "2", "3", "4"]} label="qubit" />
        {num("points", "points")}{num("shots", "shots")}
        <Select value={p.tier} onChange={(t) => set({ ...p, tier: t })} options={["AUTO", "T0", "T1A", "T1B", "T2"]} label="tier" />
        {p.kind !== "rabi" && num("pi_amplitude", "π amplitude (blank = estimate)", "FS", 0.01)}
        {(p.kind === "t1" || p.kind === "ramsey") && num("max_delay_us", "max delay", "µs")}
        {p.kind === "ramsey" && num("detuning_mhz", "virtual detuning", "MHz", 0.1)}
        {p.kind === "spectroscopy" && num("span_mhz", "span ±", "MHz")}
      </div>
      {meta && <p className="text-[12px] text-ink2"><b>{meta.name}</b> measures {meta.measures}. {meta.summary}</p>}
    </div>
  );
}

/** The plot and fit of one experiment run (lab or sandbox). */
export function ExperimentResult({ r, label, color = 0 }: { r: Json; label?: string; color?: number }) {
  const x: number[] = r.axis.values;
  if (r.kind === "single_shot") {
    return (
      <div className="space-y-3">
        <IQScatter clouds={[{ label: "prepared |0⟩", points: r.iq["0"] }, { label: "prepared |1⟩", points: r.iq["1"] }]}
          threshold={r.fit?.threshold !== undefined ? { rotation: r.fit.rotation_rad, value: r.fit.threshold } : undefined} centroids={r.fit?.centers} />
        <FitKV r={r} />
      </div>
    );
  }
  const curve: number[] | undefined = r.fit?.curve;
  const xs = curve ? curve.map((_, i) => x[0] + (i / (curve.length - 1)) * (x[x.length - 1] - x[0])) : [];
  const merged = [...new Set([...x, ...xs])].sort((a, b) => a - b);
  const at = (arr: number[], src: number[]) => merged.map((v) => { const i = src.indexOf(v); return i >= 0 ? arr[i] : null; });
  return (
    <div className="space-y-3">
      <LineChart x={merged} xLabel={`${r.axis.name}${r.axis.unit ? ` (${r.axis.unit})` : ""}`} yLabel="P(|1⟩)" height={240} yRange={[0, 1]}
        lines={[{ label: label ?? "measured", y: at(r.p1, x), points: true, color, width: 0.001 }, ...(curve ? [{ label: "fit", y: at(curve, xs), color: color + 1 }] : [])]} />
      <FitKV r={r} />
    </div>
  );
}

function FitKV({ r }: { r: Json }) {
  const f = r.fit ?? {};
  const rows: [string, string][] = Object.entries(f).filter(([k]) => k !== "curve" && k !== "centers").map(([k, v]) => [k.replaceAll("_", " "), typeof v === "number" ? fmt(v, 4) : String(v)]);
  rows.push(["tier", r.tier ?? "(chosen by the chassis; see Admin › inspect)"], ["shots", String(r.shots)], ["elapsed", `${fmt(r.elapsed_s, 2)} s`]);
  if (r.job_id) rows.push(["job id", r.job_id]);
  if (r.warnings?.length) rows.push(["warnings", r.warnings.join("; ")]);
  return <KV rows={rows} />;
}

export function LabBench() {
  const [p, setP] = useState<ExpParams>({ kind: "rabi", qubit: 0, points: 21, shots: 300, tier: "AUTO" });
  const run = useMutation({ mutationFn: () => api.post<Json>("/lab/run", p) });
  const jobs = useQuery({ queryKey: ["labjobs", run.data], queryFn: () => api.get<Json>("/lab/jobs"), refetchInterval: run.isPending ? 1000 : false });
  const describe = useQuery({ queryKey: ["describe"], queryFn: () => api.get<Json>("/lab/describe") });
  return (
    <div className="space-y-5">
      <div>
        <h1 className="flex items-center gap-2 text-[18px] font-semibold">Lab bench <LabBadge /></h1>
        <p className="mt-1 max-w-4xl text-[13px] text-ink2">Experiments submitted over the lab link exactly as Qibolab or Qibocal would: built from the hardware profile and the calibration a
          client can read, never from the truth. Jobs take real instrument time (lab clock × time_scale), results arrive as streamed chunks, and the chip may have drifted since calibration.
          Compare the fitted numbers with the Admin console's truth.</p>
      </div>
      <Panel title="Experiment" subtitle={describe.data ? `instrument: ${describe.data.profile_name} (${describe.data.vendor}) · ${describe.data.channels?.length} channels` : "DescribeDevice…"}
        actions={<Button kind="primary" onClick={() => run.mutate()} disabled={run.isPending}>{run.isPending ? "Running on the instrument…" : "▶ Submit to the lab"}</Button>}>
        <ExperimentForm p={p} set={setP} />
      </Panel>
      <Panel title="Result" subtitle="What the lab measured">
        <StateBox state={run.isPending ? "loading" : run.isError ? "error" : run.data ? "ok" : "empty"} error={run.error}
          empty={<>Submit an experiment. With time_scale 1 a Rabi takes a few seconds of real time: the repetition delay is 10 × T1 per shot.</>}>
          {run.data && <ExperimentResult r={run.data} />}
        </StateBox>
      </Panel>
      <Panel title="Jobs submitted from this dashboard" subtitle="QCSS has no ListJobs RPC: the bridge remembers what it submitted">
        <table className="num w-full text-[11.5px]">
          <thead className="text-left text-[10.5px] text-mute"><tr><th className="py-1">job id</th><th>experiment</th><th>qubit</th><th>state</th><th>epoch</th><th>elapsed</th><th>message</th></tr></thead>
          <tbody>{[...(jobs.data?.jobs ?? [])].reverse().map((j: Json) => (
            <tr key={j.job_id} className="border-t border-line"><td className="py-0.5 text-ink2">{j.job_id}</td><td>{j.kind}</td><td>{j.qubit}</td>
              <td><Badge tone={j.state === "JOB_STATE_COMPLETED" ? "good" : j.state?.includes("FAIL") ? "crit" : "neutral"}>{String(j.state).replace("JOB_STATE_", "")}</Badge></td>
              <td>{j.calibration_epoch}</td><td>{j.elapsed_s ? `${fmt(j.elapsed_s, 2)} s` : "…"}</td><td className="text-mute">{j.message}</td></tr>))}</tbody>
        </table>
      </Panel>
    </div>
  );
}
