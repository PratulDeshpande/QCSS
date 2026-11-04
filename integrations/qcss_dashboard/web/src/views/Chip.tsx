import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, type Json } from "../api";
import { LineChart, SERIES } from "../charts";
import { useWorkbench } from "../state";
import { Badge, Equation, InfoTip, KV, NumberField, Panel, Select, StateBox, TruthBadge, fmt } from "../ui";
import { DraftNote, ProfilePicker } from "./common";

function ChipMap({ chip, sel, onSel }: { chip: Json; sel: number; onSel: (q: number) => void }) {
  // Scale to the qubits' footprint (plus a 1.5 mm margin), not the whole die: qubits sit a few mm apart on a 15 mm chip.
  const xs = chip.qubits.map((q: Json) => q.xy_mm[0]), ys = chip.qubits.map((q: Json) => q.xy_mm[1]);
  const x0 = Math.min(...xs) - 1.5, y0 = Math.min(...ys) - 1.5;
  const side = Math.max(Math.max(...xs) - x0 + 1.5, Math.max(...ys) - y0 + 1.5, 1), S = 360, k = (S - 40) / side;
  const pos = (q: Json) => [40 + (q.xy_mm[0] - x0) * k, S - 30 - (q.xy_mm[1] - y0) * k] as const;
  const byIdx = new Map(chip.qubits.map((q: Json) => [q.qubit_index, q]));
  return (
    <svg viewBox={`0 0 ${S + 40} ${S + 10}`} className="w-full max-w-[420px]" role="img" aria-label="chip map: qubit positions, couplers and cosmic-ray bursts">
      <rect x={20} y={-10} width={S} height={S} rx={6} fill="var(--surface-2)" stroke="var(--border)" />
      <clipPath id="die"><rect x={20} y={-10} width={S} height={S} rx={6} /></clipPath>
      {chip.drift.bursts.map((b: Json, i: number) => (
        <circle key={i} clipPath="url(#die)" cx={40 + (b.xy_mm[0] - x0) * k} cy={S - 30 - (b.xy_mm[1] - y0) * k} r={1 * k} fill="var(--critical)" opacity={0.18}>
          <title>{`burst at ${fmt(b.t_hours, 2)} h, peak ${fmt(b.peak_gamma_per_us, 2)} /µs (σ₀ ≈ 1 mm footprint)`}</title>
        </circle>
      ))}
      {chip.couplers.map((c: Json, i: number) => {
        const a = byIdx.get(c.qubit_pair[0]) as Json, b = byIdx.get(c.qubit_pair[1]) as Json;
        const [x1, y1] = pos(a), [x2, y2] = pos(b);
        return (
          <g key={i}><line x1={x1} y1={y1} x2={x2} y2={y2} stroke="var(--text-muted)" strokeWidth={Math.max(1, c.j_mhz / 1.5)} />
            <text x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 4} fontSize={9.5} fill="var(--text-muted)" textAnchor="middle">J {fmt(c.j_mhz, 2)}</text></g>
        );
      })}
      {chip.qubits.map((q: Json) => {
        const [x, y] = pos(q);
        return (
          <g key={q.qubit_index} onClick={() => onSel(q.qubit_index)} className="cursor-pointer" role="button" aria-label={`select qubit ${q.qubit_index}`}>
            <circle cx={x} cy={y} r={16} fill={q.qubit_index === sel ? "var(--series-1)" : "var(--surface-3)"} stroke="var(--surface-1)" strokeWidth={2} />
            <text x={x} y={y + 4} textAnchor="middle" fontSize={11} fill={q.qubit_index === sel ? "#fff" : "var(--text-primary)"}>q{q.qubit_index}</text>
            {q.qubit_index === sel && <text x={x} y={y + 30} textAnchor="middle" fontSize={9.5} fill="var(--text-primary)" className="num">{fmt(q.f01_ghz, 3)} GHz</text>}
          </g>
        );
      })}
      <text x={20} y={S + 6} fontSize={9.5} fill="var(--text-muted)">view {fmt(side, 1)} mm wide (die {fmt(chip.chip_side_mm, 1)} mm) · red discs: cosmic-ray bursts in the window</text>
    </svg>
  );
}

