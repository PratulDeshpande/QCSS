import { useMutation, useQuery } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, eventsUrl, type Json } from "./api";

/** The workbench: which hardware and chip the sandbox simulates, which job it runs, and the last explain run.
 *  Drafts from the Config Studio can be pushed here, so every view can be recomputed on an unsaved configuration. */
export type Workbench = {
  profile: string; device: string; profileYaml?: string; deviceYaml?: string;
  job: Json | null; jobName: string; tier: string; seed: number; shots: number; point: number;
};

type Ctx = {
  wb: Workbench; set: (p: Partial<Workbench>) => void; configBody: () => Json;
  explain: { data?: Json; error: unknown; isPending: boolean; run: () => void };
  live: Json | null; liveError: string | null;
};
const RESETS_EXPLAIN = ["profile", "device", "profileYaml", "deviceYaml", "job"];
const WorkbenchContext = createContext<Ctx | null>(null);

export function WorkbenchProvider({ children }: { children: ReactNode }) {
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api.get<Json>("/settings") });
  const [wb, setWb] = useState<Workbench>({
    profile: "qblox_cluster_5q", device: "transmon_5q", job: null, jobName: "", tier: "AUTO", seed: 1, shots: 200, point: 0,
  });
  useEffect(() => {
    const s = settings.data;
    if (s?.chassis_profile) setWb((w) => ({ ...w, profile: s.chassis_profile, device: s.chassis_device ?? w.device }));
  }, [settings.data]);
  const configBody = useCallback((): Json => ({
    profile: wb.profile, device: wb.device, profile_yaml: wb.profileYaml, device_yaml: wb.deviceYaml,
  }), [wb.profile, wb.device, wb.profileYaml, wb.deviceYaml]);
  const m = useMutation({
    mutationFn: () => api.post<Json>("/sandbox/explain", {
      ...configBody(), job: wb.job, tier: wb.tier, seed: wb.seed, shots: wb.shots, point: wb.point,
    }),
  });
  // A result belongs to the profile, device and job it ran with: drop it when any of them changes.
  const resetExplain = m.reset;
  const set = useCallback((p: Partial<Workbench>) => {
    if (RESETS_EXPLAIN.some((k) => k in p)) resetExplain();
    setWb((w) => ({ ...w, ...p }));
  }, [resetExplain]);
  const live = useLive();
  const value = useMemo<Ctx>(() => ({
    wb, set, configBody,
    explain: { data: m.data, error: m.error, isPending: m.isPending, run: () => m.mutate() },
    live: live.data, liveError: live.error,
  }), [wb, set, configBody, m, live.data, live.error]);
  return <WorkbenchContext.Provider value={value}>{children}</WorkbenchContext.Provider>;
}

export function useWorkbench(): Ctx {
  const c = useContext(WorkbenchContext);
  if (!c) throw new Error("useWorkbench outside WorkbenchProvider");
  return c;
}

/** Live chassis state over the bridge WebSocket, reconnecting with backoff. */
function useLive(): { data: Json | null; error: string | null } {
  const [data, setData] = useState<Json | null>(null);
  const [error, setError] = useState<string | null>(null);
  const retry = useRef(0);
  useEffect(() => {
    let ws: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let closed = false;
    const connect = () => {
      ws = new WebSocket(eventsUrl());
      ws.onmessage = (e) => {
        try {
          const d = JSON.parse(e.data);
          retry.current = 0; setError(null); setData(d);
        } catch {
          setError("live link sent an unreadable message");   // keep the last good data, but say it may be stale
        }
      };
      ws.onclose = () => {
        if (closed) return;
        setError("live link lost — reconnecting");
        timer = setTimeout(connect, Math.min(10000, 500 * 2 ** retry.current++));
      };
    };
    connect();
    return () => { closed = true; clearTimeout(timer); ws?.close(); };
  }, []);
  return { data, error };
}
