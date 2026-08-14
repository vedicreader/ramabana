#!/usr/bin/env python
"""Prefetch Gemma 4 LiteRT CPU builds into the Hugging Face cache (idempotent)."""
from __future__ import annotations
import os
from pathlib import Path
from huggingface_hub import hf_hub_download, list_repo_files

MODELS = {
    'litert-community/gemma-4-E2B-it-litert-lm': 'gemma-4-E2B-it.litertlm',
    'litert-community/gemma-4-E4B-it-litert-lm': 'gemma-4-E4B-it.litertlm',
}

def main():
    for repo, fname in MODELS.items():
        files = list_repo_files(repo)
        if fname not in files:
            raise SystemExit(f'{fname} missing from {repo}: {files}')
        path = hf_hub_download(repo, fname)
        # Drop GPU siblings from the same snapshot so rishi's first()-picker cannot grab them.
        snap = Path(path).parent
        for p in snap.glob('*-gpu.litertlm'):
            try: p.unlink()
            except OSError: pass
        print(f'ok {repo} -> {path} ({Path(path).stat().st_size/1e9:.2f} GB)')

if __name__ == '__main__':
    main()
