# Source Modules

For evaluation with the final release layout, use `run_eval.py` as the only
supported public command-line entry point. The other modules provide import-only
supporting logic.

| File | Role |
| --- | --- |
| `run_eval.py` | Main CLI. Pairs `<crisis>/<cell>.report.json` files, evaluates each test instance, aggregates replicates within windows and windows within equally weighted crisis/documents, and writes crisis-nested per-instance results plus one root combined result. |
| `eval_pair.py` | Coordinates text-level and bullet-level evaluation for one gold/system file pair. |
| `eval_sitrep.py` | Extracts text units, records unmatched units as diagnostics, and computes ROUGE, BERTScore, and BLEURT over structurally matched units. With ROUGE's `whole_gold` policy, unmatched Gold content is also included in the micro recall denominator. |
| `eval_weighted_alignment.py` | Builds bullet similarity scores, combines text and Tweet-ID similarity, runs alignment, and computes soft precision, recall, and F1. |
| `hungarian_alignment.py` | Performs thresholded maximum-weight one-to-one Hungarian matching and returns matched and unmatched units. |
| `sitrep_units.py` | Validates SITREP JSON and extracts scorable units by document, section, or subsection. |
| `subsection_alignment.py` | Validates the global subsection-alignment method and builds dynamic ID/header alignment keys. |
| `evaluation_scope.py` | Resolves configured or CLI-selected section IDs, including the `all` scope for every available section. |
| `reporting_config.py` | Loads and validates within-instance aggregation, hierarchical cross-document aggregation, and primary-score settings. |
| `runtime_env.py` | Sets safe Hugging Face and TensorFlow runtime environment options before model libraries are loaded. |
