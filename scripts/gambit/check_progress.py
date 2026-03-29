"""Check calibration progress."""
import json, os, glob

corr_path = r"c:\Users\jiaqizou\SurfaceLaptopRobot\data\learned_corrections.json"
if os.path.exists(corr_path):
    with open(corr_path) as f:
        c = json.load(f)
    print(f"Learned corrections: {len(c)} keys")
    for k in sorted(c):
        v = c[k]
        a = v.get("attempts_needed", "?")
        dx = v.get("dx", 0)
        dy = v.get("dy", 0)
        print(f"  {k:5s}  dx={dx:+6.1f}  dy={dy:+6.1f}  attempts={a}")
else:
    print("No learned corrections file")

result_dirs = glob.glob(r"c:\Users\jiaqizou\SurfaceLaptopRobot\temp\calibration_*")
if result_dirs:
    latest = sorted(result_dirs)[-1]
    rpath = os.path.join(latest, "results.json")
    if os.path.exists(rpath):
        with open(rpath) as f:
            res = json.load(f)
        passed = sum(1 for r in res.values() if r.get("status") == "PASS")
        failed = sum(1 for r in res.values() if r.get("status") != "PASS")
        print(f"\nResults from {os.path.basename(latest)}: {passed} PASS / {failed} FAIL / {len(res)} total")
        for k in sorted(res):
            r = res[k]
            print(f"  {k:5s}  {r['status']:10s}  attempts={r['total_attempts']}")
