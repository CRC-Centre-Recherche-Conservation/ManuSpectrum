"""Synthetic instrument files built by the tests; no lab file is involved."""


def elio_mca(
    counts,
    *,
    calibration=((722, "8,046"), (1926, "22,163")),
    crlf=False,
    title="synthetic example",
):
    """Elio-style text export with invented header values."""
    lines = [
        f"# {title}",
        "# 11/05/2031 09:41:07",
        "# SN000",
        "# Fluorescence beam: 12,5",
        "# Incident beam angle: 45",
        "# Sample to detector distance: 2,5",
        "# Tube Anode:  Ag",
        "# Tube Voltage: 35",
        "# Tube Current: 150",
        "# Measurement time: 120000",
        "# Live time: 118,5",
        "# Deadtime: 1,25",
        f"# MCA Channels: {len(counts)}",
        f"# Calibration1: {calibration[0][0]} {calibration[0][1]}",
        f"# Calibration2: {calibration[1][0]} {calibration[1][1]}",
        "# Calibration3: 0 0",
        "#",
    ]
    lines += [f"{count:.8E}" for count in counts]
    eol = "\r\n" if crlf else "\n"
    return (eol.join(lines) + eol).encode("ascii")
