import { useState } from "react";
import { api, type Json } from "../api";
import { LineChart } from "../charts";
import { useRegistry } from "../registry";
import { useWorkbench } from "../state";
import { Badge, Button, FieldExplain, NumberField, Panel, Select, StateBox, Tabs, fmt } from "../ui";
import { ExperimentForm, ExperimentResult, type ExpParams } from "./LabBench";

type Override = { model: string; field: string; qubit: number; value: number };
const SWEEPABLE = ["QubitSpec", "ResonatorSpec", "DynamicsSpec", "CouplerSpec"];

function applyOverride(data: Json, o: Override): Json {
  const d = structuredClone(data);
  const pick = (arr: Json[] | undefined) => arr?.find((x) => x.qubit_index === o.qubit || x.qubit_pair?.[0] === o.qubit);
  const target = o.model === "QubitSpec" ? pick(d.qubits) : o.model === "ResonatorSpec" ? pick(d.resonators)
    : o.model === "CouplerSpec" ? pick(d.couplers) : o.model === "DynamicsSpec" ? d.dynamics : undefined;
  if (!target) throw new Error(`device has no ${o.model} for qubit ${o.qubit}`);
  target[o.field] = o.value;
  return d;
}

async function runWith(body: Json, device: string, overrides: Override[]): Promise<Json> {
  let yaml: string | undefined;
  if (overrides.length) {
    const base = await api.get<Json>(`/configs/device/${device}`);
    let data = base.data;
    for (const o of overrides) data = applyOverride(data, o);
    yaml = (await api.post<Json>("/configs/device/dump", { data })).yaml;
  }
  return api.post<Json>("/sandbox/experiment", { ...body, device, device_yaml: yaml });
}

function FactorPicker({ o, set }: { o: Override; set: (o: Override) => void }) {
  const { reg, byKey } = useRegistry();
  const fields = (reg?.fields ?? []).filter((f) => SWEEPABLE.includes(f.model) && (f.type === "float" || f.type === "int") && !f.field.endsWith("index") && !f.inert);
  const doc = byKey.get(`${o.model}.${o.field}`);
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-end gap-3">
        <Select value={`${o.model}.${o.field}`} onChange={(k) => { const [m, f] = k.split("."); set({ ...o, model: m, field: f }); }} label="factor"
          options={fields.map((f) => ({ value: f.key, label: `${f.model}.${f.field}${f.unit ? ` (${f.unit})` : ""}` }))} />
        {o.model !== "DynamicsSpec" && <Select value={String(o.qubit)} onChange={(v) => set({ ...o, qubit: Number(v) })} options={["0", "1", "2", "3", "4"]} label="of qubit" />}
      </div>
      {doc && <div className="rounded border border-line bg-s2/40 p-2"><FieldExplain doc={doc} compact /></div>}
    </div>
  );
}

function Compare({ exp }: { exp: ExpParams }) {
  const { wb } = useWorkbench();
  const [o, setO] = useState<Override>({ model: "QubitSpec", field: "t1_us", qubit: exp.qubit, value: 20 });
  const [state, setState] = useState<{ a?: Json; b?: Json; err?: unknown; busy: boolean }>({ busy: false });
  const go = async () => {
    setState({ busy: true });
    try {
      const body = { ...exp, profile: wb.profile, seed: 7 };
      const a = await runWith(body, wb.device, []);
      const b = await runWith(body, wb.device, [{ ...o, qubit: exp.qubit }]);
      setState({ a, b, busy: false });
    } catch (e) { setState({ err: e, busy: false }); }
  };
  return (
    <Panel title="A/B: change one factor" subtitle="Same experiment, same seed: the only difference is the factor you change"
      actions={<Button kind="primary" onClick={go} disabled={state.busy}>{state.busy ? "Simulating A and B…" : "▶ Compare"}</Button>}>
      <div className="flex flex-wrap items-end gap-4">
        <FactorPicker o={o} set={setO} />
        <NumberField label="B value" value={o.value} onChange={(v) => setO({ ...o, value: v })} />
      </div>
      <div className="mt-4">
        <StateBox state={state.busy ? "loading" : state.err ? "error" : state.a ? "ok" : "empty"} error={state.err} empty="Pick a factor and a value for B.">
          {state.a && state.b && (
            <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
              <div><Badge>A · {wb.device} as shipped</Badge><ExperimentResult r={state.a} label="A" /></div>
              <div><Badge tone="accent">B · {o.model}.{o.field} = {o.value}</Badge><ExperimentResult r={state.b} label="B" color={2} /></div>
            </div>
          )}
        </StateBox>
      </div>
    </Panel>
  );
}

