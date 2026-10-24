"""Build model-only artifacts without database or provider access.

Run in the deployment build, with the same model IDs as API and worker. Output
must be new: this command never overwrites an existing directory.
"""
import argparse
from functools import partial
import json
import os
from pathlib import Path
import re


def prepare(output: Path, *, offline: bool = False, require_cpu: bool = False,
            require_revisions: bool = False) -> dict:
    if output.exists():
        raise ValueError('Model bundle output already exists; use a new build directory')
    if os.getenv('RAG_MODEL_BUNDLE'):
        raise ValueError('Build from original model IDs, not a previous bundle')
    if offline:
        os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    # Imports happen after offline/cache flags have been selected. Settings read
    # only configuration; this command never imports services or connects to DB.
    from app.settings import EMBEDDING_MODEL, RERANKER_MODEL
    from app.model_loading import load_cached_model
    from sentence_transformers import SentenceTransformer, CrossEncoder
    import torch
    if require_cpu and torch.version.cuda is not None:
        raise ValueError('Install the CPU-only PyTorch build before packaging')
    mode = os.getenv('RAG_RETRIEVAL_MODE', 'vector').strip().lower()
    if mode not in ('vector', 'hybrid', 'rerank'):
        raise ValueError('Invalid retrieval mode')
    if mode == 'rerank' and EMBEDDING_MODEL == RERANKER_MODEL:
        raise ValueError('Embedding and reranker must be distinct model types')
    models = {}
    revisions = {}
    selections = [(EMBEDDING_MODEL, 'embedding', SentenceTransformer, os.getenv('RAG_EMBEDDING_REVISION', ''))]
    if mode == 'rerank':
        selections.append((RERANKER_MODEL, 'reranker', CrossEncoder, os.getenv('RAG_RERANKER_REVISION', '')))
    for _, _, _, revision in selections:
        if (revision or require_revisions) and not re.fullmatch(r'[0-9a-f]{40}', revision):
            raise ValueError('Pin selected models to full Hugging Face commit revisions')
    output.mkdir(parents=True)
    for name, directory, factory, revision in selections:
        options = {'revision': revision} if revision else {}
        model = load_cached_model(partial(factory, device='cpu', **options), name)
        if directory == 'embedding':
            dimension = getattr(model, 'get_embedding_dimension', None) or model.get_sentence_embedding_dimension
            if dimension() != 384:
                raise ValueError('The application requires 384-dimensional embeddings')
        model.save(str(output / directory), safe_serialization=True, create_model_card=False)
        models[name] = directory
        if revision:
            revisions[name] = revision
        del model
    manifest = {'version': 1, 'retrieval_mode': mode, 'models': models, 'revisions': revisions}
    # Written last: interrupted builds cannot look complete to a runtime.
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    size = sum(path.stat().st_size for path in output.rglob('*') if path.is_file())
    print(f'PASS: {len(models)} selected models packaged ({size / 1024**2:.1f} MiB); no database/provider calls')
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('model_bundle'))
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--require-cpu', action='store_true')
    parser.add_argument('--require-revisions', action='store_true')
    args = parser.parse_args()
    try:
        prepare(args.output, offline=args.offline, require_cpu=args.require_cpu,
                require_revisions=args.require_revisions)
        return 0
    except Exception as exc:
        print(f'FAIL: model packaging ({type(exc).__name__}); inspect build configuration privately')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
