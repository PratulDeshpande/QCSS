import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "./api";
import { calibrationWrite } from "./calibration";
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
