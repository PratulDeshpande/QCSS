import { useQuery } from "@tanstack/react-query";
import { api, type Json } from "../api";
import { Badge, Deep, KV, LabBadge, Panel, SourceRef, StateBox } from "../ui";

const FACES = [
  { name: "Qibolab controller", status: "shipped", proto: "gRPC ControlService (lab link)", src: "integrations/qcss_qibolab/src/qcss_qibolab/controller.py",
    how: "A Qibolab 0.2.17 Controller: on connect it calls DescribeDevice; each play translates the pulse sequence into a QCSS Job, merges calibration with compare-and-swap, submits pinned to that epoch, waits and streams results. Platforms in platforms/qcss_qblox_5q load like any lab platform.",
    map: [["pulse sequence", "Job.main instructions on xy/ro/flux channels"], ["platform parameters.json", "UpdateCalibration (epoch-pinned)"], ["sweepers", "Job.sweeps"], ["acquisition type", "AcquisitionMode"]] },
  { name: "Qibosoq board face", status: "shipped", proto: "TCP + 4-byte length + JSON (qibosoq protocol)", src: "src/qcss/boards/qibosoq.py",
    how: "Speaks the Qibosoq server protocol so the stock Qibolab RFSoC driver connects to QCSS as to a board; only the IP differs from a real lab. Requests become QCSS jobs; replies are window sums divided by the decimated length.",
    map: [["cfg.reps", "Job.num_shots"], ["cfg.relaxation_time (µs)", "repetition_delay_ticks"], ["element start_delay (µs)", "start ticks snapped to the real-time grid"], ["frequency (MHz) / amplitude / relative_phase (deg)", "SetFrequency / Play.amplitude / phase (rad)"], ["sweepers (freq, gain, phase, t, duration)", "program_points"]] },
  { name: "Native QICK (Pyro4 QickSoc)", status: "in progress on feat/qick-native-face", proto: "Pyro4 QickSoc (tProc v1 and v2), ZCU216 firmware description", src: "src/qcss/boards/qick/ (not on this branch)",
    how: "Registers a QickSoc stand-in with a Pyro4 name server so unmodified qick client code (make_proxy, AveragerProgramV2, acquire) runs against the virtual lab. tProc binaries are decoded and executed, pulses translated into QCSS jobs, results placed into the accumulated and decimated buffers. The dashboard's QICK views land when that branch is merged.",
    map: [["tProc pmem", "decoded and interpreted (v1 64-bit, v2 72-bit)"], ["generator registers", "tones, envelopes, Nyquist images"], ["triggers", "Acquire windows"], ["accumulated / decimated buffers", "ADC counts from QCSS IQ"]] },
];

export function Boards() {
  const describe = useQuery({ queryKey: ["describe"], queryFn: () => api.get<Json>("/lab/describe") });
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-[18px] font-semibold">Board faces</h1>
        <p className="mt-1 max-w-4xl text-[13px] text-ink2">The faces are how real client software reaches the virtual lab without knowing it is virtual. Each translates its protocol into
          the same QCSS job, so every face shares one chip, one calibration store and one set of hardware rules. Errors come back in the board's own voice.</p>
      </div>
      <Panel title={<span className="flex items-center gap-2">What every client sees: DescribeDevice <LabBadge /></span>} subtitle="The instrument's self-description over the lab link">
        <StateBox state={describe.isPending ? "loading" : describe.isError ? "error" : "ok"} error={describe.error}>
          {describe.data && (
            <div className="grid grid-cols-1 gap-5 xl:grid-cols-[280px_1fr]">
              <KV rows={[["profile", describe.data.profile_name], ["vendor", describe.data.vendor], ["tick", `${describe.data.tick_hz} Hz`],
                ["max discriminated states", describe.data.max_discriminated_states], ["default repetition delay", `${describe.data.default_repetition_delay_ticks} ticks`]]} />
              <div className="max-h-72 overflow-y-auto">
                <table className="num w-full text-[11.5px]">
                  <thead className="text-left text-[10.5px] text-mute"><tr><th className="py-1">channel</th><th>kind</th><th>generator</th><th>port</th><th>frame</th><th>sample rate</th><th>LO</th></tr></thead>
                  <tbody>{describe.data.channels.map((c: Json) => (
                    <tr key={c.channel_id} className="border-t border-line"><td className="py-0.5 text-ink">{c.channel_id}</td><td>{String(c.kind).replace("CHANNEL_KIND_", "").toLowerCase()}</td>
                      <td>{c.generator_id}</td><td>{c.port_id}</td><td>{c.frame_id}</td><td>{(c.sample_rate_hz / 1e9).toFixed(3)} GS/s</td><td>{c.lo_frequency_hz ? `${(c.lo_frequency_hz / 1e9).toFixed(3)} GHz` : "—"}</td></tr>))}</tbody>
                </table>
              </div>
            </div>
          )}
        </StateBox>
      </Panel>
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
        {FACES.map((f) => (
          <Panel key={f.name} title={f.name} subtitle={f.proto} actions={<Badge tone={f.status === "shipped" ? "good" : "warn"}>{f.status}</Badge>}>
            <p className="text-[12px] leading-relaxed text-ink2">{f.how}</p>
            <table className="mt-3 w-full text-[11.5px]"><tbody>{f.map.map(([a, b]) => (
              <tr key={a} className="border-t border-line align-top"><td className="py-1 pr-2 text-ink">{a}</td><td className="text-mute">→ {b}</td></tr>))}</tbody></table>
            <Deep at="source"><div className="mt-2"><SourceRef path={f.src} /></div></Deep>
          </Panel>
        ))}
      </div>
    </div>
  );
}
