import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "./api";
import { calibrationWrite } from "./calibration";
import { Leaf } from "./views/ConfigStudio";

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
