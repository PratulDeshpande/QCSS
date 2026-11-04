import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, type Json } from "../api";
import { IQScatter, LineChart } from "../charts";
import { Badge, Button, Equation, LabBadge, NumberField, Panel, Stat, StateBox, TruthBadge, fmt } from "../ui";

const ideal = { gain_i: 1, gain_q: 1, phase_rad: 0, dc_i: 0, dc_q: 0 };
const noCorr = { dc_i: 0, dc_q: 0, gain_ratio: 1, phase_rad: 0 };

function Mixer() {
  const [truth, setTruth] = useState({ ...ideal, gain_q: 1.06, phase_rad: 0.04, dc_i: 0.004 });
  const [corr, setCorr] = useState(noCorr);
  const [ifHz, setIf] = useState(100e6);
  const q = useQuery({ queryKey: ["mixer", truth, corr, ifHz], queryFn: () => api.post<Json>("/views/signal", { mixer: { truth, correction: corr, if_hz: ifHz } }), placeholderData: (p) => p });
  const m = q.data?.mixer;
  const T = (k: keyof typeof truth, label: string, step: number) => <NumberField key={k} label={label} value={truth[k]} step={step} onChange={(v) => setTruth({ ...truth, [k]: v })} docKey={`MixerImpairmentSpec.${k}`} width="w-24" />;
  const C = (k: keyof typeof corr, label: string, step: number, doc: string) => <NumberField key={k} label={label} value={corr[k]} step={step} onChange={(v) => setCorr({ ...corr, [k]: v })} docKey={`MixerCorrection.${doc}`} width="w-24" />;
  // The exact correction for this truth: cancel the DC, undo the gain ratio and skew (first order).
  const autoCorrect = () => setCorr({ dc_i: -truth.dc_i, dc_q: -truth.dc_q, gain_ratio: truth.gain_i / truth.gain_q, phase_rad: -truth.phase_rad });
  return (
    <Panel title="IQ mixer: hidden imbalance vs the lab's correction" subtitle="A single-sideband tone at the IF, up-converted by an imperfect mixer"
      explain={<><Equation tex={"x = \\mu\\,c(m) + \\nu\\,c(m)^* + (dc_i + i\\,dc_q),\\quad \\mu,\\nu = \\tfrac12(g_I e^{\\pm i\\phi/2} \\pm g_Q e^{\\mp i\\phi/2})"} /> — the ν term puts an <b>image</b> at −IF, the DC term leaks the <b>LO</b>. The lab cancels them by calibrating c(·); QCSS keeps the truth hidden.</>}>
      <div className="flex flex-wrap gap-6">
        <div><div className="mb-1 flex items-center gap-2 text-[12px]"><TruthBadge /> hidden mixer</div>
          <div className="flex flex-wrap gap-2">{T("gain_i", "gain I", 0.01)}{T("gain_q", "gain Q", 0.01)}{T("phase_rad", "skew (rad)", 0.01)}{T("dc_i", "DC I", 0.001)}{T("dc_q", "DC Q", 0.001)}</div></div>
        <div><div className="mb-1 flex items-center gap-2 text-[12px]"><LabBadge /> calibrated correction</div>
          <div className="flex flex-wrap gap-2">{C("dc_i", "DC I", 0.001, "dc_offset_i")}{C("dc_q", "DC Q", 0.001, "dc_offset_q")}{C("gain_ratio", "gain ratio", 0.01, "gain_ratio")}{C("phase_rad", "skew (rad)", 0.01, "phase_skew_rad")}</div>
          <div className="mt-2 flex gap-2"><Button onClick={autoCorrect}>Calibrate perfectly</Button><Button kind="ghost" onClick={() => setCorr(noCorr)}>No correction</Button></div></div>
        <NumberField label="IF" value={ifHz / 1e6} onChange={(v) => setIf(v * 1e6)} unit="MHz" width="w-20" />
      </div>
      <StateBox state={!m && q.isPending ? "loading" : q.isError ? "error" : "ok"} error={q.error}>
        {m && (
          <div className="mt-4 grid grid-cols-1 gap-5 xl:grid-cols-[220px_1fr_320px]">
            <div className="space-y-3">
              <Stat label="image sideband" value={fmt(m.image_dbc, 1)} unit="dBc" tone={m.image_dbc < -40 ? "good" : m.image_dbc < -25 ? "warn" : "crit"} hint="≈ ((g−1)² + φ²)/4" />
              <Stat label="LO leakage" value={fmt(m.lo_dbc, 1)} unit="dBc" tone={m.lo_dbc < -40 ? "good" : m.lo_dbc < -25 ? "warn" : "crit"} />
              <p className="text-[11.5px] text-mute">An image drives the qubit off-resonance; LO leakage is a constant tone at the LO, there even between pulses.</p>
            </div>
            <LineChart x={m.spectrum.f_mhz} xLabel="frequency offset from LO (MHz)" yLabel="power (dB)" height={230} lines={[{ label: "|X(f)|", y: m.spectrum.db }]} />
            <IQScatter height={230} clouds={[{ label: "programmed (ideal)", points: m.iq_in.re.map((r: number, i: number) => [r, m.iq_in.im[i]]) },
              { label: "after mixer", points: m.iq_out.re.map((r: number, i: number) => [r, m.iq_out.im[i]]) }]} />
          </div>
        )}
      </StateBox>
    </Panel>
  );
}

