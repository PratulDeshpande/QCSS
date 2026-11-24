import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "./api";
import { calibrationWrite } from "./calibration";
import { WorkbenchProvider, useWorkbench } from "./state";
import { ErrorBoundary, NumberField, Tabs } from "./ui";
import { CalibrationEditor, Leaf } from "./views/ConfigStudio";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("calibration write (review C1)", () => {
  const current = {
    qubit_index: 0, drive_frequency_hz: 5.05e9, readout_frequency_hz: 7.02e9, readout_delay_ticks: 273,
    pi_amplitude: 0.45, drive_mixer: { dc_offset_i: 0.01, dc_offset_q: 0, gain_ratio: 1.02, phase_skew_rad: 0.01 },
  };

  it("keeps every field the operator did not touch, including nested corrections", () => {
    const snap = calibrationWrite(current, { drive_frequency_hz: 5.0501e9 }, 0);
    expect(snap.qubits).toHaveLength(1);
    expect(snap.qubits[0]).toEqual({ ...current, drive_frequency_hz: 5.0501e9 });
  });

  it("ignores cleared (NaN) inputs instead of zeroing the field", () => {
    const snap = calibrationWrite(current, { readout_frequency_hz: Number.NaN }, 0);
    expect(snap.qubits[0].readout_frequency_hz).toBe(7.02e9);
  });
});

describe("calibration editor", () => {
  function open(qubits: object[]) {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => new Response(
      JSON.stringify(String(url).includes("/lab/calibration") ? { calibration_epoch: 3, qubits } : {}),
      { status: 200, headers: { "content-type": "application/json" } })));
    render(<QueryClientProvider client={new QueryClient()}><CalibrationEditor /></QueryClientProvider>);
  }
  const write = () => screen.getByRole("button", { name: /Write/ }) as HTMLButtonElement;
  const field = () => screen.findByLabelText(/drive_frequency_hz/) as Promise<HTMLInputElement>;

  it("does not carry edits typed for one qubit over to another", async () => {
    open([{ qubit_index: 0, drive_frequency_hz: 5e9 }, { qubit_index: 1, drive_frequency_hz: 6e9 }]);
    fireEvent.change(await field(), { target: { value: "5100000000" } });
    expect(write().disabled).toBe(false);
    fireEvent.change(screen.getByLabelText("qubit"), { target: { value: "1" } });
    expect(write().disabled).toBe(true);
    expect((await field()).value).toBe("6000000000");
  });

  it("refuses to write a qubit it has no calibration for, which would wipe its other fields", async () => {
    open([{ qubit_index: 1, drive_frequency_hz: 6e9 }]);
    fireEvent.change(await field(), { target: { value: "5100000000" } });
    expect(write().disabled).toBe(true);
  });
});

describe("config tree leaf (review I3)", () => {
  it("shows the new value when the underlying data changes", () => {
    const { rerender } = render(<Leaf value={52} onChange={() => {}} />);
    expect((screen.getByRole("spinbutton") as HTMLInputElement).value).toBe("52");
    rerender(<Leaf value={70} onChange={() => {}} />);
    expect((screen.getByRole("spinbutton") as HTMLInputElement).value).toBe("70");
  });
});

describe("api errors (review I5)", () => {
  it("turns a non-JSON error body into an ApiError with that text", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("Internal Server Error", { status: 500 })));
    const err = (await api.get("/x").catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(500);
    expect(err.message).toContain("Internal Server Error");
  });
});

describe("number field (review: NaN reached query keys and request bodies)", () => {
  const box = () => screen.getByRole("spinbutton") as HTMLInputElement;

  it("reports typed numbers but not a cleared field", () => {
    const seen: number[] = [];
    render(<NumberField label="x" value={5} onChange={(v) => seen.push(v)} />);
    fireEvent.change(box(), { target: { value: "" } });
    fireEvent.change(box(), { target: { value: "7" } });
    expect(seen).toEqual([7]);
  });

  it("reports blank as NaN only when the field is blankable", () => {
    const seen: number[] = [];
    render(<NumberField label="x" value={5} blankable onChange={(v) => seen.push(v)} />);
    fireEvent.change(box(), { target: { value: "" } });
    expect(seen).toHaveLength(1);
    expect(Number.isNaN(seen[0])).toBe(true);
  });

  it("follows the value when it changes from outside", () => {
    const { rerender } = render(<NumberField label="x" value={5} onChange={() => {}} />);
    rerender(<NumberField label="x" value={9} onChange={() => {}} />);
    expect(box().value).toBe("9");
  });
});

describe("tabs keyboard (review a11y)", () => {
  it("moves between tabs with the arrow keys", () => {
    const seen: string[] = [];
    render(<Tabs value="a" onChange={(t) => seen.push(t)} tabs={[{ id: "a", label: "A" }, { id: "b", label: "B" }]} />);
    const a = screen.getByRole("tab", { name: "A" });
    a.focus();
    fireEvent.keyDown(a, { key: "ArrowRight" });
    expect(seen).toEqual(["b"]);
    expect(document.activeElement).toBe(screen.getByRole("tab", { name: "B" }));
  });
});

describe("error boundary (review: one view crash blanked the app)", () => {
  it("shows a readable fallback and recovers on retry", () => {
    let boom = true;
    const Bad = () => { if (boom) throw new Error("kaput"); return <p>fine</p>; };
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(<ErrorBoundary><Bad /></ErrorBoundary>);
    expect(screen.getByRole("alert").textContent).toContain("kaput");
    boom = false;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(screen.getByText("fine")).toBeTruthy();
  });
});

describe("what-if sweep values (review)", () => {
  it("drops blank and non-numeric entries instead of running 0", async () => {
    vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }));  // uPlot, via the charts
    const { parseSweepValues } = await import("./views/WhatIf");
    expect(parseSweepValues("10,,20, x ,")).toEqual([10, 20]);
  });
});

describe("workbench (review: stale explain, unreadable live message)", () => {
  class FakeSocket { static last: FakeSocket; onmessage: ((e: { data: string }) => void) | null = null; onclose = null; constructor() { FakeSocket.last = this; } close() {} }
  function Probe() {
    const { wb, set, explain, liveError } = useWorkbench();
    return (<>
      <button onClick={explain.run}>run</button>
      <button onClick={() => set({ profile: "other" })}>switch</button>
      <output data-testid="out">{wb.profile}|{explain.data ? "result" : "none"}|{liveError ?? ""}</output>
    </>);
  }
  const setup = () => {
    vi.stubGlobal("WebSocket", FakeSocket);
    vi.stubGlobal("fetch", vi.fn(async (url: string) => new Response(JSON.stringify(String(url).includes("explain") ? { valid: true } : {}), { status: 200 })));
    render(<QueryClientProvider client={new QueryClient()}><WorkbenchProvider><Probe /></WorkbenchProvider></QueryClientProvider>);
  };
  const out = () => screen.getByTestId("out").textContent;

  it("drops the explain result when the profile changes", async () => {
    setup();
    fireEvent.click(screen.getByText("run"));
    await waitFor(() => expect(out()).toContain("|result|"));
    fireEvent.click(screen.getByText("switch"));
    await waitFor(() => expect(out()).toBe("other|none|"));
  });

  it("reports an unreadable live message instead of throwing", () => {
    setup();
    act(() => FakeSocket.last.onmessage?.({ data: "not json" }));
    expect(out()).toContain("unreadable");
  });
});
