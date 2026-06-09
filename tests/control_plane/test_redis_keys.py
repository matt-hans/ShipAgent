from src.control_plane.redis_keys import RedisKey, RedisTtl


def test_keys_are_namespaced_and_contain_no_payload_data():
    assert RedisKey.relay_session("device-1") == "sa:relay:session:device-1"
    assert RedisKey.invocation("corr-1") == "sa:invocation:corr-1"
    assert RedisTtl.RELAY_SESSION_SECONDS == 90
    assert RedisTtl.TERMINAL_JOB_SECONDS == 86400
