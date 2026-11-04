import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, type Json } from "../api";
import { Heatmap, IQScatter, LineChart } from "../charts";
import { useWorkbench } from "../state";
import { Equation, InfoTip, KV, NumberField, Panel, Select, StateBox, TruthBadge, fmt } from "../ui";
import { DraftNote, ProfilePicker } from "./common";

export function Readout() {
  const { configBody } = useWorkbench();
  const [qubit, setQubit] = useState(0);
  const [shots, setShots] = useState(400);
  const [integ, setInteg] = useState(1000);
  const [seed, setSeed] = useState(1);
  const q = useQuery({
    queryKey: ["readout", configBody(), qubit, shots, integ, seed],
    queryFn: () => api.post<Json>("/views/readout", { ...configBody(), qubit, shots, integration_ns: integ, seed }),
    placeholderData: (p) => p,
  });
  const r = q.data;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="text-[18px] font-semibold">Readout (seam 4)</h1>
          <p className="mt-1 max-w-4xl text-[13px] text-ink2">Dispersive readout: each qubit level pulls the resonator by a different amount, so a probe tone reflects
            differently. The field rings up over ~1/κ, arrives after the time of flight, is integrated with a matched filter and thresholded. T1 decay during the window and amplifier noise (efficiency η) make readout imperfect.</p>
        </div>
        <ProfilePicker />
        <Select value={String(qubit)} onChange={(v) => setQubit(Number(v))} options={["0", "1", "2", "3", "4"]} label="qubit" />
        <NumberField label="shots per level" value={shots} onChange={setShots} min={20} max={2000} width="w-20" />
        <NumberField label="integration" value={integ} onChange={setInteg} unit="ns" min={50} width="w-24" docKey="Acquire.integration_ticks" />
        <NumberField label="seed" value={seed} onChange={setSeed} width="w-16" />
      </div>
      <DraftNote />
      <StateBox state={!r && q.isPending ? "loading" : q.isError ? "error" : "ok"} error={q.error} onRetry={() => q.refetch()}>
        {r && (
          <>
            <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1fr_340px]">
              <Panel title="Resonator ring-up per qubit level" subtitle="Mean photon number |α(t)|² under the probe. |0⟩ and |1⟩ coincide: the probe sits midway between their dressed frequencies, so they hold the same photons and differ only in phase (see the IQ plane)."
                explain={<Equation block tex={"\\dot\\alpha = -\\left(i(\\Delta + \\chi_m) + \\tfrac{\\kappa}{2}\\right)\\alpha + \\sqrt\\kappa\\,A(t),\\qquad B = -A + \\sqrt\\kappa\\,\\alpha"} />}>
                <LineChart x={r.t_ns} xLabel="time in window (ns)" yLabel="photons" height={220}
                  lines={[0, 1, 2].map((m) => ({ label: `|${m}⟩`, y: r.mean_field[String(m)].photons }))} />
              </Panel>
              <Panel title={<span className="flex items-center gap-2">Readout parameters <TruthBadge /></span>}>
                <KV rows={[[<span>κ <InfoTip docKey="ResonatorSpec.kappa_mhz" /></span>, `${fmt(r.kappa_mhz, 3)} MHz`],
                  [<span>χ <InfoTip docKey="ResonatorSpec.pulls_mhz" /></span>, `${fmt(r.chi_mhz, 3)} MHz`],
                  [<span>η <InfoTip docKey="ResonatorSpec.eta" /></span>, fmt(r.eta, 2)], ["probe amplitude", fmt(r.drive_amplitude, 4)],
                  ["ADC sample", `${fmt(r.adc_dt_ns, 3)} ns`], ["time of flight", `${fmt(r.tof_ns, 1)} ns`], ["acquisition delay", `${fmt(r.delay_ns, 1)} ns`],
                  ["window", `${fmt(r.integration_ns, 0)} ns`], ["T1 during readout", `${fmt(r.t1_us, 1)} µs`], ["discriminator", r.discriminator.kind]]} />
              </Panel>
            </div>
            <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
              <Panel title="Single shots in the IQ plane" subtitle={`${shots} integrated shots per prepared level; dashed line = discriminator threshold`}>
                <IQScatter clouds={["0", "1", "2"].map((k) => ({ label: `prepared |${k}⟩`, points: r.clouds[k] }))}
                  threshold={r.discriminator.threshold !== undefined ? { rotation: r.discriminator.rotation_rad, value: r.discriminator.threshold } : undefined}
                  centroids={r.discriminator.centroids} />
              </Panel>
              <Panel title={<span>Assignment (confusion) matrix <InfoTip docKey="AcquisitionSpec.max_discriminated_states" /></span>} subtitle="P(label | true level), from the same physical model the gate tiers use"
                explain={<>Row |1⟩ leaking into label 0 is mostly T1 decay during the window; overlap of the clouds is noise. |2⟩ reads as 1 on a two-state discriminator.</>}>
                <Heatmap m={r.confusion} rowLabels={["|0⟩", "|1⟩", "|2⟩"]} colLabels={r.confusion[0].map((_: number, j: number) => `label ${j}`)} />
              </Panel>
              <Panel title="Example ADC traces" subtitle="Raw complex samples (I shown) with noise; one |1⟩ trace may show a T1 jump">
                <LineChart x={r.example_traces.t_ns} xLabel="time (ns)" yLabel="I (arb.)" height={200}
                  lines={r.example_traces.traces.map((t: Json, i: number) => ({ label: `shot ${i} (prepared |${r.example_traces.levels[i]}⟩)`, y: t.re, width: 1 }))} />
              </Panel>
              <Panel title="Resonator spectroscopy" subtitle="Reflected magnitude vs probe detuning for each qubit level; the probe sits at 0">
                <LineChart x={r.spectroscopy.freq_mhz} xLabel="probe detuning (MHz)" yLabel="|B| / |A|" height={200}
                  lines={[0, 1, 2].map((m) => ({ label: `|${m}⟩`, y: r.spectroscopy.mag[String(m)] }))} />
              </Panel>
              <Panel title="Why readout takes about a microsecond" subtitle="Separation SNR of |0⟩ and |1⟩ vs integration time">
                <LineChart x={r.snr_vs_integration.map((s: Json) => s.integration_ns)} xLabel="integration (ns)" yLabel="SNR" height={200}
                  lines={[{ label: "SNR", y: r.snr_vs_integration.map((s: Json) => s.snr), points: true }]} />
                <p className="mt-1 text-[11.5px] text-mute">Longer windows average away noise, but T1 decay during the window eventually costs more than it gains.</p>
              </Panel>
              <Panel title="Matched-filter weights" subtitle="w(t) = ⟨trace|1⟩ − ⟨trace|0⟩, normalized to [−1, 1] (Qblox weight range)">
                <LineChart x={r.t_ns} xLabel="time (ns)" yLabel="weight" height={200} lines={[{ label: "Re w", y: r.weights.re }, { label: "Im w", y: r.weights.im }]} />
              </Panel>
            </div>
          </>
        )}
      </StateBox>
    </div>
  );
}
