import { useQuery } from "@tanstack/react-query";
import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { api } from "./api";

export type FieldDoc = {
  key: string; model: string; field: string; layer: string; type: string; default: unknown; required: boolean;
  repeated: boolean; constraints: Record<string, number>; choices: string[]; unit: string; summary: string;
  detail: string; equation: string; source: string; inert: boolean; apply: string;
};
export type ModelDoc = { name: string; layer: string; summary: string; detail: string; source: string; fields: string[] };
export type Layer = { id: string; name: string; owner: string; file: string; when: string; summary: string };
export type Registry = {
  layers: Layer[]; apply_modes: Record<string, string>; models: Record<string, ModelDoc>; fields: FieldDoc[];
};

/** How deep every explanation goes: plain words, plus expert detail, plus equations and source paths. */
export type Depth = "plain" | "expert" | "source";
type Ctx = { reg?: Registry; byKey: Map<string, FieldDoc>; depth: Depth; setDepth: (d: Depth) => void };
const RegistryContext = createContext<Ctx>({ byKey: new Map(), depth: "expert", setDepth: () => {} });

export function RegistryProvider({ children }: { children: ReactNode }) {
  const { data } = useQuery({ queryKey: ["registry"], queryFn: () => api.get<Registry>("/registry"), staleTime: Infinity });
  const [depth, setDepth] = useState<Depth>(() => (localStorage.getItem("qcss-depth") as Depth) || "expert");
  const byKey = useMemo(() => new Map((data?.fields ?? []).map((f) => [f.key, f])), [data]);
  const set = (d: Depth) => {
    localStorage.setItem("qcss-depth", d);
    setDepth(d);
  };
  return <RegistryContext.Provider value={{ reg: data, byKey, depth, setDepth: set }}>{children}</RegistryContext.Provider>;
}

export const useRegistry = () => useContext(RegistryContext);
export const useFieldDoc = (key: string) => useContext(RegistryContext).byKey.get(key);
