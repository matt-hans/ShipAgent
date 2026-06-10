class RedisTtl:
    RELAY_SESSION_SECONDS = 90
    REPLAY_NONCE_SECONDS = 300
    INVOCATION_SECONDS = 300
    PROVIDER_POLL_SECONDS = 86400
    TERMINAL_JOB_SECONDS = 86400
    RATE_LIMIT_SECONDS = 60


class RedisKey:
    @staticmethod
    def relay_session(device_id: str) -> str:
        return f"sa:relay:session:{device_id}"

    @staticmethod
    def replay_nonce(device_id: str, nonce: str) -> str:
        return f"sa:relay:nonce:{device_id}:{nonce}"

    @staticmethod
    def invocation(correlation_id: str) -> str:
        return f"sa:invocation:{correlation_id}"

    @staticmethod
    def provider_poll(connection_id: str, reference: str) -> str:
        return f"sa:poll:{connection_id}:{reference}"
