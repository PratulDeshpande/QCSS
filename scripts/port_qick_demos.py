"""Regenerate notebooks/qick from the official qick_demos at the pinned qick version (0.2.370, commit 9d98886):
swap the on-board connect for make_proxy, set the channels, apply the marked QCSS edits, turn cells QCSS cannot run
into visible gap cells, add the setup / proof / truth / teardown cells.
Usage: git clone https://github.com/openquantumhardware/qick <dir> && git -C <dir> checkout 9d98886
       python scripts/port_qick_demos.py <dir>/qick_demos notebooks/qick NAME [NAME...]"""
import json
import re
import sys
from pathlib import Path

UPSTREAM_COMMIT = "9d98886"   # qick 0.2.370
SRC, OUT = Path(sys.argv[1]), Path(sys.argv[2])

# per-notebook edits: (regex, replacement) applied to code cells, each must match at least once
CABLE = "  # QCSS bench cable: generator 1 -> readout 0 (on a real board: the DAC you cabled)"
EDITS = {
    "00_Send_receive_pulse": [(r"GEN_CH = 6", "GEN_CH = 1" + CABLE)],
    "02_Sweeping_variables": [(r'"res_ch":6, # --Fixed', '"res_ch":1, # --Fixed' + CABLE)],
    "05_PhaseCoherence_QickProgram": [(r'"res_ch":6, # --Fixed', '"res_ch":1, # --Fixed' + CABLE)],
    "03_Conditional_logic": [(r'"res_ch":6, # --Fixed', '"res_ch":1, # --Fixed' + CABLE)],
    "07_Sweep_ND_variables": [(r'"res_ch": 6,  # --Fixed', '"res_ch": 1,  # --Fixed' + CABLE)],
    "08_Special_buffers": [(r"GEN_CH = 6", "GEN_CH = 1" + CABLE),
                           (r"soc\['readouts'\]", "soccfg['readouts']  # QCSS: remotely the config is soccfg, not soc")],
    "06_qubit_demos": [
        # the ZCU216 build's channels: readout tones go out through the feedline's mux generator (gen 10), qubit 0's
        # drive is gen 0, and readout 0 is qubit 0's PFB output
        (r'"res_ch":5,', '"res_ch":10,  # QCSS: the feedline mux generator (on the authors\' ZCU111: gen 5)'),
        (r'"qubit_ch":2,', '"qubit_ch":0,  # QCSS: qubit 0\'s drive line'),
        (r'"readout_length":soccfg\.us2cycles\(3\.0, gen_ch=5\), # \[Clock ticks\]',
         '"readout_us": 3.0,  # QCSS: the probe length, us (the mux tone and the readout run on different clocks)\n'
         '    "readout_length":soccfg.us2cycles(3.0, ro_ch=0), # [Clock ticks]'),
        (r'"f_res": 99\.775 \+0\.18, # \[MHz\]', '"f_res": 7150.0, # [MHz]  QCSS: qubit 0\'s resonator, as specified'),
        (r'"res_gain":10000', '"res_gain":0.5  # QCSS: a mux tone\'s gain is a fraction of full scale'),
        (r'us2cycles\(0\.025, gen_ch=2\)', 'us2cycles(0.025, gen_ch=0)'),
        (r'"pi_gain": 11500,\n    "pi2_gain":11500//2, ',
         '"pi_gain": 7200,  # QCSS: this qubit\'s calibrated pi pulse (the amplitude Rabi below shows it)\n'
         '    "pi2_gain":7200//2, '),
        (r'"f_ge":4743\.041802067813,', '"f_ge":5050.0,  # QCSS: qubit 0, as specified'),
        (r'"relax_delay":500\n', '"relax_delay":150  # QCSS: about 3x the specified T1\n'),
        # every program: the readout through the mux generator, one readout
        (r'self\.declare_gen\(ch=cfg\["res_ch"\], nqz=1\) #Readout',
         'self.declare_gen(ch=cfg["res_ch"], nqz=2, ro_ch=0, mux_freqs=[cfg.get("frequency", cfg["f_res"])],\n'
         '                        mux_gains=[cfg["res_gain"]]) #Readout  # QCSS: a mux tone on the feedline'),
        (r'for ch in \[0,1\]:', 'for ch in [0]:  # QCSS: one readout, qubit 0\'s'),
        (r'adcs=\[0,1\]', 'adcs=[0]'),
        (r'freq=cfg\["f_res"\], gen_ch=cfg\["res_ch"\]\)', 'freq=cfg["f_res"], gen_ch=cfg["res_ch"], phase=cfg["res_phase"])'),
        (r'self\.set_pulse_registers\(ch=(cfg|self\.cfg)\["res_ch"\], style="const",[^)]*?\)',
         r'self.set_pulse_registers(ch=\1["res_ch"], style="const", length=self.us2cycles(cfg["readout_us"], '
         r'gen_ch=cfg["res_ch"]), mask=[0])  # QCSS: the mux tone (its freq and gain are in declare_gen)'),
        (r'adc1, adc2 = prog\.acquire_decimated\(soc, progress=True\)',
         'adc1, = prog.acquire_decimated(soc, progress=True)  # QCSS: one readout'),
        (r'\nplot\(adc2\[0\], label="I value; ADC 1"\)\nplot\(adc2\[1\], label="Q value; ADC 1"\)', ''),
        (r'"frequency": 100, # \[MHz\]', '"frequency": 7150, # [MHz]  QCSS: at the resonator'),
        (r"(?s)shots_i0=self\.di_buf\[0\].*?shots_q1=self\.dq_buf\[1\][^\n]*",
         "# QCSS: since qick 0.2.x di_buf holds per-point averages; single shots come from get_raw() (raw sums,\n"
         "        # in the same expts x reps order as before), so the original di_buf reshape fails on a real board too\n"
         "        raw=self.get_raw()[0].reshape((self.cfg[\"expts\"],self.cfg[\"reps\"],2))/self.cfg['readout_length']\n"
         "        shots_i0, shots_q0 = raw[:,:,0], raw[:,:,1]\n"
         "        shots_i1, shots_q1 = shots_i0, shots_q0  # QCSS: one readout"),
        (r"plot=True, ran=600\)", "plot=True, ran=30)  # QCSS: this board's blobs span ~20 ADC units, not ~600"),
        (r"soccfg\.deg2reg\(-angle\*180/pi, gen_ch=5\)",
         "-angle*180/pi  # QCSS: degrees, applied at the readout (a mux tone has no phase register)"),
        # smaller sweeps, so the notebook runs in minutes
        (r'"start":95, "step":0\.025, "expts":400', '"start":7147, "step":0.1, "expts":60'),
        (r'expt_cfg=\{"reps":500, "relax_delay":10,', 'expt_cfg={"reps":200, "relax_delay":10,'),
        (r'"shots":5000', '"shots":2000'),
        (r'"start":4741, "step":0\.01, "expts":400, "reps": 20,"rounds":50,',
         '"start":5047, "step":0.1, "expts":60, "reps": 200,"rounds":1,'),
        (r'us2cycles\(2\.0, gen_ch=2\), "qubit_gain":10', 'us2cycles(2.0, gen_ch=0), "qubit_gain":200'),
        (r'"start":4, "step":1, "expts":200, "reps": 400,', '"start":4, "step":4, "expts":50, "reps": 200,'),
        (r'"start":0, "step":100, "expts":300, "reps": 400\n       \}\nconfig=\{\*\*hw_cfg,\*\*readout_cfg,\*\*qubit_cfg,\*\*expt_cfg\} #combine configs\n\nrabi',
         '"start":0, "step":300, "expts":50, "reps": 200\n       }\nconfig={**hw_cfg,**readout_cfg,**qubit_cfg,**expt_cfg} #combine configs\n\nrabi'),
        (r'"start":0, "step":1, "expts":400, "reps": 400,\n        "relax_delay":750',
         '"start":0, "step":2, "expts":50, "reps": 200,\n        "relax_delay":150'),
        (r'gen_ch=2\), "expts":250,\n          "reps": 10, "rounds": 200', 'gen_ch=0), "expts":60,\n          "reps": 200, "rounds": 1'),
        (r'cycles2us\(np\.array\(expt_pts\), gen_ch=2\)', 'cycles2us(np.array(expt_pts), gen_ch=0)'),
        (r"cycles2us\(config\['sigma'\], gen_ch=2\)", "cycles2us(config['sigma'], gen_ch=0)")],
    "01_Phase_coherent_readout": [
        (r"out_chs = \[0,5,6\]", "out_chs = [1,2]  # QCSS bench cables: generator 1 -> readout 0, generator 2 -> readout 1"),
        (r"gen_ch=6, ro_ch=0\)", "gen_ch=1, ro_ch=0)  # QCSS: generator 1 is cabled to readout 0"),
        (r"(    data = \[\[prog\.di_buf)",
         "    # note: in qick 0.2.370 di_buf is already divided by the readout length, so mag below is 1/1000 of\n"
         "    # the decimated value on a real board too (this demo predates that change; QCSS returns what qick computes)\n"
         r"\1")],
}
SUMMARY = {
    "00_Send_receive_pulse": "Send a pulse out of a DAC and read it back on an ADC through a loopback cable.",
    "02_Sweeping_variables": "Sweep a pulse parameter (gain) inside the tProcessor with RAveragerProgram, "
                             "and compare with a Python-side sweep.",
    "03_Conditional_logic": "Branch inside a tProcessor program on a register value (conditional jumps).",
    "04_Reading_Math_Writing": "Do arithmetic in the tProcessor and write results to its data memory.",
    "07_Sweep_ND_variables": "Sweep several pulse parameters at once inside the tProcessor (NDAveragerProgram).",
    "08_Special_buffers": "The DDR4 and multi-rate buffers: long raw-ADC captures beyond the decimated buffer.",
    "09_photon_counting": "Count photon-like pulses with a threshold readout (written for an RFSoC 4x2 build).",
    "06_qubit_demos": "Characterise a real qubit: time of flight, resonator spectroscopy, single-shot readout, "
                      "qubit spectroscopy, Rabi, T1 and Ramsey. The upstream notebook was taken on its authors' "
                      "ZCU111 wiring; here the same programs read out through this ZCU216 build's multiplexed "
                      "readout generator, so their readout lines change (each marked `QCSS`), and the sweeps are "
                      "shorter so the notebook runs in minutes.",
    "01_Phase_coherent_readout": "Calibrate the phase of a phase-coherent readout: measure the readout phase "
                                 "against frequency through loopback cables and fit the cable delay.",
    "05_PhaseCoherence_QickProgram": "Check the phase coherence of the generator and readout across frequencies "
                                     "and repeated runs.",
}
LOOPBACK = ({n: ("1:0",) for n in SUMMARY} | {"01_Phase_coherent_readout": ("1:0", "2:1")}
            | {"04_Reading_Math_Writing": ("0:0",), "09_photon_counting": ("0:0",)}
            | {"06_qubit_demos": ()})     # a real qubit: the readout hears the resonator, no bench cable
