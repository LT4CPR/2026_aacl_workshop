# Configuration Options

`evaluation.yaml` contains the following evaluator options.

## Evaluation scope

| Option | Values | Meaning |
| --- | --- | --- |
| `evaluation_scope.sections` | `"all"`, a comma-separated string, or a list of section IDs | Selects the sections to evaluate. The release policy lists Sections 3–11. `all` evaluates every section available in each input file, including Sections 1–2 when present. Explicit selections may also include IDs such as `1` and `2`. |

## Reporting

| Option | Values | Meaning |
| --- | --- | --- |
| `reporting.aggregation.within_document` | `micro`, `macro` | `micro` pools statistics across units within a disaster. `macro` averages the unit-level scores. |
| `reporting.aggregation.across_documents` | `macro` | Averages successfully scored disasters with equal weight. Cross-document `micro` is not supported. |
| `reporting.primary_score.enabled` | `true`, `false` | Enables or disables generation of the primary score. |
| `reporting.primary_score.method` | `mean_bertscore_f1_bleurt` | Defines the primary score as `(BERTScore F1 + BLEURT) / 2`. |

## Text-level metrics

The following common options are available under
`metrics.text_level.rouge`, `metrics.text_level.bertscore`, and
`metrics.text_level.bleurt`.

| Option | Values | Meaning |
| --- | --- | --- |
| `mode` | `0`, `1`, `2`, `3` | Selects the evaluation level: `0` disables the metric, `1` evaluates the document, `2` evaluates sections, and `3` evaluates subsections. |
| `aggregation` | `micro`, `macro` | Selects pooled statistics (`micro`) or the arithmetic mean of unit scores (`macro`) as the metric's overall result. |

### ROUGE options

| Option | Values | Meaning |
| --- | --- | --- |
| `denominator_policy` | `whole_gold`, `matched_only` | For ROUGE micro aggregation, `whole_gold` uses all Gold content for recall and all System content for precision, penalizing missing and System-only units. `matched_only` uses only structurally matched units and is intended for diagnostics. |

### BERTScore options

| Option | Values | Meaning |
| --- | --- | --- |
| `model_type` | Hugging Face model name | Selects the model used by BERTScore. The default is `microsoft/deberta-xlarge-mnli`. |
| `batch_size` | Positive integer | Sets the BERTScore inference batch size. |

### BLEURT options

| Option | Values | Meaning |
| --- | --- | --- |
| `config_name` | BLEURT configuration name | Selects the BLEURT checkpoint configuration. The default is `BLEURT-20`. |

## Bullet-level metric

The following options are available under `metrics.bullet_level`.

| Option | Values | Meaning |
| --- | --- | --- |
| `mode` | `0`, `1`, `2`, `3` | Selects the alignment level: `0` disables bullet evaluation, `1` aligns across the document, `2` aligns within sections, and `3` aligns within subsections. |
| `aggregation` | `micro`, `macro` | Selects pooled bullet statistics (`micro`) or the mean of group-level scores (`macro`). |
| `on_missing_structure` | `warn`, `fail` | `warn` returns a skipped result with diagnostics. `fail` immediately stops bullet evaluation when the System hierarchy is missing. An active metric that remains unscored makes the release run incomplete in either case. |
| `similarity_metric` | `rougeL`, `bertscore`, `cosine` | Selects the text-similarity metric used to build bullet-pair edge weights. |
| `batch_size` | Positive integer | Sets the inference batch size for model-based similarity metrics. |

### Tweet-ID overlap options

These options are available under `metrics.bullet_level.tweet_id_overlap`.

| Option | Values | Meaning |
| --- | --- | --- |
| `enabled` | `true`, `false` | Enables or disables Tweet-ID Jaccard similarity in bullet-pair weights. In the release configuration, it contributes 20% of each edge weight. |
| `text_weight` | Number from `0.0` to `1.0` | Sets the text-similarity weight. With the release value `0.8`, each edge weight is `0.8 × text similarity + 0.2 × Tweet-ID Jaccard similarity`. |

### Model options

These options are available under `metrics.bullet_level.model_type`.

| Option | Values | Meaning |
| --- | --- | --- |
| `bertscore` | Hugging Face model name | Selects the model used when `similarity_metric: bertscore`. |
| `cosine` | Sentence Transformers model name | Selects the encoder used when `similarity_metric: cosine`. |

### Alignment options

These options are available under `metrics.bullet_level.alignment`.

| Option | Values | Meaning |
| --- | --- | --- |
| `method` | `bipartite` | Uses one-to-one bipartite matching. No other method is supported. |
| `algorithm` | `hungarian` | Uses the Hungarian algorithm to maximize the total accepted edge weight. No other algorithm is supported. |
| `threshold.rougeL` | Non-negative number | Sets the acceptance threshold when `similarity_metric: rougeL`. A pair must be strictly greater than the threshold. |
| `threshold.bertscore` | Non-negative number | Sets the acceptance threshold when `similarity_metric: bertscore`. A pair must be strictly greater than the threshold. |
| `threshold.cosine` | Non-negative number | Sets the acceptance threshold when `similarity_metric: cosine`. A pair must be strictly greater than the threshold. |
