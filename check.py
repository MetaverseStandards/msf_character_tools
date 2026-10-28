# SPDX-License-Identifier: MIT
"""Thin convenience wrapper; the package owns validation and byte checking."""
from msf_character_tools.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["check", "examples/authoring", "--pack", "examples/generated/pack.json",
                           "--csv", "examples/generated/survey.csv"]))