# cells that cannot run on QCSS: (regex identifying the cell, reason, code reference). The upstream code stays
# visible, commented out, under a gap note.
TPROC = ("QCSS does not serve soc.tproc (raw tProc memory and program access); the AveragerProgram cells "
         "below make the same measurement through the served methods", "userdocs/reference/qick-surface.md")
GAPS = {"01_Phase_coherent_readout": [
    (r"soc\.tproc\.single_write", *TPROC),
    (r"load_program\(soc", *TPROC),
    (r"prog\.memri\(1,1,123", *TPROC),
    (r"soc\.readouts\[|soc\.avg_bufs\[", "QCSS does not serve soc.readouts / soc.avg_bufs (driver objects on the "
     "board)", "userdocs/reference/qick-surface.md")],
    "04_Reading_Math_Writing": [
        (r"soc\.tproc\.single_read", "QCSS does not serve soc.tproc, so the tProc data memory can't be read back "
         "from the client; the program itself compiles and runs", "userdocs/reference/qick-surface.md")],
    "08_Special_buffers": [
        (r"soc\.(clear_ddr4|arm_ddr4|get_ddr4|arm_mr|get_mr)\(|soc\.tproc\.", "QCSS does not serve the DDR4 and "
         "multi-rate buffers (clear_ddr4/arm_ddr4/get_ddr4/arm_mr/get_mr) or soc.tproc",
         "userdocs/reference/qick-surface.md"),
        (r"iq_list|iq_mr|complex_iq|\biq\[", "uses data captured by a skipped buffer cell above",
         "userdocs/reference/qick-surface.md")],
    "06_qubit_demos": [
        (r"QICK_wiring_new\.png", "the upstream authors' wiring photo is not included; the QCSS board's wiring is "
         "the ZCU216 description printed by print(soccfg)", "src/qcss/boards/qick/firmware.py"),
        (r"class ActiveResetProgram|areset", "active reset branches on a measurement inside the program "
         "(measurement feedback), which QCSS does not simulate yet", "notebooks/README.md")],
    "09_photon_counting": [
        (r"\bprog\b|\bcounts\b", "needs a photon-counting firmware build whose readout has an edge counter; the "
         "QCSS ZCU216 build has none, like a standard ZCU216 build, and qick itself refuses with 'channel has no "
         "edge counter'", "src/qcss/boards/qick/firmware.py")]}


