import { useState } from "react";
import { Link } from "react-router-dom";
import { useRegistry } from "../registry";
import { Badge, FieldExplain, Panel } from "../ui";

const TOURS = [
  { title: "Why does a π pulse not give exactly |1⟩?", steps: [
    ["/physics", "Run rabi_amplitude_q0 at tier T2 and pick sweep point 5 (A ≈ 0.5). Watch P(|1⟩) rise during the pulse and a little population appear in |2⟩: leakage, because the 1–2 transition is only E_C away."],
    ["/chip", "Read the qubit's T1, T2* and thermal n̄: the qubit starts slightly excited (n̄ > 0) and decays during the pulse and the readout."],
    ["/readout", "Look at the confusion matrix: |1⟩ read as 0 a few percent of the time, mostly from T1 decay inside the 1 µs window."],
    ["/whatif", "Sweep QubitSpec.ec_ghz in a Rabi: smaller anharmonicity, more leakage."]] },
  { title: "How does a drifting chip spoil calibration?", steps: [
    ["/admin", "Note the Δ column of Truth vs belief: calibrated drive vs true f01."],
    ["/admin", "Apply a drift step of +300 kHz to q0. The truth moves; the calibration does not."],
    ["/lab", "Run a Ramsey on q0 over the lab link: the fringe frequency now shows the detuning the lab did not know about."],
    ["/config?layer=C", "Correct drive_frequency_hz with a compare-and-swap write; run the Ramsey again."]] },
  { title: "What decides how a job is simulated?", steps: [
    ["/physics", "Run the same job at AUTO, T1B and T2; compare the chosen tier and its reason."],
    ["/program", "Edit the job so two pulses overlap on one qubit: the gate tiers refuse, T2 is required."],
    ["/admin", "Set the tier policy: the operator, not the client, decides the physics on a lab chassis."]] },
  { title: "Why can't a branch come sooner?", steps: [
    ["/hardware", "Read the feedback latency matrix and the readout time of flight."],
    ["/timing", "Run a job and read the result-ready time: acquisition start + ToF + integration."],
    ["/program", "Move a branch earlier than ready + latency: the validator refuses it with a field path."]] },
  { title: "What does the lab never see?", steps: [
    ["/", "Open the Atlas: lab clients only reach the adapters; truth comes only through the admin channel."],
    ["/admin", "Inject a REBOOT fault and run a Lab-bench job: the lab sees a bare 'instrument fault'; Admin › inspect shows the cause."],
    ["/config?layer=E", "Read ChassisConfig.seed and reflection: entropy by default, reflection off, because a lab never repeats and never reveals it is QCSS."]] },
];

const CONCEPTS: [string, string][] = [
  ["Indistinguishability", "Nothing a lab client can reach may reveal the simulator: no tier, no truth, no replayable seeds, no zero latency, no perfect initial calibration, no reset on restart (tests/integration/test_indistinguishability.py)."],
  ["Tick", "The integer time unit: the least common multiple of every instrument clock. All scheduling is exact integer arithmetic."],
  ["Lab clock", "Lab time = wall time × time_scale. The chip drifts on it, jobs are paced by it, and it keeps running while the chassis is down."],
  ["Calibration epoch", "A version number of the lab's calibration. Writes are compare-and-swap; a job can pin the epoch it was compiled for."],
  ["Lift", "Reducing a rendered pulse to the gate it performs (a unitary plus leakage) during a planning dry run; gate tiers apply lifted gates."],
  ["Tier", "The engine that simulates a job: T0 surrogate, T1a stabilizer, T1b statevector, T2 Lindblad. The cheapest faithful one wins."],
  ["Seam", "One of the four physics boundaries: Render (signal chain), Parameters (device truth), Evolve (engines), Readout."],
  ["Virtual technician", "Real Qibocal run on a schedule against the virtual lab; it measures the drifting truth and writes calibration."],
  ["Admin channel", "The operator's separate gRPC service and token: truth, scenarios, mode, faults. This dashboard is an admin client."],
  ["Time of flight", "Delay between a probe tone leaving the instrument and its reflection arriving at the ADC: internal pipeline + output latency + cable."],
];

export function Learn() {
  const { reg } = useRegistry();
  const [q, setQ] = useState("");
  const ql = q.toLowerCase();
  const hits = (reg?.fields ?? []).filter((f) => ql.length > 1 && `${f.key} ${f.summary} ${f.detail} ${f.unit}`.toLowerCase().includes(ql)).slice(0, 40);
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-[18px] font-semibold">Tours & glossary</h1>
        <p className="mt-1 max-w-4xl text-[13px] text-ink2">Short guided paths through the views that answer one question each, and every concept and parameter in one place.</p>
      </div>
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        {TOURS.map((t) => (
          <Panel key={t.title} title={t.title}>
            <ol className="space-y-2">
              {t.steps.map(([to, text], i) => (
                <li key={i} className="flex gap-3 text-[12.5px] leading-relaxed">
                  <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full border border-line text-[10px] text-mute">{i + 1}</span>
                  <span className="text-ink2">{text} <Link to={to} className="text-accent hover:underline">open →</Link></span>
                </li>
              ))}
            </ol>
          </Panel>
        ))}
      </div>
      <Panel title="Concepts">
        <dl className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {CONCEPTS.map(([k, v]) => <div key={k}><dt className="text-[12.5px] font-semibold text-ink">{k}</dt><dd className="text-[12px] leading-relaxed text-ink2">{v}</dd></div>)}
        </dl>
      </Panel>
      <Panel title="Find any parameter" subtitle={`${reg?.fields.length ?? "…"} fields across the five layers`}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. latency, T1, full scale, epoch…" aria-label="Search all parameters"
          className="h-8 w-full max-w-lg rounded-md border border-line bg-s2 px-2 text-[12.5px]" />
        <div className="mt-3 grid grid-cols-1 gap-2 lg:grid-cols-2">
          {hits.map((f) => <div key={f.key} className="rounded border border-line bg-s2/40 p-2.5"><Badge tone="accent">{f.layer}</Badge> <FieldExplain doc={f} /></div>)}
          {ql.length > 1 && !hits.length && <p className="text-[12px] text-mute">No parameter matches “{q}”.</p>}
        </div>
      </Panel>
    </div>
  );
}
