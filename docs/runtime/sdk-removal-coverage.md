# SDK removal test-retirement map

Every removed test method is listed below. SDK-only object/envelope mechanics retire with their implementation; required observable behavior remains at the named neutral boundary. No production compatibility exemption or test SDK module stub remains.

## tests/orchestrator/agent/test_client.py

### TestOrchestrationAgentUnit
SDK constructor/options/context-manager mechanics retire. Started-state, stop/interrupt/process guards and turn limits remain in tests/services/conversation_runtime/test_runtime_session.py and test_conversation_lifecycle_acceptance.py. Public selection is covered by test_conversation_agent.py.

- `test_can_instantiate`
- `test_default_options`
- `test_custom_max_turns`
- `test_custom_permission_mode`
- `test_has_lifecycle_methods`
- `test_has_context_manager`
- `test_is_started_property`
- `test_process_command_requires_start`
- `test_stop_without_start`

### TestAgentOptions
SDK MCP registration/options/wildcards retire; no raw carrier namespace is exposed. Neutral tool_catalog tests plus test_tool_workflow_acceptance.py retain mode-aware registration/dispatch; gateway configs remain tested directly.

- `test_options_has_mcp_servers`
- `test_options_has_allowed_tools`
- `test_options_has_hooks`
- `test_data_mcp_removed_from_agent`
- `test_interactive_mode_omits_data_mcp`
- `test_has_orchestrator_mcp`
- `test_has_ups_mcp`
- `test_ups_mcp_omitted_when_no_credentials`
- `test_allowed_tools_includes_wildcards`
- `test_interactive_mode_allowed_tools_omit_data_namespace`

### TestAgentHooksConfiguration
SDK PreToolUse/PostToolUse registration mechanics retire; test_policy.py and test_conversation_policy_acceptance.py prove actual denials and safe decisions.

- `test_has_pretooluse_hooks`
- `test_has_posttooluse_hooks`

### TestOrchestrationAgentIntegration
Live SDK-only lifecycle/context factory tests retire. Same lifecycle/history semantics are covered offline across all actual protocol adapters in test_conversation_lifecycle_acceptance.py; SDK-free real API/CLI startup/workflow tests replace operational dependency.

- `test_agent_lifecycle`
- `test_context_manager`
- `test_create_agent_factory`
- `test_conversation_context`
- `test_start_twice_raises_error`

### TestStartTwiceErrorContext
SDK exception/message mechanics retire. Shared session availability/start failure/rebuild behavior remains in test_conversation_lifecycle_acceptance.py.

- `test_start_twice_error_includes_context`

### TestAgentGracefulShutdown
Stop/timeout is covered by request-owned adapter cancellation in conversation_runtime/test_runtime_lifecycle.py and shared lifecycle acceptance.

- `test_stop_accepts_custom_timeout`
- `test_default_stop_timeout`

## tests/orchestrator/agent/test_client_enhanced.py

### TestSystemPromptSupport
SDK options fields retire; test_runtime_session.py and SDK-absent API/CLI probes exercise actual system messages. Shared system_prompt tests retained.

- `test_constructor_accepts_system_prompt`
- `test_constructor_default_system_prompt_is_none`
- `test_options_include_system_prompt`
- `test_options_system_prompt_none_when_not_provided`

### TestModelConfiguration
Factory/default/explicit/legacy env precedence migrated to test_conversation_agent.py; safe-boundary configuration snapshot tested in lifecycle acceptance.

- `test_constructor_accepts_model`
- `test_default_model_is_set`
- `test_options_include_model`
- `test_uses_agent_model_env_when_set`
- `test_uses_legacy_anthropic_model_env_when_agent_model_missing`

### TestPartialMessageStreaming
SDK option flag retires; actual streamed deltas/SSE asserted by test_anthropic_http_sse.py and adapter protocol tests.

- `test_options_include_partial_messages`

### TestToolsV2Integration
SDK MCP registration retires; neutral WorkflowToolCatalog registration and actual workflow dispatch acceptance retained.

- `test_options_include_v2_tools`
- `test_orchestrator_mcp_still_registered`

