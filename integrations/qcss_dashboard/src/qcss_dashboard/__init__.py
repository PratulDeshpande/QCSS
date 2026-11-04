"""QCSS Explorer: an operator dashboard that explains, visualizes and configures every layer of QCSS.

The bridge (this package) is the only thing the browser talks to. It holds the lab and admin tokens, calls QCSS's own
code for every number it shows, and never adds anything to the lab link: whatever a lab client could see stays exactly
as it was (indistinguishability: the lab link must not reveal it is a simulator).
"""
__version__ = "0.1.0"
