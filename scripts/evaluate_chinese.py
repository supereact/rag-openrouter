"""Synthetic multilingual retrieval smoke check; no database or LLM calls.

First use may download public model weights. This small corpus is a smoke check,
not a benchmark or proof of quality on a company's actual documents.
"""
import argparse
import json

import numpy as np

from app.embeddings import embed_many
from scripts.reembed_chunks import DEFAULT_MODEL

PASSAGES = [
    '员工每年享有十五天带薪年假。请至少提前三天向直属经理提交申请。',
    '遠端連線必須先啟用雙重驗證，再透過公司的虛擬私人網路登入。',
    'Equipment purchases above 500 dollars require finance department approval.',
    '员工离职后，信息技术团队应立即停用其账号并撤销所有会话。',
]
CASES = [
    ('simplified', '员工每年有多少天带薪年假？', 0),
    ('traditional', '如何從家裡安全地連接公司內部系統？', 1),
    ('english', 'Who approves equipment purchases costing over 500 dollars?', 2),
    ('paraphrase', '同事不再为公司工作时，应怎样处理他的登录权限？', 3),
    ('cross-script', '每年的有薪休假是多少天？', 0),
    ('cross-language', '购买六百美元的设备需要谁批准？', 2),
]


def evaluate(model_name: str, reranker_model: str | None = None) -> dict:
    passages = embed_many(PASSAGES, model_name=model_name)
    queries = embed_many([case[1] for case in CASES], query=True, model_name=model_name)
    scores = queries @ passages.T  # Normalized embeddings: cosine similarity.
    if reranker_model:
        from sentence_transformers import CrossEncoder
        reranker = CrossEncoder(reranker_model)
        # Rank the whole tiny corpus so both inference paths can be compared.
        scores = np.asarray([reranker.predict([(q, p) for p in PASSAGES],
                                              show_progress_bar=False)
                             for _, q, _ in CASES])
    results = [dict(id=case_id, passed=int(np.argmax(row)) == expected)
               for (case_id, _, expected), row in zip(CASES, scores)]
    return dict(model=model_name, reranker=reranker_model, cases=results,
                passed=sum(case['passed'] for case in results), total=len(results))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default=DEFAULT_MODEL)
    parser.add_argument('--reranker-model')
    args = parser.parse_args()
    report = evaluate(args.model, args.reranker_model)
    print(json.dumps(report))
    return 0 if report['passed'] == report['total'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