### TestProcessMessageStream
SDK-shaped envelopes retire. Runtime stable-ID dedup/missing ID/turn count tests, actual provider workflow acceptance and HTTP/SSE assertions retain behavior.

- `test_has_process_message_stream_method`
- `test_process_message_stream_no_history_param`
- `test_process_message_stream_accepts_user_input`
- `test_dedups_tool_call_between_stream_and_assistant_by_id`
- `test_missing_stream_event_id_emits_from_assistant_only`
- `test_tool_dedup_tracking_resets_each_assistant_turn`
- `test_records_last_turn_count_from_assistant_messages`

### TestInterruptSupport
Shared lifecycle and all-adapter opening/body cancellation tests replace client-specific method checks.

- `test_has_interrupt_method`
- `test_interrupt_without_client_is_safe`

### TestBackwardCompatibility
Removed Python SDK class is intentionally not a supported endpoint. Supported configuration compatibility is preserved in test_conversation_agent.py. Catalog/policy/gateway behavior has independent coverage.

- `test_no_args_constructor_works`
- `test_process_command_still_exists`
- `test_mcp_servers_still_configured`
- `test_hooks_still_configured`

## tests/orchestrator/agent/test_hooks.py

### TestValidateShippingInput
Generic SDK input-shape hook is obsolete: raw creation is denied regardless of shape by test_policy.py malformed-input matrix in both modes; supported preview validation remains in deterministic handler tests.

- `test_allows_partial_payload_missing_shipper`
- `test_allows_partial_payload_missing_shipto`
- `test_allows_partial_payload_missing_shipper_name`
- `test_allows_partial_payload_missing_shipper_address`
- `test_allows_partial_payload_missing_shipto_name`
- `test_allows_partial_payload_missing_shipto_address`
- `test_allows_valid_shipping_input`
- `test_allows_empty_dict`
- `test_allows_partial_shipment_request`
- `test_denies_none_tool_input`
- `test_denies_string_tool_input`
- `test_denies_list_tool_input`
- `test_allows_non_shipping_tools`
- `test_allows_data_tools`

### TestValidateVoidShipment
All direct raw void attempts denied in test_policy.py and conversation policy acceptance; SDK raw-call payload validator is obsolete.

- `test_denies_missing_tracking_number`
- `test_allows_with_tracking_number`
- `test_allows_with_shipment_id`
- `test_allows_non_void_tools`

### TestValidateDataQuery
Removed informational-only SDK data query warnings never enforced SQL authority. Neutral filter SQL/structure gates and deterministic SQL validator tests remain; no raw data MCP tool enters the catalog.

- `test_allows_query_with_where`
- `test_allows_query_without_where`
- `test_allows_non_query_tools`
- `test_warns_on_dangerous_keywords`

### TestValidatePreTool
SDK routing retires. Neutral policy tests assert raw creation/void/doc mutation denials and allowed named safe workflow tools; direct raw query tool is absent from catalog.

- `test_routes_to_shipping_validator`
- `test_routes_to_void_shipment_validator`
- `test_routes_to_data_query_validator`
- `test_allows_other_tools`

### TestLogPostTool
SDK stderr hook mechanism retires. Conversation audit service and test_conversation_privacy_acceptance.py retain structured redacted success/failure logging; test_policy.py covers None/success/error response detection.

- `test_returns_empty_dict`
- `test_handles_error_response`
- `test_handles_none_response`
- `test_handles_successful_response`

### TestDetectErrorResponse
Neutral test_policy.py covers error/isError/is_error/status/statusCode/nested lists/strings/None/success cases; no SDK hook envelope remains.

- `test_detects_error_key`
- `test_detects_is_error_flag`
- `test_detects_http_error_status`
- `test_detects_status_code_400`
- `test_handles_success_response`
- `test_handles_none_response`
- `test_handles_string_response_with_error`

### TestCreateHookMatchers
SDK matcher construction and names retire, superseded by observable policy checks and canonical local catalog tests.

