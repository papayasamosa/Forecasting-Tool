import json

d = json.load(open(r"D:\Forecasting-Tool-Local\temp\evidence-benchmark\benchmark_20260729_125106.json"))
print("Suite passed:", d["suite_passed"])
print("Initial cache:", d.get("initial_cache_state", ""))
print("Commit:", d.get("code_commit", "")[:12])
print("Schema ver:", d.get("evidence_schema_version", ""))
print("Scenarios:", len(d["scenarios"]))
for s in d["scenarios"]:
    print(f'  {s["scenario"]}: PASS={s["scenario_passed"]} samples={len(s["samples"])}')
    for sm in s["samples"]:
        print(f'    {sm["label"]}: cache_state={sm.get("cache_state","")} success={sm["success"]}')
