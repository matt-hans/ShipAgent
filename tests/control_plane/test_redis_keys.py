from src.control_plane.redis_keys import RedisKey, RedisTtl


def test_keys_are_namespaced_and_contain_no_payload_data():
    assert RedisKey.relay_device("acct-1", "device-1") == "sa:relay:device:acct-1:device-1"
    assert RedisKey.relay_session("device-1") == "sa:relay:session:device-1"
    assert RedisKey.relay_heartbeat("device-1") == "sa:relay:heartbeat:device-1"
    assert RedisKey.invocation("corr-1") == "sa:invocation:corr-1"
    assert RedisKey.rate_limit("pc-1", "estimate", "1234") == "sa:rate:pc-1:estimate:1234"
    assert RedisKey.loop_guard("pc-1", "get_job_status", "hash-1") == "sa:loop:pc-1:get_job_status:hash-1"
    assert RedisTtl.RELAY_SESSION_SECONDS == 90
    assert RedisTtl.TERMINAL_JOB_SECONDS == 86400
