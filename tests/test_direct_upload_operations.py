from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from botocore.exceptions import ClientError
import pytest

from app import object_storage as storage
from scripts import cleanup_direct_uploads as cleanup, configure_upload_cors as cors


@pytest.fixture
def remote(monkeypatch):
    monkeypatch.setattr(storage.settings, 'RAG_STORAGE_BACKEND', 's3')
    fake = Mock()
    monkeypatch.setattr(storage, 'client', lambda: fake)
    return fake


def test_cors_preview_preserves_other_rules_and_apply_keeps_exact_origins(remote):
    other = {'ID':'OtherRule','AllowedOrigins':['https://other.example'],'AllowedMethods':['GET']}
    remote.get_bucket_cors.return_value = {'CORSRules':[other]}
    cors.configure(['https://app.example'])
    remote.put_bucket_cors.assert_not_called()
    remote.put_bucket_cors.side_effect = lambda **kw: setattr(remote.get_bucket_cors, 'return_value', kw['CORSConfiguration'])
    cors.configure(['https://app.example'],apply=True)
    rules = remote.put_bucket_cors.call_args.kwargs['CORSConfiguration']['CORSRules']
    assert rules[0] == other
    assert rules[1]['AllowedOrigins'] == ['https://app.example']
    assert rules[1]['AllowedMethods'] == ['POST']
    assert 'ACL' not in remote.put_bucket_cors.call_args.kwargs


@pytest.mark.parametrize('origin', ['*','https://*.example.com','https://app.example/path',
    'https://user:secret@app.example','http://app.example'])
def test_unsafe_cors_origins_never_update_storage(remote, origin):
    with pytest.raises(ValueError):
        cors.configure([origin],apply=True)
    remote.put_bucket_cors.assert_not_called()


def test_cors_can_initialize_an_unconfigured_bucket(remote):
    rule = {'ID':cors.RULE_ID,'AllowedOrigins':['http://127.0.0.1:5173'], 'AllowedMethods':['POST'],
            'AllowedHeaders':['content-type'],'ExposeHeaders':['ETag'],'MaxAgeSeconds':300}
    remote.get_bucket_cors.side_effect = [ClientError({'Error':{'Code':'NoSuchCORSConfiguration'}},'GetBucketCors'), {'CORSRules':[rule]}]
    cors.configure(['http://127.0.0.1:5173'],apply=True)
    assert remote.put_bucket_cors.called


def test_cors_never_reports_success_when_provider_does_not_persist_rule(remote):
    remote.get_bucket_cors.return_value = {'CORSRules':[]}
    with pytest.raises(storage.StorageUnavailable, match='did not persist'):
        cors.configure(['https://app.example'],apply=True)


def test_cleanup_is_dry_run_by_default_and_never_deletes_frozen_or_recent_objects(remote):
    now = datetime.now(timezone.utc)
    expired = 'incoming/'+'1'*32+'.upload'
    remote.list_objects_v2.return_value = {'Contents':[
        {'Key':expired,'LastModified':now-timedelta(days=2)},
        {'Key':'incoming/'+'2'*32+'.upload','LastModified':now},
        {'Key':'staged/'+'3'*32+'.upload','LastModified':now-timedelta(days=2)},
        {'Key':'incoming/unrelated-file','LastModified':now-timedelta(days=2)},
    ]}
    assert cleanup.cleanup() == {'expired':1,'deleted':0}
    remote.delete_object.assert_not_called()
    assert cleanup.cleanup(apply=True) == {'expired':1,'deleted':1}
    assert remote.delete_object.call_args.kwargs['Key'] == expired
    with pytest.raises(ValueError):
        cleanup.cleanup(older_than_hours=0,apply=True)