- `test_returns_pretooluse_hooks`
- `test_returns_posttooluse_hooks`
- `test_pretooluse_has_create_shipment_matcher`
- `test_pretooluse_has_void_shipment_matcher`
- `test_pretooluse_no_stale_data_query_matcher`
- `test_posttooluse_applies_to_all`
- `test_pretooluse_has_fallback`
- `test_each_matcher_has_hooks`
- `test_hooks_are_callable`
- `test_accepts_interactive_shipping_parameter`
- `test_default_interactive_shipping_is_false`

### TestValidateSchedulePickup
Raw pickup names always denied by test_policy.py; trusted preview/confirm gateway cardinality covered by test_auxiliary_workflow_acceptance.py.

- `test_schedule_pickup_hook_matcher_exists`
- `test_schedule_pickup_hook_always_denies`
- `test_schedule_pickup_hook_denies_even_with_valid_input`

### TestValidateCancelPickup
Raw pickup names always denied by test_policy.py; trusted preview/confirm gateway cardinality covered by test_auxiliary_workflow_acceptance.py.

- `test_cancel_pickup_hook_matcher_exists`
- `test_cancel_pickup_hook_always_denies`

### TestValidateLocatorHooks
Raw locator names denied by test_policy.py; deterministic locator wrapper behavior retained in tool-workflow acceptance.

- `test_find_locations_hook_matcher_exists`
- `test_get_service_center_facilities_hook_matcher_exists`
- `test_find_locations_hook_always_denies`
- `test_get_service_center_facilities_hook_always_denies`

### TestValidateLandedCostHooks
Raw landed-cost names denied by test_policy.py; neutral wrapper parity retained by auxiliary/tool workflow tests.

- `test_landed_cost_hook_matcher_exists`
- `test_landed_cost_hook_always_denies`

### TestLogToStderr
SDK-specific broken-pipe stderr adapter retires; centralized redacted audit owns observability and is independently tested.

- `test_log_to_stderr_broken_pipe_routes_validation_to_warning`
- `test_log_to_stderr_broken_pipe_routes_audit_to_debug`

### TestInteractiveShippingHookEnforcement
Neutral test_policy.py covers both modes including None/string/list/empty/confirmed raw inputs; SDK HookMatcher factory checks retire.

- `test_create_shipment_denied_when_interactive_off`
- `test_create_shipment_denied_when_interactive_on`
- `test_non_dict_input_denied_when_interactive_on`
- `test_non_shipping_tools_unaffected`
- `test_empty_dict_denied_when_interactive_on`
- `test_none_input_denied_when_interactive_on`
- `test_list_input_denied_when_interactive_on`
- `test_create_hook_matchers_uses_factory`
- `test_create_hook_matchers_denies_when_interactive`

### TestFilterSpecStructuralValidation
Root/structure checks preserved by test_filter_policy_regressions.py and neutral test_policy.py.

- `test_filter_spec_without_root_denied`
- `test_filter_spec_with_root_allowed`

### TestHookExactMatching
SDK validator substring routing retires. Neutral canonical catalog never dispatches unknown or raw namespace tools; test_policy.py covers raw/future carrier denial and policy acceptance verifies zero gateway effects.

- `test_substring_tool_name_not_matched`
- `test_exact_tool_name_still_denied`
- `test_validate_pre_tool_exact_routing`
- `test_validate_pre_tool_void_exact_routing`

### TestSimplifiedFilterSpecHook
Filter structure/all_rows/reuse/unrelated-tool assertions migrated to test_filter_policy_regressions.py; bridge parameter and matcher list-shape assertions retire.

- `test_filter_spec_with_root_allowed`
- `test_filter_spec_without_root_denied`
- `test_all_rows_allowed`
- `test_no_filter_spec_allowed`
- `test_refinement_reuse_allowed`
- `test_non_pipeline_tool_ignored`
- `test_create_hook_matchers_accepts_bridge_param`
- `test_create_hook_matchers_without_bridge`

### TestClaudeHookProjectionOfNeutralDecisions
Removed vendor envelope conversion has no remaining consumer. Allowed/denied code/reason contract tested by test_policy.py and test_policy_decision_boundary.py.

