import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { api, type Json } from "../api";
import { useWorkbench } from "../state";
import { Badge, Button, NumberField, Select, StateBox } from "../ui";

/** Which profile and device the sandbox views compute with (names; drafts come from the Config Studio). */
export function ProfilePicker({ device = true }: { device?: boolean }) {
  const { wb, set } = useWorkbench();
  const list = useQuery({ queryKey: ["configs"], queryFn: () => api.get<Json>("/configs") });
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select value={wb.profile} onChange={(v) => set({ profile: v, profileYaml: undefined })}
        options={(list.data?.profile ?? []).map((c: Json) => c.name)} label="profile" />
      {device && <Select value={wb.device} onChange={(v) => set({ device: v, deviceYaml: undefined })}
        options={(list.data?.device ?? []).map((c: Json) => c.name)} label="device" />}
    </div>
  );
}

export function DraftNote() {
  const { wb, set } = useWorkbench();
  if (!wb.profileYaml && !wb.deviceYaml) return null;
  return (
    <div className="flex items-center gap-3 rounded-md border border-warn/50 bg-warn/10 px-3 py-2 text-[12px] text-ink2">
      <Badge tone="warn">draft</Badge>
      Computing with an unsaved {wb.profileYaml ? "profile" : ""}{wb.profileYaml && wb.deviceYaml ? " and " : ""}{wb.deviceYaml ? "device" : ""} draft from the Config Studio.
      <Button kind="ghost" onClick={() => set({ profileYaml: undefined, deviceYaml: undefined })}>Discard draft</Button>
    </div>
  );
}

const TIERS = ["AUTO", "T0", "T1A", "T1B", "T2"];

/** The run bar shared by Program, Physics and Timing: pick a job, tier, seed, shots, sweep point; run the sandbox. */
export function RunBar() {
  const { wb, set, explain } = useWorkbench();
  const examples = useQuery({ queryKey: ["examples"], queryFn: () => api.get<Json>("/examples") });
  useEffect(() => {
    const jobs = examples.data?.jobs;
    if (jobs && !wb.job) {
      const first = jobs.rabi_amplitude_q0 ? "rabi_amplitude_q0" : Object.keys(jobs)[0];
      if (first) set({ job: jobs[first], jobName: first });
    }
  }, [examples.data, wb.job, set]);
  const nPoints = explain.data?.plan?.n_points ?? 1;
  return (
    <div className="flex flex-wrap items-end gap-3 rounded-lg border border-line bg-s1 p-3">
      <Select value={wb.jobName} onChange={(n) => set({ job: examples.data?.jobs?.[n], jobName: n, point: 0 })}
        options={[...Object.keys(examples.data?.jobs ?? {}), ...(wb.jobName && !examples.data?.jobs?.[wb.jobName] ? [wb.jobName] : [])]} label="job" />
      <Select value={wb.tier} onChange={(t) => set({ tier: t })} options={TIERS} label="tier" />
      <NumberField label="seed" value={wb.seed} onChange={(v) => set({ seed: v })} width="w-20" />
      <NumberField label="shots" value={wb.shots} onChange={(v) => set({ shots: v })} min={1} max={2000} width="w-20" />
      <NumberField label={`sweep point (0–${nPoints - 1})`} value={wb.point} onChange={(v) => set({ point: v })} min={0} width="w-20" />
      <ProfilePicker />
      <Button kind="primary" onClick={explain.run} disabled={!wb.job || explain.isPending}>{explain.isPending ? "Simulating…" : "▶ Run in sandbox"}</Button>
      {explain.data?.plan && <span className="text-[11.5px] text-ink2">tier <b>{explain.data.plan.tier}</b> · {explain.data.plan.reason}</span>}
    </div>
  );
}

/** Wraps a view that needs an explain run: shows the right state until there is a valid result. */
export function NeedsRun({ children }: { children: (d: Json) => React.ReactNode }) {
  const { explain } = useWorkbench();
  if (explain.isPending) return <StateBox state="loading" />;
  if (explain.error) return <StateBox state="error" error={explain.error} onRetry={explain.run} />;
  if (!explain.data) return <StateBox state="empty" empty={<>Pick a job and press <b>Run in sandbox</b>: QCSS plans, renders, evolves and reads it out in this process, keeping every intermediate.</>} />;
  if (explain.data.valid === false) {
    return (
      <div role="alert" className="rounded-lg border border-crit/50 bg-crit/10 p-4 text-[12.5px]">
        <div className="font-semibold text-crit">The instrument refused this job at the {explain.data.stage} stage</div>
        <p className="mt-1 text-ink2">Exactly what a real driver would return (INVALID_ARGUMENT with field violations):</p>
        <ul className="mt-2 space-y-1">{explain.data.violations.map((v: Json, i: number) => <li key={i}><code className="font-mono text-ink">{v.path}</code> — {v.description}</li>)}</ul>
      </div>
    );
  }
  return <>{children(explain.data)}</>;
}
