import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RegistryProvider, useFieldDoc } from "./registry";
import { FieldExplain, constraintText, fmt } from "./ui";

const T1 = {
  key: "QubitSpec.t1_us", model: "QubitSpec", field: "t1_us", layer: "B", type: "float", default: null, required: true,
  repeated: false, constraints: { gt: 0 }, choices: [], unit: "µs", summary: "Energy relaxation time T1.",
  detail: "The baseline; drift moves it.", equation: "\\Gamma_1 = 1/T_1", source: "src/qcss/physics/transmon.py:17",
  inert: false, apply: "restart",
};

function Probe() {
  const doc = useFieldDoc("QubitSpec.t1_us");
  return doc ? <FieldExplain doc={doc} /> : <span>loading</span>;
}

function mount(depth: string) {
  localStorage.setItem("qcss-depth", depth);
  const qc = new QueryClient();
  render(<QueryClientProvider client={qc}><RegistryProvider><Probe /></RegistryProvider></QueryClientProvider>);
}

describe("formatting", () => {
  it("keeps ordinary numbers fixed and switches to exponent for tiny or huge ones", () => {
    expect(fmt(5.12345, 2)).toBe("5.12");
    expect(fmt(0.00002)).toBe("2.00e-5");
    expect(fmt(4.2e9)).toBe("4.20e+9");
    expect(fmt(null)).toBe("—");
    expect(fmt(Number.NaN)).toBe("—");
  });
  it("renders constraints the way the validator states them", () => {
    expect(constraintText({ gt: 0 })).toBe("> 0");
    expect(constraintText({ ge: 1, le: 4 })).toBe("≥ 1, ≤ 4");
    expect(constraintText(undefined)).toBe("");
  });
});

describe("layered explanations", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ layers: [], apply_modes: {}, models: {}, fields: [T1] }))));
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); localStorage.clear(); });

  it("plain depth shows only the summary", async () => {
    mount("plain");
    await waitFor(() => expect(screen.getByText("Energy relaxation time T1.")).toBeTruthy());
    expect(screen.queryByText("The baseline; drift moves it.")).toBeNull();
    expect(screen.queryByText("src/qcss/physics/transmon.py:17")).toBeNull();
  });

  it("expert depth adds detail, type, default and range but not the source path", async () => {
    mount("expert");
    await waitFor(() => expect(screen.getByText("The baseline; drift moves it.")).toBeTruthy());
    expect(screen.getByText(/type float · > 0 · required/)).toBeTruthy();
    expect(screen.queryByText("src/qcss/physics/transmon.py:17")).toBeNull();
  });

  it("source depth also names the code that implements the field", async () => {
    mount("source");
    await waitFor(() => expect(screen.getByText("src/qcss/physics/transmon.py:17")).toBeTruthy());
  });

  it("marks device fields as hidden truth and shows the apply mode", async () => {
    mount("plain");
    await waitFor(() => expect(screen.getByText(/truth/)).toBeTruthy());
    expect(screen.getByText("restart")).toBeTruthy();
  });
});