function Sweep({ exp }: { exp: ExpParams }) {
  const { wb } = useWorkbench();
  const { byKey } = useRegistry();
  const [o, setO] = useState<Override>({ model: "QubitSpec", field: "t1_us", qubit: exp.qubit, value: 0 });
  const [values, setValues] = useState("10, 20, 40, 80");
  const [out, setOut] = useState<{ v: number; r: Json }[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const go = async () => {
    setBusy(true); setErr(null); setOut([]);
    const vs = values.split(",").map((s) => Number(s.trim())).filter(Number.isFinite).slice(0, 8);
    try {
      const acc: { v: number; r: Json }[] = [];
      for (const v of vs) {
        acc.push({ v, r: await runWith({ ...exp, profile: wb.profile, seed: 7 }, wb.device, [{ ...o, qubit: exp.qubit, value: v }]) });
        setOut([...acc]);
      }
    } catch (e) { setErr(e); }
    setBusy(false);
  };
  const metrics = out[0] ? Object.keys(out[0].r.fit ?? {}).filter((k) => typeof out[0].r.fit[k] === "number") : [];
  const [metric, setMetric] = useState("");
  const m = metric || metrics[0];
  const doc = byKey.get(`${o.model}.${o.field}`);
  return (
    <Panel title="Sweep a simulator factor" subtitle="Run the experiment once per value and plot what the lab would measure"
      actions={<Button kind="primary" onClick={go} disabled={busy}>{busy ? `Simulating ${out.length + 1}…` : "▶ Sweep"}</Button>}>
      <div className="flex flex-wrap items-end gap-4">
        <FactorPicker o={o} set={setO} />
        <label className="flex flex-col gap-1 text-[11px] text-mute">values (comma separated, ≤ 8)<input value={values} onChange={(e) => setValues(e.target.value)} className="num h-7 w-56 rounded-md border border-line bg-s2 px-2 text-[12px] text-ink" /></label>
      </div>
      <div className="mt-4">
        <StateBox state={err ? "error" : out.length ? "ok" : busy ? "loading" : "empty"} error={err} empty="Each value is a full sandbox run of the experiment with that chip.">
          <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
            <div>
              <Select value={m ?? ""} onChange={setMetric} options={metrics} label="fitted metric" />
              {m && <LineChart x={out.map((o2) => o2.v)} xLabel={`${o.field}${doc?.unit ? ` (${doc.unit})` : ""}`} yLabel={m} height={240}
                lines={[{ label: m, y: out.map((o2) => o2.r.fit?.[m] ?? null), points: true }]} />}
            </div>
            <div>
              {out.length > 0 && out[0].r.kind !== "single_shot" && (
                <LineChart x={out[0].r.axis.values} xLabel={out[0].r.axis.name} yLabel="P(|1⟩)" height={240} yRange={[0, 1]}
                  lines={out.map((o2) => ({ label: `${o.field} = ${fmt(o2.v, 3)}`, y: o2.r.p1 }))} />
              )}
            </div>
          </div>
        </StateBox>
      </div>
    </Panel>
  );
}

export function WhatIf() {
  const [tab, setTab] = useState<"compare" | "sweep">("compare");
  const [exp, setExp] = useState<ExpParams>({ kind: "t1", qubit: 0, points: 11, shots: 300, tier: "T1B" });
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-[18px] font-semibold">What-if lab</h1>
        <p className="mt-1 max-w-4xl text-[13px] text-ink2">Change any physical factor of the chip and see what a lab would measure. Every run is a full QCSS simulation in the sandbox
          (fixed seed, frozen chip), so differences come from the factor alone. Shipped files are never modified: overrides travel as an in-memory draft.</p>
      </div>
      <Panel title="Experiment" subtitle="What to measure in every run"><ExperimentForm p={exp} set={setExp} /></Panel>
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "compare", label: "A/B compare" }, { id: "sweep", label: "Sweep a factor" }]} />
      {tab === "compare" ? <Compare exp={exp} /> : <Sweep exp={exp} />}
    </div>
  );
}
