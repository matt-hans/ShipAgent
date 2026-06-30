class RedisTtl:
    RELAY_SESSION_SECONDS = 90
    REPLAY_NONCE_SECONDS = 300
    INVOCATION_SECONDS = 300
    PROVIDER_POLL_SECONDS = 86400
    TERMINAL_JOB_SECONDS = 86400
    RATE_LIMIT_SECONDS = 60


class RedisKey:
    @staticmethod
    def relay_device(account_id: str, device_id: str) -> str:
        return f"sa:relay:device:{account_id}:{device_id}"

    @staticmethod
    def relay_challenge(relay_session_id: str) -> str:
        return f"sa:relay:challenge:{relay_session_id}"

    @staticmethod
    def relay_session(device_id: str) -> str:
        return f"sa:relay:session:{device_id}"

    @staticmethod
    def relay_heartbeat(device_id: str) -> str:
        return f"sa:relay:heartbeat:{device_id}"

    @staticmethod
    def replay_nonce(device_id: str, nonce: str) -> str:
        return f"sa:relay:nonce:{device_id}:{nonce}"

    @staticmethod
    def invocation(correlation_id: str) -> str:
        return f"sa:invocation:{correlation_id}"

    @staticmethod
    def provider_poll(connection_id: str, reference: str) -> str:
        return f"sa:poll:{connection_id}:{reference}"

    @staticmethod
    def rate_limit(connection_id: str, rate_limit_class: str, minute_bucket: str) -> str:
        return f"sa:rate:{connection_id}:{rate_limit_class}:{minute_bucket}"

    @staticmethod
    def loop_guard(connection_id: str, tool_name: str, arguments_hash: str) -> str:
        return f"sa:loop:{connection_id}:{tool_name}:{arguments_hash}"
