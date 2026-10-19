"""Chinese ingestion/retrieval regressions; no database or model downloads."""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app.chinese import contains_han, search_terms
from app.chunking import chunk_text
from app import knowledge_bases, services
from app.security import Principal

READER = Principal(3, 2, 'reader', 'test')


@pytest.mark.parametrize('text', [
    '员工每年可以申请十五天带薪年假。',
    '員工每年可以申請十五天帶薪年假。',
    '混合 English 文本：VPN access 需要 manager approval。',
])
def test_long_unspaced_documents_keep_every_character(text):
    text *= 100
    parts = chunk_text(text, overlap=0)
    assert len(parts) > 1
    assert all(0 < len(part) <= 256 for part in parts)
    assert ''.join(parts) == text


def test_chinese_overlap_and_sentence_boundaries():
    parts = chunk_text('甲' * 20 + '。' + '乙' * 30 + '。' + '丙' * 30,
                       chunk_size=40, overlap=5)
    assert parts[0] == '甲' * 20 + '。'
    assert parts[1].startswith(parts[0][-5:])
    assert parts[-1].endswith('丙' * 30)
    assert all(len(part) <= 40 for part in parts)


def test_mixed_text_preserves_whole_english_words():
    parts = chunk_text('中文 internationalization VPN access 申请。' * 20,
                       chunk_size=40, overlap=4)
    assert sum(part.count('internationalization') for part in parts) == 20


def test_mixed_text_allows_latin_word_within_original_character_budget():
    word = 'a' * 300
    parts = chunk_text('中文 ' + word + ' 中文', overlap=0)
    assert word in parts
    assert ''.join(parts).replace(' ', '') == '中文' + word + '中文'
    with pytest.raises(ValueError, match='One word exceeds'):
        chunk_text('中文 ' + 'a' * 801)


def test_small_size_large_overlap_still_progresses():
    parts = chunk_text('甲乙丙丁戊己庚辛壬癸' * 100, chunk_size=10, overlap=9)
    assert 100 <= len(parts) < 200
    assert all(len(part) <= 10 for part in parts)


def test_lexical_terms_are_bounded_literal_and_deduplicated():
    assert search_terms('年假年假 VPN vpn？') == ['年假', '假年', 'vpn']
    assert search_terms('中！') == ['中']
    assert len(search_terms(''.join(chr(0x4e00 + i) for i in range(200)))) == 64
    assert contains_han('員工')
    assert not contains_han('annual leave')


@pytest.mark.parametrize('question', ['年假有多少天？', '年假有多少天？ VPN', "年假 % ' OR 1=1 --"])
def test_chinese_lexical_candidates_keep_acl_scope_and_citations(monkeypatch, question):
    calls, embeds, reranks = [], [], []
    vector = (11, 5, 'policy.txt', 0, '一般说明', None, .9)
    lexical = (12, 6, '年假.pdf', 7, '年假为十五天。', 3, .6)

    @contextmanager
    def database():
        class Connection:
            def execute(self, sql, params):
                calls.append((sql, params))
                rows = [lexical] if 'unnest' in sql else [vector, lexical]
                return SimpleNamespace(fetchall=lambda: rows)
        yield Connection()

    monkeypatch.setattr(services, 'db_connection', database)
    monkeypatch.setattr(services, '_audit', lambda *_a, **_kw: None)
    monkeypatch.setattr(services, 'embed_many',
                        lambda texts, **kw: embeds.append((texts, kw)) or [[.1] * 384])
    monkeypatch.setattr(knowledge_bases, 'assert_tenant_collection', lambda *_: None)

    def rerank(query, candidates):
        assert len(calls) == 2  # Inference receives only database-authorized rows.
        reranks.append(query)
        return candidates
    monkeypatch.setattr(services, '_cross_encoder_rerank', rerank)
    hits = services.search_documents(question, 2, mode='rerank', principal=READER,
                                     knowledge_base_id=9)
    assert embeds == [([question], {'query': True})]
    assert reranks == [question]
    assert hits[0].document_id == 6
    assert hits[0].page_number == 3
    assert hits[0].chunk_index == 7
    assert hits[0].similarity == .6
    for sql, params in calls:
        assert question not in sql
        assert 'd.tenant_id=%s' in sql
        assert 'document_acl' in sql
        assert 'owner_user_id=%s' in sql
        assert 'knowledge_base_documents' in sql
        assert 'kbd.tenant_id=d.tenant_id' in sql
    assert calls[1][1][1] == search_terms(question)
    assert calls[1][1][2:7] == (2, 3, 'reader', 3, 9)
    assert 'strpos' in calls[1][0]
    assert 'websearch_to_tsquery' not in calls[1][0]


def test_implicit_chinese_mode_uses_lexical_but_explicit_vector_is_respected(monkeypatch):
    calls = []
    @contextmanager
    def database():
        class Connection:
            def execute(self, sql, params):
                calls.append(sql)
                return SimpleNamespace(fetchall=lambda: [])
        yield Connection()
    monkeypatch.setenv('RAG_RETRIEVAL_MODE', 'vector')
    monkeypatch.setattr(services, 'db_connection', database)
    monkeypatch.setattr(services, '_audit', lambda *_a, **_kw: None)
    monkeypatch.setattr(services, 'embed_many', lambda *_a, **_kw: [[.1] * 384])
    services.search_documents('年假', principal=READER)
    assert len(calls) == 2
    assert 'unnest' in calls[-1]
    calls.clear()
    services.search_documents('年假', mode='vector', principal=READER)
    assert len(calls) == 1


@pytest.mark.parametrize('question', ['如何申请年假？', '如何申請年假？'])
def test_empty_chinese_sources_do_not_call_provider(monkeypatch, question):
    def unexpected(*_):
        raise AssertionError('Provider must not be called')
    monkeypatch.setattr(services, 'generate_grounded_answer', unexpected)
    assert services.answer_question(question, []) == '未找到可引用的已索引文本。'
    assert services.answer_question('Annual leave?', []) == 'No indexed sources are available to answer that question.'


def test_chinese_context_keeps_page_citations(monkeypatch):
    seen = []
    monkeypatch.setattr(services, 'generate_grounded_answer',
                        lambda q, ctx: seen.append((q, ctx)) or '十五天。[1]')
    from app.schemas import SearchHit
    hit = SearchHit(source_number=1, document_id=6, title='政策.pdf', chunk_index=7,
                    content='年假为十五天。', page_number=3, similarity=.8)
    assert services.answer_question('年假有几天？', [hit]) == '十五天。[1]'
    assert 'PDF page 3' in seen[0][1]
    assert '[1] 政策.pdf' in seen[0][1]
    assert '年假为十五天。' in seen[0][1]
