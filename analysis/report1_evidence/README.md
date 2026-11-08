# Report #1 software evidence

Reproduce these artifacts from an activated Python 3.11 environment inside `analysis/`:

```bash
python run_report1.py
```

The [acceptance summary](acceptance_summary.json) records full configurations, seed **9500**, Python **3.11.6**, package versions, transformations, groups, coverage diagnostics, metrics, and input-order determinism checks. All six scenarios produced valid partitions and the same results after observations and device manifests were reordered.

The full automated suite passed **207 tests** with `python -m pytest -q`. Its 14 Matplotlib/pyparsing deprecation warnings did not cause test failures. The complete `python run_report1.py` workflow also completed successfully.

| Synthetic scenario | Devices | Graph pairwise F1 | Pearson pairwise F1 | Graph count error |
|---|---:|---:|---:|---:|
| Default two pairs | 4 | 1.000 | 1.000 | 0 |
| Three pairs, arbitrary identifiers | 6 | 1.000 | 1.000 | 0 |
| Two pairs plus singleton | 5 | 1.000 | 1.000 | 0 |
| Two triples, `K=3` | 6 | 1.000 | 0.500 | 0 |
| Incomplete and uneven coverage | 5 | 0.667 | 0.667 | 1 |
| Prespecified 12 dB noise control | 4 | 1.000 | 1.000 | 0 |

The graph matches the Pearson baseline on every pair-capacity scenario. In the triples case the graph can form groups of three while the specified Pearson mutual-top-1 baseline can form only pairs, so that difference does not isolate graph inference quality. The 12 dB noise control **did not reduce accuracy at this seed**. It remains unchanged and is reported honestly. The incomplete-data case loses one true pair because an under-covered device correctly falls back to a singleton; the zero-sample manifest device also remains present.

`synth001/` contains the default configuration, predicted groups and metrics, similarity CSV, and RSSI/state/similarity figures. The default result recovers `{M1,D1}` and `{M2,D2}`; these identifiers belong to the fixture, not algorithm branches. Full packet-level generated data remains in ignored `data/processed/`.

`wisniff/` contains only an aggregate summary and RSSI histogram of the existing ambient scan: **40 records**, **18 source-MAC strings**, RSSI **−93 to −33 dBm**. It has no pose, synchronized time, or ownership labels. It cannot validate grouping or person counts, and the evidence does not reproduce raw MACs.

The separate `capture001` workflow uses an **invented one-transmitter** serial/event fixture: **9** stationary samples are accepted, **6** samples outside capture windows are excluded, and inference returns a singleton. Its quality report lives in ignored `data/processed/capture001/`. It demonstrates `[start,end)` joining and diagnostics, not real hardware or multi-device colocation.

Synthetic results test software behavior under the documented toy model. Real RF colocation remains unvalidated by these artifacts. Firmware, event emission, LED cues, and serial-logger changes are deferred. For eventual real inputs, samples and events must come from the same ESP32 recording; overlapping integer uptimes alone cannot independently prove that provenance.