function Levels({ q }: { q: Json }) {
  const f01 = q.f01_ghz, f12 = q.f12_ghz, H = 150, scale = H / (f01 + f12) * 0.9;
  const y = (e: number) => H - 10 - e * scale;
  return (
    <svg viewBox="0 0 220 160" className="w-56" role="img" aria-label="transmon level diagram">
      {[[0, "|0⟩"], [f01, "|1⟩"], [f01 + f12, "|2⟩"]].map(([e, l]) => (
        <g key={l as string}><line x1={40} x2={140} y1={y(e as number)} y2={y(e as number)} stroke="var(--text-primary)" strokeWidth={2} />
          <text x={146} y={y(e as number) + 4} fontSize={11} fill="var(--text-secondary)">{l as string}</text></g>
      ))}
      <line x1={70} x2={70} y1={y(0)} y2={y(f01)} stroke={SERIES(0)} strokeWidth={2} markerEnd="url(#a)" />
      <text x={74} y={(y(0) + y(f01)) / 2} fontSize={10} fill="var(--text-secondary)" className="num">f01 {fmt(f01, 3)}</text>
      <line x1={110} x2={110} y1={y(f01)} y2={y(f01 + f12)} stroke={SERIES(1)} strokeWidth={2} />
      <text x={114} y={(y(f01) + y(f01 + f12)) / 2} fontSize={10} fill="var(--text-secondary)" className="num">f12 {fmt(f12, 3)}</text>
      <text x={8} y={154} fontSize={9.5} fill="var(--text-muted)">α = f12 − f01 = −E_C = {fmt(q.alpha_ghz * 1e3, 0)} MHz</text>
    </svg>
  );
}

