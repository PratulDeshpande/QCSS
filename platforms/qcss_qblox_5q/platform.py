"""5-qubit transmon chip on a cluster: one drive and one flux line per qubit, one readout feedline."""
import os
import pathlib

from qibolab import AcquisitionChannel, DcChannel, Hardware, IqChannel, Qubit

from qcss_qibolab.controller import QcssController

FOLDER = pathlib.Path(__file__).parent
ADDRESS = os.environ.get("QCSS_QBLOX_5Q_ADDRESS", "192.168.0.20:50051")


def create() -> Hardware:
    qubits, channels = {}, {}
    for q in range(5):
        qubits[q] = qubit = Qubit.default(q)
        channels |= {
            qubit.drive: IqChannel(mixer=None, lo=None),
            qubit.probe: IqChannel(mixer=None, lo=None),
            qubit.acquisition: AcquisitionChannel(probe=qubit.probe, twpa_pump=None),
            qubit.flux: DcChannel(),
        }
    cluster = QcssController(address=ADDRESS, channels=channels)
    return Hardware(instruments={"cluster": cluster}, qubits=qubits)
