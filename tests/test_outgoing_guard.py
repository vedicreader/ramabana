import pytest

from ramabana.core import ModelSpec


SECRET = 'sk-test' + 'abcdefghijklmnopqrstuvwxyzabcd'
EMAIL = 'ada@example.com'
LOCAL = ModelSpec('local', 'litert', 'litert-community/gemma-4-E2B-it-litert-lm')
HOSTED = ModelSpec('hosted', 'remote', 'openai/gpt-5.6')


def test_outgoing_masks_secrets_and_applies_hosted_pii_policy():
    from ramabana.guard import OutgoingRefused, outgoing

    assert SECRET not in outgoing(f'key {SECRET}', LOCAL, mode='off')
    assert EMAIL in outgoing(f'email {EMAIL}', LOCAL, mode='redact')
    redacted = outgoing(f'email {EMAIL}', HOSTED, mode='redact')
    assert redacted == 'email [EMAIL]'
    with pytest.raises(OutgoingRefused): outgoing(f'email {EMAIL}', HOSTED, mode='refuse')


def test_outgoing_validates_policy_and_never_exposes_refused_text():
    from ramabana.guard import OutgoingRefused, outgoing

    with pytest.raises(ValueError): outgoing('safe', HOSTED, mode='invalid')
    sent = outgoing(f'key {SECRET}', HOSTED, mode='refuse')
    assert SECRET not in sent and '[SECRET]' in sent


def test_outgoing_withholds_local_only_vault_references_from_hosted_models(tmp_path):
    from vishalakshi import Vault
    from ramabana.guard import OutgoingRefused, outgoing

    vault = Vault(tmp_path/'vault.db', offline=True)
    doc = vault.note('a note without detectable personal data', title='private note')
    vault.set_level(doc['doc_id'], 'local')
    with pytest.raises(OutgoingRefused): outgoing('summarise the note', HOSTED, vault=vault, refs=[doc['doc_id']])
    assert outgoing('summarise the note', LOCAL, vault=vault, refs=[doc['doc_id']]) == 'summarise the note'


def test_outgoing_honours_a_vault_floor_for_unreferenced_text(tmp_path):
    from vishalakshi import Vault
    from ramabana.guard import OutgoingRefused, outgoing

    vault = Vault(tmp_path/'vault.db', offline=True)
    vault.set_floor('local')
    with pytest.raises(OutgoingRefused): outgoing('summarise the note', HOSTED, vault=vault)
    assert outgoing('summarise the note', LOCAL, vault=vault) == 'summarise the note'


def test_outgoing_refuses_marked_personal_references_it_cannot_mask(tmp_path):
    from vishalakshi import Vault
    from ramabana.guard import OutgoingRefused, outgoing

    vault = Vault(tmp_path/'vault.db', offline=True)
    doc = vault.note('a note without detectable personal data', title='marked note')
    vault.set_level(doc['doc_id'], 'personal')
    with pytest.raises(OutgoingRefused): outgoing('summarise the note', HOSTED, mode='redact', vault=vault, refs=[doc['doc_id']])


def test_missing_pii_detector_fails_closed_for_hosted_pii_and_queries(monkeypatch):
    import ramabana.guard as guard

    monkeypatch.setattr(guard, 'pii_report', None)
    with pytest.raises(guard.OutgoingRefused, match='PII detection is unavailable'):
        guard.outgoing('safe', HOSTED, mode='redact')
    with pytest.raises(guard.OutgoingRefused, match='PII detection is unavailable'):
        guard.query('safe')


def test_outgoing_masks_a_secret_and_places_a_model_without_vishalakshi_or_rahasya(monkeypatch):
    import sys
    import ramabana.agent as agent
    import ramabana.guard as guard

    for name in ('vishalakshi', 'vishalakshi.ask'): monkeypatch.setitem(sys.modules, name, None)
    for owner, name in ((agent, 'redact'), (agent, 'pii_report'), (guard, 'pii_report')): monkeypatch.setattr(owner, name, None)
    sent = guard.outgoing(f'key {SECRET} {EMAIL}', LOCAL, mode='off')
    assert SECRET not in sent and '[SECRET]' in sent and EMAIL in sent, sent


def test_query_refuses_secrets_and_personal_data_without_network_calls():
    from ramabana.guard import OutgoingRefused, query

    with pytest.raises(OutgoingRefused): query(f'key {SECRET}')
    with pytest.raises(OutgoingRefused): query(f'contact {EMAIL}')
    assert query('ramabana guard') == 'ramabana guard'
