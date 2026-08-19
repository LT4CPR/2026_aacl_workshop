"""Runtime environment guards for model-based metrics."""

from __future__ import annotations

import os
import sys

SAFE_HF_ENV = {
    "TOKENIZERS_PARALLELISM": "false",
    "HF_ENABLE_PARALLEL_LOADING": "false",
    "USE_TF": "0",
}


def apply_safe_hf_env() -> None:
    """Use stable model-loading defaults for the evaluation scripts."""
    for key, value in SAFE_HF_ENV.items():
        os.environ[key] = value


def ensure_safe_hf_env_for_main(module_name: str) -> None:
    """Restart direct script execution once with safe Hugging Face settings."""
    if module_name != "__main__":
        return
    if all(os.environ.get(key) == value for key, value in SAFE_HF_ENV.items()):
        return
    env = os.environ.copy()
    env.update(SAFE_HF_ENV)
    os.execvpe(sys.executable, [sys.executable, *sys.argv], env)