# QCSS cells inserted after the upstream cell a regex matches (keep a result before a later cell overwrites it)
INSERT_AFTER = {
    "06_qubit_demos": [
        (r"qspec=PulseProbeSpectroscopyProgram\(soccfg, config\)",
         "# QCSS: keep the spectroscopy peak for the comparison with the true chip at the end\n"
         "f_ge_measured = expt_pts[np.argmax(avgi[0][0])]\n"
         "print(f'qubit spectroscopy peak: {f_ge_measured:.3f} MHz')"),
        (r"t1p=T1Program\(soccfg, config\)",
         "# QCSS: fit T1 from the data above, for the comparison with the true chip at the end\n"
         "from scipy.optimize import curve_fit\n"
         "decay = lambda t, a, t1, c: a * np.exp(-t / t1) + c\n"
         "(_, t1_measured, _), _ = curve_fit(decay, np.asarray(x_pts), np.asarray(avgi[0][0]), p0=(0.8, 20, 0.02))\n"
         "print(f'fitted T1: {t1_measured:.1f} us')")],
}
FINALE = {
    "06_qubit_demos":
        "## What QCSS adds: the true chip\n\n"
        "A real lab never learns what its qubit really is: it only has fits. QCSS can say. `lab.truth()` reads "
        "the simulated chip through the admin channel (which a client of the board never sees). The chip drifts "
        "slowly (flux noise, two-level defects), so the truth is read now, right after the measurements; the "
        "frequency tolerance covers that drift, the T1 tolerance the statistics of a 50-point sweep.",
}
FINALE_CODE = {
    "06_qubit_demos":
        "truth = lab.truth()[0]\n"
        "_proof.truth_table([\n"
        "    ('qubit 0 f01 (MHz)', f_ge_measured, truth['frequency_hz'] / 1e6, 1e-4),\n"
        "    ('qubit 0 T1 (us)', t1_measured, truth['t1_s'] * 1e6, 0.35),\n"
        "])",
}


