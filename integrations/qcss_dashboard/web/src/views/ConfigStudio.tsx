import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, type Json } from "../api";
import { useRegistry, type FieldDoc, type Registry } from "../registry";
import { useWorkbench } from "../state";
import {
  Badge, Button, Deep, FieldExplain, InfoTip, LabBadge, NumberField, Panel, Select, StateBox, Tabs, TruthBadge, cx,
} from "../ui";

type LayerId = "A" | "B" | "C" | "D" | "E";
const ROOT: Record<LayerId, string> = { A: "HardwareProfile", B: "DeviceSpec", C: "CalibrationSnapshot", D: "Job", E: "ChassisConfig" };

function nestedModel(reg: Registry, doc: FieldDoc | undefined): string | undefined {
  if (!doc) return undefined;
  return Object.keys(reg.models).find((m) => m !== doc.model && new RegExp(`\\b${m}\\b`).test(doc.type));
}

/** Parameter browser: every model and field of a layer with its explanation; searchable. */
function ParameterBrowser({ layer }: { layer: LayerId }) {
  const { reg } = useRegistry();
  const [q, setQ] = useState("");
  const [onlyInert, setOnlyInert] = useState(false);
  if (!reg) return <StateBox state="loading" />;
  const models = Object.values(reg.models).filter((m) => m.layer === layer);
  const ql = q.toLowerCase();
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="search fields, units, meaning…" aria-label="Search parameters"
          className="h-7 w-72 rounded-md border border-line bg-s2 px-2 text-[12px]" />
        <label className="flex items-center gap-1.5 text-[12px] text-ink2"><input type="checkbox" checked={onlyInert} onChange={(e) => setOnlyInert(e.target.checked)} />only inert fields</label>
        <span className="text-[11px] text-mute">{models.reduce((n, m) => n + m.fields.length, 0)} fields in {models.length} models</span>
      </div>
      {models.map((m) => {
        const fields = m.fields.map((k) => reg.fields.find((f) => f.key === k)!).filter((f) => f
          && (!onlyInert || f.inert) && (!ql || `${f.field} ${f.summary} ${f.unit} ${f.detail}`.toLowerCase().includes(ql)));
        if (!fields.length) return null;
        return (
          <details key={m.name} open={!!ql || onlyInert || models.length < 4} className="rounded-md border border-line bg-s2/40">
            <summary className="cursor-pointer select-none px-3 py-2 text-[12.5px]">
              <span className="font-mono text-ink">{m.name}</span>
              <span className="ml-2 text-ink2">{m.summary}</span>
            </summary>
            <div className="space-y-1 px-3 pb-3">
              <Deep at="expert">{m.detail && <p className="mb-2 text-[12px] leading-relaxed text-mute">{m.detail}</p>}</Deep>
              <div className="grid grid-cols-1 gap-2 lg:grid-cols-2">
                {fields.map((f) => <div key={f.key} className="rounded border border-line bg-s1 p-2.5"><FieldExplain doc={f} /></div>)}
              </div>
            </div>
          </details>
        );
      })}
    </div>
  );
}

/** The parsed config as an annotated, editable tree; every key carries its registry explanation. */
function DataTree({ data, model, path, onEdit }: { data: any; model: string; path: (string | number)[]; onEdit: (p: (string | number)[], v: any) => void }) {
  const { reg, byKey } = useRegistry();
  if (!reg || data === null || typeof data !== "object") return null;
  return (
    <ul className={cx("space-y-0.5", path.length > 0 && "ml-3 border-l border-line pl-3")}>
      {Object.entries(data).map(([k, v]) => {
        const doc = byKey.get(`${model}.${k}`);
        const sub = nestedModel(reg, doc);
        const p = [...path, k];
        if (Array.isArray(v) && v.length && typeof v[0] === "object" && v[0] !== null && !Array.isArray(v[0])) {
          return (
            <li key={k}>
              <details open={path.length < 1}>
                <summary className="cursor-pointer text-[12px]"><span className="font-mono text-ink2">{k}</span> <span className="text-mute">[{v.length}]</span> {doc && <InfoTip docKey={doc.key} />}</summary>
                {v.map((item, i) => (
                  <details key={i} className="ml-3">
                    <summary className="cursor-pointer text-[11.5px] text-mute">{k}[{i}] {item.qubit_index !== undefined ? `· q${item.qubit_index}` : item.generator_id ?? item.port_id ?? (item.qubit_pair ? `· q${item.qubit_pair.join("–q")}` : "")}</summary>
                    <DataTree data={item} model={sub ?? model} path={[...p, i]} onEdit={onEdit} />
                  </details>
                ))}
              </details>
            </li>
          );
        }
        if (v !== null && typeof v === "object" && !Array.isArray(v)) {
          return (
            <li key={k}>
              <details>
                <summary className="cursor-pointer text-[12px]"><span className="font-mono text-ink2">{k}</span> {doc && <InfoTip docKey={doc.key} />}</summary>
                <DataTree data={v} model={sub ?? model} path={p} onEdit={onEdit} />
              </details>
            </li>
          );
        }
        return (
          <li key={k} className="flex items-center gap-2 py-px text-[12px]">
            <span className={cx("w-56 shrink-0 truncate font-mono", doc?.inert ? "text-mute line-through decoration-crit/60" : "text-ink2")} title={doc?.summary}>{k}</span>
            {doc && <InfoTip docKey={doc.key} />}
            <Leaf value={v} doc={doc} onChange={(nv) => onEdit(p, nv)} />
            {doc?.unit && <span className="text-[11px] text-mute">{doc.unit}</span>}
          </li>
        );
      })}
    </ul>
  );
}