- `test_denied_decision_projects_to_pre_tool_use_envelope`
- `test_allowed_decision_projects_to_empty_dict`
- `test_raw_sql_hook_denial_matches_neutral_engine_code`

### module-level
Raw document mutation denial is retained and broadened in test_policy.py across both modes, malformed arguments and claimed confirmation.

- `test_legacy_generic_hook_blocks_raw_document_mutations`

## tests/orchestrator/agent/test_filter_hooks.py

### TestDenyRawSqlInFilterTools
Migrated one-for-one to test_filter_policy_regressions.py with neutral PolicyDecision assertions; detailed root text becomes safe stable denial code. No permission/token semantics changed.

- `test_denies_where_clause_in_pipeline`
- `test_denies_sql_key_in_fetch_rows`
- `test_denies_top_level_query_key`
- `test_denies_deeply_nested_where_clause`
- `test_denies_sql_in_list_of_dicts`
- `test_allows_filter_spec`
- `test_ignores_unrelated_tools`

### TestValidateIntentOnResolve
Migrated one-for-one to test_filter_policy_regressions.py with neutral PolicyDecision assertions; detailed root text becomes safe stable denial code. No permission/token semantics changed.

- `test_denies_invalid_operator`
- `test_allows_valid_intent`

### TestValidateFilterSpecOnPipeline
Migrated one-for-one to test_filter_policy_regressions.py with neutral PolicyDecision assertions; detailed root text becomes safe stable denial code. No permission/token semantics changed.

- `test_allows_filter_spec_with_root`
- `test_allows_resolved_spec_without_token`
- `test_denies_filter_spec_without_root`
- `test_allows_repeated_calls_same_spec`
- `test_ignores_unrelated_tools`
- `test_allows_all_rows`
- `test_allows_no_filter_spec`

## tests/orchestrator/agent/test_config.py

### TestCreateMCPServersConfig
Unused SDK aggregate map assembly removed. Individual get_data_mcp_config/get_ups_mcp_config/get_external_sources_mcp_config and credential/gateway ownership tests remain in test_config.py/test_ups_call_site_integration.py.

- `test_returns_dict_with_data_and_external`
- `test_includes_ups_when_credentials_available`
- `test_omits_ups_when_no_credentials`
- `test_data_config_is_valid`
- `test_external_config_is_valid`
- `test_data_uses_preferred_python`
- `test_external_uses_preferred_python`
- `test_ups_uses_preferred_python`
- `test_ups_config_is_valid`
- `test_returns_new_dict_each_call`

## tests/services/test_ups_call_site_integration.py

### TestCreateMcpServersConfig
Unused SDK aggregate map assembly removed. Credential-present/absent behavior remains asserted directly by TestGetUpsMcpConfig and TestGatewayProviderBuild in the same file.

- `test_ups_key_omitted_when_no_creds`
- `test_ups_key_present_with_creds`

## Renamed or inverted cutover assertions

- `test_interactive_on_denies_create_shipment_via_hook` → `test_interactive_on_denies_create_shipment_via_policy`: same denial and preview-direction assertion via the shared policy
- `test_hook_denies_create_shipment_in_interactive_mode` → `test_policy_denies_create_shipment_in_interactive_mode`: same safety assertion via the shared policy
- `test_claude_runtime_fails_closed_when_optional_sdk_unavailable` → `test_claude_runtime_requires_anthropic_key`: removed SDK installation is no longer an error; missing provider credentials still fail closed
- `test_legacy_claude_selectors_never_select_the_messages_adapter` → `test_legacy_claude_selectors_use_shared_messages_adapter`: deliberately reversed for the cutover; aliases never enable the SDK
- `test_active_non_compat_source_does_not_import_claude_agent_sdk_after_runtime_split` → `test_all_production_source_is_sdk_free_without_exemptions`: removes both production-file exemptions and asserts wrappers absent
- `test_required_install_includes_claude_agent_sdk` → `test_required_install_excludes_claude_agent_sdk`: intentionally reversed and extended to the generated lockfile
