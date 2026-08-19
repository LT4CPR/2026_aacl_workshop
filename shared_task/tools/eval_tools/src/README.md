# Source Modules

For the final release, run `run_eval.py`. The other modules are imported by the evaluator.

| File | Role |
| --- | --- |
| `run_eval.py` | Main CLI. Finds gold/system pairs, evaluates each disaster, and writes per-disaster and combined results. |
| `eval_pair.py` | Coordinates text-level and bullet-level evaluation for one gold/system file pair. |
| `eval_sitrep.py` | Extracts text units and computes ROUGE, BERTScore, and BLEURT, including zero scores for unmatched units. |
| `eval_weighted_alignment.py` | Builds bullet similarity scores, combines text and Tweet-ID similarity, runs alignment, and computes soft precision, recall, and F1. |
| `hungarian_alignment.py` | Performs thresholded maximum-weight one-to-one Hungarian matching and returns matched and unmatched units. |
| `sitrep_units.py` | Validates SITREP JSON and extracts scorable units by document, section, or subsection. |
| `evaluation_scope.py` | Resolves configured or CLI-selected section IDs, including the `all` scope for every available section. |
| `reporting_config.py` | Loads and validates within-disaster aggregation, across-disaster aggregation, and primary-score settings. |
| `runtime_env.py` | Sets safe Hugging Face and TensorFlow runtime environment options before model libraries are loaded. |
