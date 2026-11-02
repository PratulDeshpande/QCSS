"""5-qubit transmon chip on a ZCU216 running qibosoq: one drive and one flux DAC per qubit, one readout DAC."""
import os
import pathlib

from qibolab import AcquisitionChannel, DcChannel, Hardware, IqChannel, Qubit
from qibolab.instruments.qibosoq import RFSoC

FOLDER = pathlib.Path(__file__).parent
ADDRESS = os.environ.get("QCSS_RFSOC_5Q_ADDRESS", "192.168.0.81:6000")


def create() -> Hardware:
    qubits, channels = {}, {}
    for q in range(5):
        qubits[q] = qubit = Qubit.default(q)
        channels |= {
            qubit.drive: IqChannel(path=str(q), mixer=None, lo=None),
            qubit.probe: IqChannel(path="10", mixer=None, lo=None),
            qubit.acquisition: AcquisitionChannel(path=str(q), probe=qubit.probe, twpa_pump=None),
            qubit.flux: DcChannel(path=str(5 + q)),
        }
    board = RFSoC(address=ADDRESS, channels=channels)
    return Hardware(instruments={"tii_rfsoc4x2": board}, qubits=qubits)