function Leaf({ value, doc, onChange }: { value: any; doc?: FieldDoc; onChange: (v: any) => void }) {
  if (typeof value === "boolean") return <input type="checkbox" checked={value} onChange={(e) => onChange(e.target.checked)} aria-label={doc?.field} />;
  if (doc?.choices?.length) {
    return <select value={String(value)} onChange={(e) => onChange(e.target.value)} className="h-6 rounded border border-line bg-s2 px-1 text-[12px]" aria-label={doc.field}>{doc.choices.map((c) => <option key={c}>{c}</option>)}</select>;
  }
  if (typeof value === "number") {
    return <input type="number" defaultValue={value} step="any" onBlur={(e) => { const n = e.target.valueAsNumber; if (Number.isFinite(n) && n !== value) onChange(n); }}
      className="num h-6 w-36 rounded border border-line bg-s2 px-1.5 text-[12px]" aria-label={doc?.field} />;
  }
  if (Array.isArray(value)) {
    return <input defaultValue={JSON.stringify(value)} onBlur={(e) => { try { const v = JSON.parse(e.target.value); if (JSON.stringify(v) !== JSON.stringify(value)) onChange(v); } catch { e.target.value = JSON.stringify(value); } }}
      className="num h-6 w-56 rounded border border-line bg-s2 px-1.5 text-[12px]" aria-label={doc?.field} />;
  }
  return <input defaultValue={value ?? ""} onBlur={(e) => { const v = e.target.value === "" && value === null ? null : e.target.value; if (v !== value) onChange(v); }}
    className="h-6 w-56 rounded border border-line bg-s2 px-1.5 text-[12px]" aria-label={doc?.field} placeholder={value === null ? "null" : ""} />;
}

function setPath(obj: any, path: (string | number)[], v: any): any {
  const copy = structuredClone(obj);
  let cur = copy;
  for (const k of path.slice(0, -1)) cur = cur[k];
  cur[path[path.length - 1]] = v;
  return copy;
}

