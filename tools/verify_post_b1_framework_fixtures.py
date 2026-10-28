"""Re-measure the small post-B1 development controls with .NET Framework.

This probes only public development fixtures, never a sealed holdout. Supply a
new output directory; results from another NLS profile are saved but cannot
establish the original profile's comparison contract.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = (
    ("framework_independent_development_comparisons.json",
     "b24b6af7022fae0467e0997c34348b7b639e3027d99d98edddcbfe4e059ca104"),
    ("framework_separator_regression_controls.json",
     "3baae11d4ecfa487d9e1c2b2065315cfa19e142234d3aba9e5366c339bfc5954"),
    ("framework_inline_candidate_regressions.json",
     "2b0dd82cb2f0c26603860631123773c2faa296df027a2380d936ca739c4c48bc"),
    ("framework_decisive_jamo_development.json",
     "ef118921b4f16e9be7a38ee6b10c1b35519060ea70847d17367a8a38ea3b17c0"),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csc", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists():
        raise SystemExit("output already exists; refusing overwrite")
    if not args.csc.is_file():
        raise SystemExit("Framework compiler not found")
    records = []
    for name, expected_hash in FIXTURES:
        path = ROOT / "tests" / "fixtures" / name
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected_hash:
            raise SystemExit("fixture hash mismatch: " + name)
        data = json.loads(raw)
        for row in data["comparisons"]:
            expected = row.get("expected", row.get("CompareTo_sign"))
            if expected not in (-1, 0, 1):
                raise ValueError("invalid expected sign")
            records.append((name, row["left_utf16le_hex"], row["right_utf16le_hex"], expected))
    values = list(dict.fromkeys(value for _, left, right, _ in records for value in (left, right)))
    ids = {value: index for index, value in enumerate(values)}
    out.mkdir(parents=True, exist_ok=False)
    (out / "inputs.txt").write_text("".join(v + "\n" for v in values), encoding="ascii", newline="\n")
    (out / "pairs.tsv").write_text("".join("control\t%d\t%d\n" % (ids[l], ids[r])
                                                   for _, l, r, _ in records), encoding="ascii", newline="\n")
    (out / "arrays.json").write_text("[]\n", encoding="ascii", newline="\n")
    exe = out / "probe.exe"
    subprocess.run([str(args.csc.resolve()), "/nologo", "/optimize+", "/reference:System.Web.Extensions.dll",
                    "/out:" + str(exe), str(ROOT / "tools" / "post_b1_oracle_probe.cs")], check=True)
    subprocess.run([str(exe), str(out / "inputs.txt"), str(out / "pairs.tsv"), str(out / "arrays.json"),
                    str(out / "oracle.json")], check=True)
    result = json.loads((out / "oracle.json").read_text(encoding="utf-8-sig"))
    if result["inputs_utf16le_hex"] != values or len(result["pairs"]) != len(records):
        raise RuntimeError("probe input or row count mismatch")
    mismatches = []
    for i, ((name, left, right, expected), row) in enumerate(zip(records, result["pairs"])):
        if (row["left"], row["right"]) != (ids[left], ids[right]):
            raise RuntimeError("probe pair order mismatch")
        actual = [row[key] for key in ("CompareTo_sign", "CompareInfo_None_sign", "NLS_sign")]
        if actual != [expected] * 3:
            mismatches.append({"fixture": name, "row": i, "expected": expected, "actual": actual})
    profile_match = (result["culture"] == "ja-JP" and result["compare_options"] == "None"
                     and result["nls_version"] == 393989
                     and result["nls_sort_id"] == "00000046-57ee-1e5c-00b4-d0000bb1e11e")
    summary = {"profile_match": profile_match, "rows": len(records), "mismatches": mismatches,
               "oracle_sha256": hashlib.sha256((out / "oracle.json").read_bytes()).hexdigest()}
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary))
    return 0 if profile_match and not mismatches else 1


if __name__ == "__main__":
    raise SystemExit(main())