def md(text):
    return {"cell_type": "markdown", "metadata": {}, "source": text}


def code(text, tags=()):
    return {"cell_type": "code", "metadata": {"tags": list(tags)}, "execution_count": None, "outputs": [],
            "source": text}


CONNECT = ('# QCSS: the official demo runs on the board itself (soc = QickSoc()). From a PC you reach a board through\n'
           "# QICK's Pyro4 server instead (qick.pyro.make_proxy) -- on a real board only ns_host would differ.\n"
           'from qick.pyro import make_proxy\n'
           'soc, soccfg = make_proxy(ns_host="127.0.0.1", ns_port=8888, proxy_name="myqick")\n'
           '_lab.keep_errors_visible()  # QCSS: make_proxy hides cell errors from Jupyter; keep them failing\n')


def port(name):
    nb = json.loads((SRC / f"{name}.ipynb").read_text(encoding="utf-8"))
    edits = EDITS.get(name, [])
    hits = [0] * len(edits)
    cells = []
    for c in nb["cells"]:
        c = dict(c, outputs=[], execution_count=None) if c["cell_type"] == "code" else dict(c)
        src = "".join(c["source"])
        if c["cell_type"] == "code":
            if re.search(r"^soc = QickSoc\(", src, re.M):
                src = re.sub(r"^soc = QickSoc\(.*\)\n?", CONNECT, src, flags=re.M)
                src = re.sub(r"^soccfg = soc\n?", "", src, flags=re.M)
            for k, (pat, rep) in enumerate(edits):
                src, n = re.subn(pat, rep, src)
                hits[k] += n
            for pat, reason, ref in GAPS.get(name, []):
                if re.search(pat, src):
                    src = (f"# QCSS gap: this upstream cell is not run on QCSS; its code is kept below, commented out.\n"
                           f"_proof.gap({reason!r}, {ref!r})\n\n" + "\n".join("# " + l for l in src.splitlines()))
                    break
        c["source"] = src
        cells.append(c)
        for pat, extra in INSERT_AFTER.get(name, []):
            if c["cell_type"] == "code" and re.search(pat, src) and "QCSS gap" not in src:
                cells.append(code(extra, tags=("qcss",)))
    missing = [edits[k][0] for k, h in enumerate(hits) if not h]
    assert not missing, f"{name}: edits matched nothing: {missing}"
    url = f"https://github.com/openquantumhardware/qick/blob/{UPSTREAM_COMMIT}/qick_demos/{name}.ipynb"
    head = md(f"# {name.replace('_', ' ')} — on QCSS\n\n"
              f"Adapted from the official QICK demo [`{name}.ipynb`]({url}) (qick 0.2.370, MIT License, "
              f"© 2021 Open Quantum Hardware).\n\n{SUMMARY[name]}\n\n"
              "**What changes from the official demo:** the two cells marked `QCSS` — starting the simulated board, "
              "and connecting through `make_proxy` instead of running on the board. Every other cell is the "
              "upstream code, unchanged except where a `QCSS` comment says so.\n\n"
              "**What this shows:** qick's own client library compiles, uploads and acquires exactly as it does "
              "against a board, and gets back data of the shape, dtype and scale a board returns. It does **not** "
              "prove the numbers are identical to any particular physical board: no real-board reference data "
              "is compared here.")
    setup = code("# QCSS: start the simulated ZCU216 board (tProc v1 firmware, as these demos expect)\n"
                 "import sys; sys.path.insert(0, '..')\n"
                 "import _lab, _proof\n"
                 f"lab = _lab.start(qick=True, firmware='zcu216_v1_5q', loopback={LOOPBACK.get(name, ())!r})",
                 tags=("qcss-setup",))
    finale = [md(FINALE[name]), code(FINALE_CODE[name], tags=("qcss",))] if name in FINALE else []
    proof = [md("## Does the client think it is a real board?"),
             code("_proof.qick_surface(soc, soccfg)"),
             *finale,
             md("## Teardown"),
             code("lab.stop()", tags=("qcss-setup",))]
    nb["cells"] = [head, setup, *cells, *proof]
    nb["metadata"]["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.ipynb").write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", OUT / f"{name}.ipynb")


for n in sys.argv[3:]:
    port(n)