export function Chip() {
  const { configBody } = useWorkbench();
  const [hours, setHours] = useState(24);
  const [seed, setSeed] = useState(1);
  const [sel, setSel] = useState(0);
  const q = useQuery({ queryKey: ["chip", configBody(), hours, seed], queryFn: () => api.post<Json>("/views/chip", { ...configBody(), hours, steps: 120, seed }) });
  const chip = q.data;
  const qb: Json | undefined = chip?.qubits.find((x: Json) => x.qubit_index === sel);
  const qi = chip ? chip.qubits.findIndex((x: Json) => x.qubit_index === sel) : 0;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="flex items-center gap-2 text-[18px] font-semibold">Chip truth <TruthBadge /></h1>
          <p className="mt-1 max-w-4xl text-[13px] text-ink2">The transmons as they really are, and how they wander. Lab clients only see the effect of these numbers through what they measure; this is why calibration goes stale.</p>
        </div>
        <ProfilePicker />
        <NumberField label="drift window" value={hours} onChange={setHours} unit="h" min={0.1} width="w-20" />
        <NumberField label="drift seed" value={seed} onChange={setSeed} width="w-16" />
      </div>
      <DraftNote />
      <StateBox state={q.isPending ? "loading" : q.isError ? "error" : "ok"} error={q.error} onRetry={() => q.refetch()}>
        {chip && qb && (
          <>
            <div className="grid grid-cols-1 gap-5 xl:grid-cols-[440px_1fr]">
              <Panel title={chip.device_name} subtitle={`${chip.qubits.length} qubits · ${chip.couplers.length} couplers · click a qubit`}>
                <ChipMap chip={chip} sel={sel} onSel={setSel} />
              </Panel>
              <Panel title={`Qubit ${sel}`} subtitle="Asymmetric-SQUID transmon, simulated as a qutrit"
                actions={<Select value={String(sel)} onChange={(v) => setSel(Number(v))} options={chip.qubits.map((x: Json) => String(x.qubit_index))} label="qubit" />}
                explain={<Equation block tex={"f_{01}(\\Phi) = (f_{max}+E_C)\\,[\\cos^2\\pi\\Phi + d^2\\sin^2\\pi\\Phi]^{1/4} - E_C"} />}>
                <div className="flex flex-wrap gap-6">
                  <KV rows={[
                    [<span>f_max <InfoTip docKey="QubitSpec.f_max_ghz" /></span>, `${fmt(qb.f_max_ghz, 4)} GHz`],
                    [<span>Φ offset <InfoTip docKey="QubitSpec.phi_offset" /></span>, `${fmt(qb.phi_offset, 4)} Φ₀`],
                    ["idle f01", `${fmt(qb.f01_ghz, 5)} GHz`], ["df/dΦ (flux noise sensitivity)", `${fmt(qb.df_dphi_ghz, 4)} GHz/Φ₀`],
                    [<span>T1 <InfoTip docKey="QubitSpec.t1_us" /></span>, `${fmt(qb.t1_us, 1)} µs`],
                    [<span>T2* <InfoTip docKey="QubitSpec.t2_star_us" /></span>, `${fmt(qb.t2_star_us, 1)} µs`],
                    ["pure dephasing Tφ", qb.t_phi_us ? `${fmt(qb.t_phi_us, 1)} µs` : "∞"],
                    [<span>thermal n̄ <InfoTip docKey="QubitSpec.t_eff_mk" /></span>, fmt(qb.nbar, 5)],
                    ["P(|0⟩,|1⟩,|2⟩) at rest", qb.thermal_populations.map((p: number) => fmt(p, 4)).join(", ")],
                    [<span>Rabi at full scale <InfoTip docKey="QubitSpec.rabi_max_ghz" /></span>, `${fmt(qb.rabi_max_ghz * 1e3, 1)} MHz`],
                  ]} />
                  <Levels q={qb} />
                </div>
              </Panel>
            </div>
            <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
              <Panel title="Flux tuning curve" subtitle="The qubit idles at its flux offset; slope sets its sensitivity to flux noise">
                <LineChart x={qb.flux_curve.phi} xLabel="Φ (Φ₀)" yLabel="f01 (GHz)" height={220}
                  lines={[{ label: "f01(Φ)", y: qb.flux_curve.f01_ghz }, { label: "idle point", y: qb.flux_curve.phi.map((p: number) => Math.abs(p - qb.phi_offset) < 0.003 ? qb.f01_ghz : null), points: true, color: 1 }]} />
              </Panel>
              <Panel title="TLS defects near this qubit" subtitle="T1 limit vs qubit frequency; a defect in resonance shortens T1 sharply"
                explain={<Equation block tex={"\\Gamma_1(f) = \\Gamma_1^{0} + \\sum_k \\frac{g_k^2\\,\\gamma_k}{(f-f_k)^2 + (\\gamma_k/2)^2}"} />}>
                {chip.tls_curves[qi].f_ghz.length ? (
                  <LineChart x={chip.tls_curves[qi].f_ghz} xLabel="frequency (GHz)" yLabel="T1 limit (µs)" height={200}
                    lines={[{ label: "T1(f)", y: chip.tls_curves[qi].t1_limit_us }]} />
                ) : <p className="text-[12px] text-mute">No dynamics block in this device: no TLS defects are simulated.</p>}
              </Panel>
              <Panel title="Frequency drift" subtitle={`f01 over ${hours} h of lab time (1/f flux noise + scenarios)`}>
                <LineChart x={chip.drift.t_hours} xLabel="lab time (h)" yLabel="Δf01 (kHz)" height={200}
                  lines={chip.qubits.map((x: Json, i: number) => ({ label: `q${x.qubit_index}`, y: chip.drift.f01_ghz[i].map((f: number) => (f - x.f01_ghz) * 1e6) }))} />
              </Panel>
              <Panel title="T1 drift" subtitle="Log-normal OU wander, TLS hits and bursts, on the same clock">
                <LineChart x={chip.drift.t_hours} xLabel="lab time (h)" yLabel="T1 (µs)" height={200}
                  lines={chip.qubits.map((x: Json, i: number) => ({ label: `q${x.qubit_index}`, y: chip.drift.t1_us[i] }))} />
              </Panel>
            </div>
            <Panel title="Couplers" subtitle="Fixed exchange coupling: CZ via the |11⟩–|02⟩ crossing, static ZZ when idle">
              <table className="num w-full text-[12px]">
                <thead className="text-left text-[10.5px] text-mute"><tr><th className="py-1">pair</th><th>J <InfoTip docKey="CouplerSpec.j_mhz" /></th><th>detuning</th><th>CZ time</th><th>static ZZ</th></tr></thead>
                <tbody>{chip.couplers.map((c: Json) => (
                  <tr key={c.qubit_pair.join("-")} className="border-t border-line"><td className="py-0.5">q{c.qubit_pair[0]}–q{c.qubit_pair[1]}</td>
                    <td>{fmt(c.j_mhz, 2)} MHz</td><td>{fmt(c.detuning_mhz, 1)} MHz</td><td>{fmt(c.cz_time_ns, 1)} ns</td><td>{fmt(c.zz_khz, 1)} kHz</td></tr>))}</tbody>
              </table>
            </Panel>
            {chip.dynamics && <p className="text-[11.5px] text-mute"><Badge>dynamics</Badge> σ(ln T1) {chip.dynamics.t1_sigma_ln}, τ {chip.dynamics.t1_tau_s} s, 1/f amplitude {chip.dynamics.flux_noise_ghz} GHz, {chip.dynamics.tls_per_qubit} TLS/qubit, bursts {String(chip.dynamics.bursts)} · TLS ranges and burst shape are fixed in code (src/qcss/device/tls.py, bursts.py).</p>}
          </>
        )}
      </StateBox>
    </div>
  );
}