function Flux() {
  const [terms, setTerms] = useState<[number, number][]>([[0.08, 30e-9], [0.03, 400e-9]]);
  const [pre, setPre] = useState<[number, number][]>([]);
  const [bias, setBias] = useState(0);
  const q = useQuery({
    queryKey: ["flux", terms, pre, bias],
    queryFn: () => api.post<Json>("/views/signal", { flux: { exp_terms: terms, predistortion: pre, bias_tee_tau_s: bias ? bias * 1e-6 : null, inverse_highpass_tau_s: null, samples: 2000 } }),
    placeholderData: (p) => p,
  });
  const f = q.data?.flux;
  const edit = (list: [number, number][], set: (l: [number, number][]) => void, i: number, j: 0 | 1, v: number) => { const c = list.map((x) => [...x] as [number, number]); c[i][j] = j === 1 ? v * 1e-9 : v; set(c); };
  const rows = (list: [number, number][], set: (l: [number, number][]) => void, doc: string) => list.map(([a, t], i) => (
    <div key={i} className="flex items-end gap-2">
      <NumberField label="A" value={a} step={0.01} onChange={(v) => edit(list, set, i, 0, v)} docKey={doc} width="w-20" />
      <NumberField label="τ" value={t * 1e9} step={5} onChange={(v) => edit(list, set, i, 1, v)} unit="ns" width="w-24" />
      <Button kind="ghost" onClick={() => set(list.filter((_, k) => k !== i))}>✕</Button>
    </div>
  ));
  return (
    <Panel title="Flux line: hidden distortion vs the lab's predistortion" subtitle="Step response of the line the flux pulse travels through (Rol form, Qblox real-time predistortion)"
      explain={<><Equation tex={"s[n] = \\prod_k \\left(1 + A_k\\,p_k^{\\,n}\\right),\\; p_k = e^{-1/(\\tau_k f_s)}"} /> — exponential tails smear a flux pulse into the next gate (cryoscope measures them). The lab programs inverse filters; the combined response should be a clean step.</>}>
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[300px_1fr]">
        <div className="space-y-3">
          <div><div className="mb-1 flex items-center gap-2 text-[12px]"><TruthBadge /> line tails</div>{rows(terms, setTerms, "FluxLineSpec.exp_terms")}
            <Button onClick={() => setTerms([...terms, [0.02, 100e-9]])}>+ tail</Button></div>
          <NumberField label="bias-tee τ (0 = none)" value={bias} onChange={setBias} unit="µs" docKey="FluxLineSpec.bias_tee_tau_s" />
          <div><div className="mb-1 flex items-center gap-2 text-[12px]"><LabBadge /> predistortion stages (≤ 4)</div>{rows(pre, setPre, "ExponentialStage.amplitude")}
            <div className="flex gap-2"><Button onClick={() => pre.length < 4 && setPre([...pre, [0.02, 100e-9]])}>+ stage</Button>
              <Button onClick={() => setPre(terms.slice(0, 4))}>Calibrate perfectly</Button></div></div>
        </div>
        <StateBox state={!f && q.isPending ? "loading" : q.isError ? "error" : "ok"} error={q.error}>
          {f && (
            <div>
              <div className="mb-2 flex gap-6"><Stat label="worst residual" value={fmt(f.residual_max * 100, 2)} unit="%" tone={f.residual_max < 0.005 ? "good" : f.residual_max < 0.03 ? "warn" : "crit"} hint="max |combined − 1|" /></div>
              <LineChart x={f.t_ns} xLabel="time (ns)" yLabel="step response" height={260}
                lines={[{ label: "ideal", y: f.ideal, dash: true, color: 7, width: 1 }, { label: "line (truth)", y: f.truth, color: 1 },
                  { label: "predistorted command", y: f.predistorted, color: 3 }, { label: "what the qubit sees", y: f.combined, color: 0 }]} />
            </div>
          )}
        </StateBox>
      </div>
      {q.isError && <Badge tone="crit">predistortion refused (driver limits: τ ∈ [6 ns, 2 ms], A ∈ [−1, 1))</Badge>}
    </Panel>
  );
}

export function Signal() {
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-[18px] font-semibold">Signal chain (render seam)</h1>
        <p className="mt-1 max-w-4xl text-[13px] text-ink2">Between the numbers a job programs and what the qubit feels sit an NCO, an IQ mixer with its LO, and for flux a long cable with filters. QCSS renders all of it with QCSS's own filters, mixer model and Qblox predistortion: these plots call that code directly. The rendered drive of a real job is on the Feedback & timing view.</p>
      </div>
      <Mixer />
      <Flux />
    </div>
  );
}