/** Profiles and devices: pick one, edit as a tree or YAML, see the validated diff, save as a copy, use or apply it. */
function ConfigEditor({ kind }: { kind: "profile" | "device" }) {
  const qc = useQueryClient();
  const { wb, set } = useWorkbench();
  const list = useQuery({ queryKey: ["configs"], queryFn: () => api.get<Json>("/configs") });
  const [name, setName] = useState(kind === "profile" ? wb.profile : wb.device);
  const base = useQuery({ queryKey: ["config", kind, name], queryFn: () => api.get<Json>(`/configs/${kind}/${name}`), enabled: !!name });
  const [text, setText] = useState("");
  const [data, setData] = useState<any>(null);
  const [saveAs, setSaveAs] = useState("");
  const [msg, setMsg] = useState<{ tone: "good" | "crit"; text: string } | null>(null);
  useEffect(() => { if (base.data) { setText(base.data.yaml); setData(base.data.data); setSaveAs(`${name}_draft`); } }, [base.data, name]);
  const validation = useQuery({
    queryKey: ["validate", kind, text], enabled: !!text,
    queryFn: () => api.post<Json>(`/configs/${kind}/validate`, { yaml: text }), placeholderData: (p) => p,
  });
  const diff = useQuery({
    queryKey: ["diff", kind, name, text], enabled: !!text && !!base.data && text !== base.data.yaml,
    queryFn: () => api.post<Json>(`/configs/${kind}/diff`, { base: name, yaml: text }),
  });
  useEffect(() => { if (validation.data?.ok) setData(validation.data.data); }, [validation.data]);
  const edit = async (p: (string | number)[], v: any) => {
    const nd = setPath(data, p, v);
    const r = await api.post<Json>(`/configs/${kind}/dump`, { data: nd });
    setText(r.yaml);
  };
  const save = useMutation({
    mutationFn: () => api.put<Json>(`/configs/${kind}/${saveAs}`, { yaml: text }),
    onSuccess: () => { setMsg({ tone: "good", text: `saved as ${saveAs} in the dashboard workspace` }); qc.invalidateQueries({ queryKey: ["configs"] }); },
    onError: (e) => setMsg({ tone: "crit", text: String((e as Error).message) }),
  });
  const restart = useMutation({
    mutationFn: async () => {
      await api.put(`/configs/${kind}/${saveAs}`, { yaml: text });
      return api.post<Json>("/chassis/restart", kind === "profile" ? { profile: saveAs, device: wb.device } : { profile: wb.profile, device: saveAs });
    },
    onSuccess: () => { setMsg({ tone: "good", text: `chassis restarted with ${saveAs}` }); qc.invalidateQueries(); },
    onError: (e) => setMsg({ tone: "crit", text: String((e as Error).message) }),
  });
  const useDraft = () => {
    set(kind === "profile" ? { profileYaml: text } : { deviceYaml: text });
    setMsg({ tone: "good", text: "draft is now used by every sandbox view (Program, Physics, Readout, What-if…)" });
  };
  const names: string[] = (list.data?.[kind] ?? []).map((c: Json) => c.name);
  const v = validation.data;
  const changes: Json[] = diff.data?.changes ?? [];
  return (
    <div className="grid grid-cols-1 gap-5 2xl:grid-cols-2">
      <Panel title={<span className="flex items-center gap-2">{kind === "profile" ? "Hardware profile" : "Device"} {kind === "device" ? <TruthBadge /> : <Badge>instrument rules</Badge>}</span>}
        subtitle={kind === "profile" ? "Edit the instrument's rules; the validator enforces them on every job" : "Edit the hidden chip; lab clients only ever see its effect"}
        actions={<Select value={name} onChange={(n) => { setName(n); setMsg(null); }} options={names} label="file" />}>
        <StateBox state={base.isPending ? "loading" : base.isError ? "error" : "ok"} error={base.error}>
          <div className="mb-2 flex flex-wrap items-center gap-2 text-[11px]">
            {base.data?.source === "builtin" ? <Badge>shipped · read-only</Badge> : <Badge tone="accent">your copy</Badge>}
            {v && (v.ok ? <Badge tone="good">✓ valid</Badge> : <Badge tone="crit">✕ {v.errors.length} error(s)</Badge>)}
            {(v?.warnings ?? []).map((w: string) => <Badge key={w} tone="warn">{w}</Badge>)}
            {(base.data?.unverified ?? []).length > 0 && <span className="text-mute" title={(base.data?.unverified ?? []).join(", ")}>{base.data?.unverified.length} unverified block(s) (provenance verified: false)</span>}
          </div>
          {data && <div className="max-h-[520px] overflow-y-auto rounded-md border border-line bg-bg p-2"><DataTree data={data} model={ROOT[kind === "profile" ? "A" : "B"]} path={[]} onEdit={edit} /></div>}
        </StateBox>
      </Panel>
      <div className="space-y-5">
        <Panel title="YAML and validation" subtitle="Pydantic validation from QCSS itself (frozen models, extra fields forbidden)">
          <textarea value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} aria-label={`${kind} YAML`}
            className="num h-64 w-full resize-y rounded-md border border-line bg-bg p-2 text-[11.5px] leading-snug text-ink" />
          {v && !v.ok && (
            <ul className="mt-2 space-y-1 text-[12px]">{v.errors.map((e: Json, i: number) => <li key={i} className="text-crit"><span className="num">{e.loc || "(file)"}</span>: {e.msg}</li>)}</ul>
          )}
        </Panel>
        <Panel title={`Changes against ${name}`} subtitle="Every changed value, with what it means and when it takes effect">
          {changes.length === 0 ? <p className="text-[12px] text-mute">No changes yet. Edit a value in the tree or the YAML.</p> : (
            <table className="w-full text-[12px]">
              <thead className="text-left text-[11px] text-mute"><tr><th className="py-1">field</th><th>before</th><th>after</th><th>meaning</th></tr></thead>
              <tbody>{changes.map((c) => (
                <tr key={c.path} className="border-t border-line align-top">
                  <td className="py-1 font-mono text-ink2">{c.path}</td>
                  <td className="num text-mute">{JSON.stringify(c.before)}</td>
                  <td className="num text-ink">{JSON.stringify(c.after)}</td>
                  <td className="max-w-80"><ChangeDoc k={c.key} /></td>
                </tr>
              ))}</tbody>
            </table>
          )}
          <Deep at="source">{diff.data?.unified && <pre className="num mt-3 max-h-48 overflow-auto rounded bg-bg p-2 text-[11px] text-ink2">{diff.data.unified}</pre>}</Deep>
          <div className="mt-3 flex flex-wrap items-end gap-2 border-t border-line pt-3">
            <label className="flex flex-col gap-1 text-[11px] text-mute">save as<input value={saveAs} onChange={(e) => setSaveAs(e.target.value)} className="h-7 w-48 rounded-md border border-line bg-s2 px-2 text-[12px] text-ink" /></label>
            <Button onClick={useDraft} disabled={!v?.ok} title="Recompute every sandbox view with this unsaved draft">Use draft in sandbox</Button>
            <Button onClick={() => save.mutate()} disabled={!v?.ok || save.isPending}>Save copy</Button>
            <Button kind="primary" onClick={() => restart.mutate()} disabled={!v?.ok || restart.isPending}
              title="Save the copy and restart the embedded chassis with it (the restart apply mode)">{restart.isPending ? "Restarting…" : "Save & restart chassis"}</Button>
          </div>
          {msg && <p className={cx("mt-2 text-[12px]", msg.tone === "good" ? "text-good" : "text-crit")}>{msg.text}</p>}
        </Panel>
      </div>
    </div>
  );
}

