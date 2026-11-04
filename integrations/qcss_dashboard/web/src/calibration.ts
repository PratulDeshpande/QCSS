import type { Json } from "./api";

/** The snapshot to write for one qubit. QCSS replaces a written qubit's calibration wholesale (CopyFrom), so the
 *  edits are merged over the qubit's full current calibration; cleared inputs (NaN) keep the current value. */
export function calibrationWrite(current: Json, edits: Json, qubit: number): { qubits: Json[] } {
  const kept = Object.fromEntries(Object.entries(edits).filter(([, v]) => typeof v !== "number" || Number.isFinite(v)));
  return { qubits: [{ ...structuredClone(current), ...kept, qubit_index: qubit }] };
}
