"""Long-input compatibility hypotheses that require new Windows observation."""
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "tests/fixtures/r44_collation_boundaries"


def inputs_and_pairs():
    inputs, groups, pairs = [], [], []

    def group(label, values):
        offset = len(inputs)
        inputs.extend(values)
        indices = list(range(offset, len(inputs)))
        groups.append({"case_id": label, "input_indices": indices})
        for left in indices:
            for right in indices:
                pairs.append((left, right))

    for count in (62, 63, 64, 8191, 8192, 8193, 16383, 16384, 16385):
        base = "a" * count
        group(f"word-elements-{count}", [base, "-" + base, base + "-",
                                         base[:count // 2] + "-" + base[count // 2:]])
    for count in (8191, 8192, 8193):
        group(f"long-symbols-{count}", ["-" * count, "'" * count,
                                       "-" * count + "a", "a" + "-" * count])
    for count in (1, 63, 2048, 2049):
        base = "\u1112\u119e\u11ab" * count
        group(f"old-jamo-clusters-{count}", [base, "-" + base, base + "-", "\u1113" * count])
    for codepoint, count in ((0xE3F8, 64), (0xE3F8, 8192), (0x3400, 4096), (0xD800, 8192)):
        base = chr(codepoint) * count
        group(f"context-elements-{codepoint:04x}-{count}", [base, "-" + base, base + "-"])
    return inputs, pairs, groups


def write_windows_plan():
    import hashlib
    inputs, pairs, groups = inputs_and_pairs()
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    hex_path = DIRECTORY / "inputs_utf16hex.txt"
    pairs_path = DIRECTORY / "pairs.tsv"
    sorts_path = DIRECTORY / "sort_orders.tsv"
    hex_path.write_text("".join(s.encode("utf-16-le", errors="surrogatepass").hex() + "\n" for s in inputs), encoding="ascii")
    pairs_path.write_text("".join(f"{left}\t{right}\n" for left, right in pairs), encoding="ascii")
    # One additional actual Framework List.Sort mixes all length/position
    # boundaries. Expected permutations are intentionally not generated here.
    sorts_path.write_text("LONG_BOUNDARIES\t" + ",".join(map(str, range(len(inputs)))) + "\n", encoding="ascii")
    manifest = {"schema": "r44-unobserved-collation-boundary-probe-1", "inputs": len(inputs),
                "pairs": len(pairs), "sorts": 1, "groups": groups,
                "expected_native_results": None, "native_execution": "UNOBSERVED",
                "known_local_condition": "The inferred 16bit positional encoding repeats every8192weight elements. This may create local leading/trailing punctuation ties; actual modern CompareTo behavior remains unobserved.",
                "immutable_prior_plan": "Originalr43 5213inputs/31991pairs plans are retained byteexact separately.",
                "files": []}
    for path in (hex_path, pairs_path, sorts_path):
        manifest["files"].append({"path": path.name, "bytes": path.stat().st_size,
                                   "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    (DIRECTORY / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