function ChangeDoc({ k }: { k?: string }) {
  const { byKey } = useRegistry();
  const d = k ? byKey.get(k) : undefined;
  if (!d) return <span className="text-mute">—</span>;
  return <span className="text-ink2">{d.summary} <Badge tone={d.apply === "live" ? "good" : "warn"}>{d.apply}</Badge>{d.inert && <> <Badge tone="crit">inert: no effect</Badge></>}</span>;
}

/** Calibration (layer C): the lab's beliefs, written with compare-and-swap exactly as Qibocal does. */
function CalibrationEditor() {
  const qc = useQueryClient();
  const cal = useQuery({ queryKey: ["calibration"], queryFn: () => api.get<Json>("/lab/calibration") });
  const [q, setQ] = useState(0);
  const [edits, setEdits] = useState<Json>({});
  const [msg, setMsg] = useState("");
  const qcal = (cal.data?.qubits ?? []).find((x: Json) => x.qubit_index === q) ?? {};
  const write = useMutation({
    mutationFn: () => api.put<Json>("/lab/calibration", { snapshot: { qubits: [{ qubit_index: q, ...edits }] }, expected_epoch: cal.data?.calibration_epoch ?? 0 }),
    onSuccess: (r) => { setMsg(`written: epoch ${r.new_epoch}`); setEdits({}); qc.invalidateQueries({ queryKey: ["calibration"] }); },
    onError: (e) => setMsg(String((e as Error).message)),
  });
  const fields: [string, string][] = [["drive_frequency_hz", "Hz"], ["readout_frequency_hz", "Hz"], ["readout_delay_ticks", "ticks"],
    ["readout_rotation_rad", "rad"], ["readout_threshold", ""], ["pi_length_samples", "samples"], ["pi_amplitude", "FS"], ["drag_beta_samples", "samples"]];
  return (
    <Panel title={<span className="flex items-center gap-2">Calibration <LabBadge /></span>} subtitle={`epoch ${cal.data?.calibration_epoch ?? "—"} · read and written over the lab link`}
      explain={<>Calibration is what the lab <em>believes</em>. QCSS never writes it: the virtual technician (real Qibocal) measures the drifting truth and writes it with compare-and-swap. A write here is a lab-client write: if someone wrote in between, it is refused (HTTP 409) and nothing changes. Compare with the truth in the Chip and Admin views to see how stale it is.</>}
      actions={<Select value={String(q)} onChange={(v) => setQ(Number(v))} options={(cal.data?.qubits ?? []).map((x: Json) => String(x.qubit_index))} label="qubit" />}>
      <StateBox state={cal.isPending ? "loading" : cal.isError ? "error" : "ok"} error={cal.error} onRetry={() => cal.refetch()}>
        <div className="flex flex-wrap gap-4">
          {fields.map(([f, unit]) => (
            <NumberField key={f} label={f} unit={unit} docKey={`QubitCalibration.${f}`} width="w-40"
              value={edits[f] ?? qcal[f] ?? 0} onChange={(n) => setEdits((e) => ({ ...e, [f]: n }))} />
          ))}
        </div>
        <div className="mt-3 flex items-center gap-3">
          <Button kind="primary" onClick={() => write.mutate()} disabled={!Object.keys(edits).length || write.isPending}>Write (compare-and-swap)</Button>
          <span className="text-[12px] text-ink2">{msg}</span>
        </div>
      </StateBox>
    </Panel>
  );
}

function ChassisLayer() {
  const qc = useQueryClient();
  const info = useQuery({ queryKey: ["chassis"], queryFn: () => api.get<Json>("/chassis") });
  const list = useQuery({ queryKey: ["configs"], queryFn: () => api.get<Json>("/configs") });
  const emb = info.data?.embedded;
  const [p, setP] = useState(""); const [d, setD] = useState(""); const [ts, setTs] = useState(1);
  useEffect(() => { if (emb) { setP(emb.profile); setD(emb.device ?? ""); setTs(emb.time_scale); } }, [emb]);
  const restart = useMutation({ mutationFn: () => api.post<Json>("/chassis/restart", { profile: p, device: d || null, time_scale: ts }), onSuccess: () => qc.invalidateQueries() });
  return (
    <Panel title="Chassis" subtitle="The running virtual lab (startup options); live mode and scenarios are in the Admin console"
      actions={<Link to="/admin"><Button>Live mode & scenarios →</Button></Link>}>
      <StateBox state={info.isPending ? "loading" : info.isError ? "error" : "ok"} error={info.error}>
        {emb ? (
          <div className="flex flex-wrap items-end gap-3">
            <Select value={p} onChange={setP} options={(list.data?.profile ?? []).map((c: Json) => c.name)} label="profile" />
            <Select value={d} onChange={setD} options={(list.data?.device ?? []).map((c: Json) => c.name)} label="device" />
            <NumberField label="time_scale" value={ts} onChange={setTs} step={0.5} min={0} docKey="ChassisConfig.time_scale" />
            <Button kind="primary" onClick={() => restart.mutate()} disabled={restart.isPending}>{restart.isPending ? "Restarting…" : "Restart chassis"}</Button>
            {restart.isError && <span className="text-[12px] text-crit">{String((restart.error as Error).message)}</span>}
            <p className="w-full text-[12px] text-mute">Lab {emb.lab_address} · admin {emb.admin_address} · tokens generated per start and held by the bridge only · chip state {emb.restored_state ? "restored from the workspace" : "fresh"}</p>
          </div>
        ) : <p className="text-[12px] text-mute">Connected to an external chassis: start options are set where it runs (qcss serve).</p>}
      </StateBox>
    </Panel>
  );
}

export function ConfigStudio() {
  const [sp, setSp] = useSearchParams();
  const layer = (sp.get("layer") as LayerId) || "B";
  const { reg } = useRegistry();
  const l = reg?.layers.find((x) => x.id === layer);
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-[18px] font-semibold">Config Studio</h1>
        <p className="mt-1 max-w-4xl text-[13px] text-ink2">Every configurable value in QCSS, discovered from the code itself and explained. Edit as a tree or YAML; the simulator's own validator checks every draft, the diff tells you what each change means and when it applies.</p>
      </div>
      <Tabs value={layer} onChange={(t) => setSp({ layer: t })}
        tabs={(reg?.layers ?? []).map((x) => ({ id: x.id as LayerId, label: `${x.id} · ${x.name}` }))} />
      {l && <p className="text-[12px] text-ink2"><span className="text-mute">owner</span> {l.owner} · <span className="text-mute">applies</span> {l.when} · <span className="text-mute">schema</span> <code className="font-mono">{l.file}</code></p>}
      {layer === "A" && <ConfigEditor key="profile" kind="profile" />}
      {layer === "B" && <ConfigEditor key="device" kind="device" />}
      {layer === "C" && <CalibrationEditor />}
      {layer === "D" && <Panel title="Jobs" subtitle="Built per experiment; open the Program view to build, validate and run one"
        actions={<Link to="/program"><Button kind="primary">Open program builder →</Button></Link>}><p className="text-[12px] text-ink2">A job is a timed list of instructions on channels (xy_q0, ro_q0, flux_q0…), a waveform library, sweeps and shots. Below is every field a job can carry.</p></Panel>}
      {layer === "E" && <ChassisLayer />}
      <Panel title="Parameter reference" subtitle={`Every field of layer ${layer}, with meaning, unit, default, range, equation, source and apply mode`}>
        <ParameterBrowser layer={layer} />
      </Panel>
    </div>
  );
}
