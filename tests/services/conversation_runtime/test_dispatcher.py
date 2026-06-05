import json
import logging

import pytest

from src.services.conversation_runtime.dispatcher import LocalToolDispatcher
from src.services.conversation_runtime.models import ProviderToolCall
from src.services.conversation_runtime.policy import RuntimePolicyEngine


class FakeTool:
    name = "fetch_rows"
    allow_parallel = False

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": '{"fetch_id":"fetch-1","total_count":2,"returned_count":2,"sample_rows":[{"name":"Jane","address":"1 Main"}],"rows":[{"name":"Jane","address":"1 Main"}]}',
                }
            ],
        }


class SuccessfulRowsWithErrorFieldsTool:
    name = "fetch_rows"
    allow_parallel = False

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "fetch_id": "fetch-1",
                            "total_count": 2,
                            "returned_count": 2,
                            "rows": [
                                {
                                    "status": "error",
                                    "error": "customer note",
                                    "name": "Jane",
                                },
                                {
                                    "status": "ready",
                                    "error": "",
                                    "address": "1 Main",
                                },
                            ],
                        }
                    ),
                }
            ],
        }


class EventObservedTool(FakeTool):
    def __init__(self, events):
        self.events = events
        self.saw_tool_call_before_handler = False

    async def handler(self, args):
        self.saw_tool_call_before_handler = (
            len(self.events) == 1
            and self.events[0][0] == "tool_call"
            and self.events[0][1]["tool_name"] == self.name
            and self.events[0][1]["tool_input"] == args
        )
        return await super().handler(args)


class MixedListTool:
    name = "mixed_payload"
    allow_parallel = False

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": '{"items":["kept",{"name":"Jane","address":"1 Main","safe_id":"safe-1"}]}',
                }
            ],
        }


class UnsafeKeyVariantTool:
    name = "variant_payload"
    allow_parallel = False

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": '{"safe_id":"safe-1","labelUrl":"https://labels.example/one","labelURLs":["https://labels.example/two"],"labelDownloadUrl":"https://labels.example/download","documentUrl":"https://documents.example/one","document_url":"https://documents.example/two","documentDownloadUrl":"https://documents.example/download-one","document_download_url":"https://documents.example/download-two","requestBody":{"address":"1 Main"},"responseBody":{"name":"Jane"},"documentBytes":"binary-label","fileContentBase64":"encoded-document","sampleRows":[{"address":"2 Main"}],"previewRows":[{"address":"3 Main"}],"rawRows":[{"address":"4 Main"}],"raw_rows":[{"address":"5 Main"}],"sample":{"address":"6 Main"},"samples":[{"address":"7 Main"}],"labelData":"label-binary-data","label_data":"label-binary-data-two","rawResponse":{"token":"raw"}}',
                }
            ],
        }


class CompoundUnsafeKeyTool:
    name = "compound_payload"
    allow_parallel = False

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": '{"shippingLabelUrls":["https://labels.example/leak"],"paperlessDocumentUrls":["https://documents.example/leak"],"rawResponseBody":{"address":"1 Main"},"requestPayload":{"safe_id":"safe-1","address":"5 Main"},"responsePayload":{"job_id":"job-1","phone":"555"},"rawPayload":{"fetch_id":"fetch-1","email":"jane@example.com"},"shipmentSampleRows":[{"name":"Jane","address":"2 Main"}],"shipmentRawRows":[{"address":"3 Main"}],"shipmentPreviewRows":[{"address":"4 Main"}],"fetch_id":"fetch-1"}',
                }
            ],
        }


class UnsafeContainerKeyTool:
    name = "unsafe_container_payload"
    allow_parallel = False

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": '{"customerData":{"fetch_id":"fetch-2"},"orderData":{"job_id":"job-2"},"contactData":{"safe_id":"safe-2"},"addressData":{"status":"ready"},"phoneData":{"action":"created"},"emailData":{"success":true},"nameData":{"total_count":1},"fetch_id":"fetch-1"}',
                }
            ],
        }


class SecretContainerKeyTool:
    name = "container_probe"
    allow_parallel = False

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": '{"secret":{"job_id":"job-1"},"secrets":{"fetch_id":"fetch-2"},"apiSecret":{"safe_id":"safe-2"},"carrierSecretData":{"status":"ready"},"fetch_id":"fetch-1"}',
                }
            ],
        }


class WrapperContainerKeyTool:
    name = "wrapper_probe"
    allow_parallel = False

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": '{"carrierRequest":{"job_id":"job-1"},"carrierResponse":{"fetch_id":"fetch-2"},"raw":{"safe_id":"safe-2"},"payload":{"status":"ready"},"apiPayload":{"action":"created"},"fetch_id":"fetch-1"}',
                }
            ],
        }


class NestedKeyDataTool:
    name = "nested_key_probe"
    allow_parallel = False

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": '{"summary":{"Jane Doe":{"count":1},"jane@example.com":{"count":1},"742 Main St":{"count":1},"BobWilson":{"count":1}},"fetch_id":"fetch-1"}',
                }
            ],
        }


class SchemaMetadataTool:
    name = "get_schema"
    allow_parallel = True

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "columns": [
                                {
                                    "name": "Ship To Name",
                                    "type": "string",
                                    "nullable": False,
                                    "sample_values": ["Jane"],
                                    "values": ["Jane"],
                                    "rows": [{"name": "Jane"}],
                                },
                                {
                                    "field": "weight_oz",
                                    "data_type": "number",
                                    "null_count": 0,
                                    "non_null_count": 2,
                                    "sample": "16",
                                },
                            ],
                            "column_count": 2,
                            "sample_rows": [{"address": "1 Main"}],
                            "raw_values": ["Jane"],
                        },
                    ),
                }
            ],
        }


class SourceInfoTool:
    name = "get_source_info"
    allow_parallel = True

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "source_type": "csv",
                            "row_count": 25,
                            "column_count": 2,
                            "columns": [
                                {"name": "Order ID", "type": "string"},
                                {"name": "Ship To Address 1", "type": "string"},
                            ],
                            "source_name": "Jane Orders",
                            "sample_rows": [{"name": "Jane", "address": "1 Main"}],
                            "values": ["Jane", "1 Main"],
                        },
                    ),
                }
            ],
        }


class UnsafeSourceTypeTool:
    name = "get_source_info"
    allow_parallel = True

    def __init__(self, source_type):
        self.source_type = source_type

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "source_type": self.source_type,
                            "row_count": 25,
                            "column_count": 2,
                        },
                    ),
                }
            ],
        }


class LeakySchemaTextTool:
    name = "get_schema"
    allow_parallel = True

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "columns": [
                                {"name": "Jane Doe", "type": "string"},
                                {"name": "1 Main", "type": "string"},
                                {"field": "5551234567", "type": "string"},
                                {"name": "jane doe", "type": "string"},
                                {"name": "Jane Doe-Smith", "type": "string"},
                                {"field": "742 Main St", "type": "string"},
                                {"column": "Bob Wilson", "data_type": "string"},
                                {"name": "jane@example.com", "type": "string"},
                                {"name": "https://labels.example/leak", "type": "string"},
                                {"name": "reference_id", "type": "1 Main"},
                                {"name": "tracking_id", "type": "string"},
                            ],
                            "column_count": 6,
                        },
                    ),
                }
            ],
        }


class LeakySchemaTypeTool:
    name = "get_schema"
    allow_parallel = True

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "columns": [
                                {
                                    "name": "reference_id",
                                    "type": "Jane Doe",
                                    "data_type": "Bob Wilson",
                                }
                            ],
                            "column_count": 1,
                        },
                    ),
                }
            ],
        }


class ObfuscatedSchemaTypeTokenTool:
    name = "get_schema"
    allow_parallel = True

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "columns": [
                                {
                                    "name": "tracking_id",
                                    "type": "s/t/r/i/n/g",
                                    "data_type": "n u m b e r",
                                },
                                {
                                    "name": "status",
                                    "type": "String",
                                    "data_type": "NUMBER",
                                },
                                {"name": "reference_id", "type": "string"},
                            ],
                            "column_count": 3,
                        },
                    ),
                }
            ],
        }


class LeakySchemaUrlTextTool:
    name = "get_schema"
    allow_parallel = True

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "columns": [
                                {"name": "labels.example/leak", "type": "string"},
                                {"field": "www.example.com", "type": "string"},
                                {
                                    "name": "documents.example/file.pdf",
                                    "type": "string",
                                },
                                {"name": "tracking_id", "type": "string"},
                            ],
                            "column_count": 4,
                        },
                    ),
                }
            ],
        }


class LeakyCompactSchemaIdentifierTool:
    name = "get_schema"
    allow_parallel = True

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "columns": [
                                {"name": "742MainSt", "type": "string"},
                                {"name": "JaneDoe", "type": "string"},
                                {"field": "Jane_Doe", "type": "string"},
                                {"field": "BobWilson", "type": "string"},
                                {"name": "tracking_id", "type": "string"},
                            ],
                            "column_count": 5,
                        },
                    ),
                }
            ],
        }


class LeakyTechnicalFragmentSchemaIdentifierTool:
    name = "get_schema"
    allow_parallel = True

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "columns": [
                                {"name": "JaneDoeName", "type": "string"},
                                {"field": "BobWilsonId", "type": "string"},
                                {"name": "742Address", "type": "string"},
                                {"name": "customer_id", "type": "string"},
                                {"name": "address_line_1", "type": "string"},
                                {"name": "ship_to_name", "type": "string"},
                                {"name": "tracking_id", "type": "string"},
                            ],
                            "column_count": 7,
                        },
                    ),
                }
            ],
        }


class LeakyLongDigitSchemaIdentifierTool:
    name = "get_schema"
    allow_parallel = True

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "columns": [
                                {"name": "5551234567Phone", "type": "string"},
                                {"field": "5551234567Id", "type": "string"},
                                {"name": "1234567890OrderId", "type": "string"},
                                {"name": "tracking_id", "type": "string"},
                            ],
                            "column_count": 4,
                        },
                    ),
                }
            ],
        }


class LeakySeparatedTechnicalSuffixSchemaIdentifierTool:
    name = "get_schema"
    allow_parallel = True

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "columns": [
                                {"name": "Jane_DoeName", "type": "string"},
                                {"field": "Bob_WilsonId", "type": "string"},
                                {"name": "Jane_Doe_Address", "type": "string"},
                                {"field": "Jane_DoePhone", "type": "string"},
                                {"name": "Bob_Wilson_OrderId", "type": "string"},
                                {"name": "customer_id", "type": "string"},
                                {"name": "address_line_1", "type": "string"},
                                {"name": "ship_to_name", "type": "string"},
                                {"name": "tracking_id", "type": "string"},
                            ],
                            "column_count": 9,
                        },
                    ),
                }
            ],
        }


class LeakySingleTokenTechnicalSuffixSchemaIdentifierTool:
    name = "get_schema"
    allow_parallel = True

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "columns": [
                                {"name": "Jane_name", "type": "string"},
                                {"field": "Bob_id", "type": "string"},
                                {"name": "742_address", "type": "string"},
                                {"name": "alice_phone", "type": "string"},
                                {"field": "maria_customer_id", "type": "string"},
                                {"name": "customer_id", "type": "string"},
                                {"name": "address_line_1", "type": "string"},
                                {"name": "ship_to_name", "type": "string"},
                                {"name": "reference_id", "type": "string"},
                                {"name": "tracking_id", "type": "string"},
                            ],
                            "column_count": 10,
                        },
                    ),
                }
            ],
        }


class LeakySeparatorSchemaIdentifierTool:
    name = "get_schema"
    allow_parallel = True

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "columns": [
                                {"name": "phone_555-123-4567", "type": "string"},
                                {"field": "address_742_main_st", "type": "string"},
                                {"name": "ship_to_address_742_main_st", "type": "string"},
                                {"name": "ship_to_742_main_st_address", "type": "string"},
                                {"field": "billing_address_742mainst", "type": "string"},
                                {"name": "ship_to_phone_555_123_4567", "type": "string"},
                                {"name": "email_jane_example_com", "type": "string"},
                                {"name": "name_jane", "type": "string"},
                                {"name": "ship_to_name_jane", "type": "string"},
                                {"name": "customer_name_jane", "type": "string"},
                                {"name": "email_jane", "type": "string"},
                                {"name": "ship_to_email_jane", "type": "string"},
                                {"name": "phone_number", "type": "string"},
                                {"name": "email_address", "type": "string"},
                                {"name": "address_line_1", "type": "string"},
                                {"name": "ship_to_address_1", "type": "string"},
                                {"name": "tracking_id", "type": "string"},
                            ],
                            "column_count": 17,
                        },
                    ),
                }
            ],
        }


class LeakyCompactSeparatorHybridAddressSchemaIdentifierTool:
    name = "get_schema"
    allow_parallel = True

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "columns": [
                                {"name": "address_742mainst", "type": "string"},
                                {"field": "address_742_mainst", "type": "string"},
                                {"name": "address_line_1", "type": "string"},
                                {"name": "tracking_id", "type": "string"},
                            ],
                            "column_count": 4,
                        },
                    ),
                }
            ],
        }


class TechnicalVocabularySchemaIdentifierTool:
    name = "get_schema"
    allow_parallel = True

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "columns": [
                                {"name": "sku", "type": "string"},
                                {"name": "quantity", "type": "number"},
                                {"field": "carrier", "type": "string"},
                                {"name": "service_level", "type": "string"},
                            ],
                            "column_count": 4,
                        },
                    ),
                }
            ],
        }


class TechnicalCamelSchemaIdentifierTool:
    name = "get_schema"
    allow_parallel = True

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "columns": [
                                {"name": "trackingId", "type": "string"},
                                {"field": "OrderId", "type": "string"},
                                {"name": "PhoneNumber", "type": "string"},
                            ],
                            "column_count": 3,
                        },
                    ),
                }
            ],
        }


class LeakyExceptionTool:
    name = "fetch_rows"
    allow_parallel = False

    async def handler(self, _args):
        raise RuntimeError(
            "label_url=https://labels.example/leak address=1 Main "
            'request_body={"street":"2 Main"}'
        )


class LeakyErrorTextTool:
    name = "fetch_rows"
    allow_parallel = False

    async def handler(self, _args):
        return {
            "isError": True,
            "content": [
                {
                    "type": "text",
                    "text": "error: label_url=https://labels.example/leak address=1 Main request_body={\"street\":\"2 Main\"}",
                }
            ],
        }


class JsonTextErrorTool:
    name = "fetch_rows"
    allow_parallel = False

    def __init__(self, payload):
        self.payload = payload

    async def handler(self, _args):
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(self.payload),
                }
            ],
        }


class RawErrorThenJsonTool:
    name = "fetch_rows"
    allow_parallel = False

    async def handler(self, _args):
        return {
            "content": [
                {
                    "type": "text",
                    "text": "error: label_url=https://labels.example/leak address=1 Main",
                },
                {
                    "type": "text",
                    "text": '{"fetch_id":"fetch-1"}',
                },
            ],
        }


class LeakyErrorDictTool:
    name = "fetch_rows"
    allow_parallel = False

    async def handler(self, _args):
        return {
            "isError": True,
            "error": "label_url=https://labels.example/leak address=1 Main",
            "message": 'requestBody={"street":"2 Main"}',
            "status": 500,
        }


class LeakySuccessTextTool:
    name = "text_payload"
    allow_parallel = False

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": "label_url=https://labels.example/leak documentUrl=https://documents.example/leak address=1 Main",
                }
            ],
        }


class LaterJsonContentTool:
    name = "later_json_payload"
    allow_parallel = False

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": "non-json preface address=1 Main",
                },
                {
                    "type": "text",
                    "text": '{"fetch_id":"fetch-1","total_count":2,"rows":[{"name":"Jane","address":"1 Main"}]}',
                },
            ],
        }


class LeakySuccessListTool:
    name = "list_payload"
    allow_parallel = False

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": '["label_url=https://labels.example/leak","documentUrl=https://documents.example/leak","address=1 Main"]',
                }
            ],
        }


class LeakySuccessBytesTool:
    name = "bytes_payload"
    allow_parallel = False

    async def handler(self, _args):
        return b"document bytes label_url=https://labels.example/leak address=1 Main"


class SuccessNumberTool:
    name = "number_payload"
    allow_parallel = False

    async def handler(self, _args):
        return 42


class ResolveFilterIntentTool:
    name = "resolve_filter_intent"
    allow_parallel = False

    async def handler(self, _args):
        raise AssertionError("policy denial should happen before handler execution")


class ResolvedFilterIntentResultTool:
    name = "resolve_filter_intent"
    allow_parallel = False

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "status": "RESOLVED",
                            "root": {
                                "logic": "AND",
                                "conditions": [
                                    {
                                        "column": "ship_to_state",
                                        "operator": "in",
                                        "operands": [
                                            {"type": "string", "value": "NY"},
                                            {"type": "string", "value": "CT"},
                                        ],
                                    }
                                ],
                            },
                            "resolution_token": "resolved-token_123=",
                            "schema_signature": "schema-1",
                            "canonical_dict_version": "dict-v1",
                            "source_fingerprint": "abc123",
                            "compiler_version": "filter_compiler_v2",
                            "mapping_version": "mapping_cache_v2",
                            "normalizer_version": "column_mapping_v2",
                            "rows": [{"name": "Jane", "address": "1 Main"}],
                            "label_url": "https://labels.example/leak",
                        }
                    ),
                }
            ],
        }


class NeedsConfirmationFilterIntentResultTool:
    name = "resolve_filter_intent"
    allow_parallel = False

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "status": "NEEDS_CONFIRMATION",
                            "root": {"logic": "AND", "conditions": []},
                            "resolution_token": "needs-confirmation-token_123=",
                            "pending_confirmations": [
                                {
                                    "term": "NORTHEAST",
                                    "expansion": "NORTHEAST (CT, ME, MA...)",
                                    "tier": "B",
                                    "customer_name": "Jane",
                                }
                            ],
                            "sample_rows": [{"address": "1 Main"}],
                        }
                    ),
                }
            ],
        }


class ConfirmFilterInterpretationResultTool:
    name = "confirm_filter_interpretation"
    allow_parallel = False

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "status": "RESOLVED",
                            "filter_spec": {
                                "status": "RESOLVED",
                                "root": {
                                    "logic": "AND",
                                    "conditions": [
                                        {
                                            "column": "recipient_type",
                                            "operator": "eq",
                                            "operands": [
                                                {
                                                    "type": "string",
                                                    "value": "business",
                                                }
                                            ],
                                        }
                                    ],
                                },
                                "resolution_token": "confirmed-token_123=",
                            },
                            "resolution_token": "confirmed-token_123=",
                            "raw_rows": [{"name": "Jane"}],
                            "document_url": "https://documents.example/leak",
                        }
                    ),
                }
            ],
        }


class ContactOrderDataTool:
    name = "safe_projection_payload"
    allow_parallel = False

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": '{"contact":{"id":"contact-1","display_name":"Jane","address_line_1":"1 Main","phone":"555"},"order_data":{"ship_to_name":"Jane","ship_to_address_line_1":"1 Main"},"fetch_id":"fetch-1","total_count":1}',
                }
            ],
        }


class NestedUnsafeOnlyTool:
    name = "nested_payload"
    allow_parallel = False

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": '{"profile":{"display_name":"Jane","address_line_1":"1 Main","phone":"555","email":"jane@example.com"},"fetch_id":"fetch-1"}',
                }
            ],
        }


class SafeAllowlistedValuesTool:
    name = "safe_values_payload"
    allow_parallel = False

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": '{"fetch_id":"fetch-1","job_id":"job-1","total_count":2,"returned_count":1,"status":"ready","action":"created","success":true}',
                }
            ],
        }


class FailedStatusPayloadTool:
    name = "get_job_status"
    allow_parallel = True

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": '{"status":"failed","job_id":"job-1"}',
                }
            ],
        }


class UnsafeNumericCountValuesTool:
    name = "numeric_payload"
    allow_parallel = False

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": '{"fetch_id":"fetch-1","count":5551234567,"total_count":123456789012,"returned_count":9876543210,"nested":{"count":123456789012}}',
                }
            ],
        }


class UnsafeAllowlistedValuesTool:
    name = "unsafe_values_payload"
    allow_parallel = False

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": '{"status":"Jane jane@example.com label_url=https://labels.example/leak address=1 Main","secondary_status":"JaneDoe","numeric_status":"5551234567","action":"created address 1 Main","secondary_action":"1MainSt","fetch_id":"fetch https://labels.example/leak","secondary_fetch_id":"JaneDoe","job_id":"job 1 Main","secondary_job_id":"5551234567","artifact_id":"artifact@example.com","confirmation_token":"confirm/label_url/leak","safe_id":"safe address","count":"address 1 Main","total_count":"1 Main","returned_count":true,"success":"true","ok":"false"}',
                }
            ],
        }


class CompactUnsafeAllowlistedValuesTool:
    name = "compact_unsafe_values_payload"
    allow_parallel = False

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": '{"status":"JaneDoe","nested_status":{"status":"5551234567"},"action":"1MainSt","fetch_id":"JaneDoe","job_id":"5551234567"}',
                }
            ],
        }


class UnsafePrefixedOpaqueValuesTool:
    name = "unsafe_prefixed_values_payload"
    allow_parallel = False

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": '{"fetch_id":"fetch-JaneDoe","job_id":"job-5551234567","safe_id":"safe-1MainSt","artifact_id":"artifact-jane.example.com","confirmation_token":"confirm-JaneDoe","nested":{"safe_id":"safe-order-12345","fetch_id":"fetch-email-123","confirmation_token":"confirm-customer-123","job_id":"job-phone-123","artifact_id":"artifact-name-123"},"hyphenated":{"safe_id":"safe-555-123-4567","fetch_id":"fetch-123-45-6789","job_id":"job-987-654-3210"}}',
                }
            ],
        }


class HumanReadableOpaqueValuesTool:
    name = "human_readable_values_payload"
    allow_parallel = False

    async def handler(self, _args):
        return {
            "isError": False,
            "content": [
                {
                    "type": "text",
                    "text": '{"fetch_id":"fetch-bob-wilson","job_id":"job-robert-jones","safe_id":"safe-742-evergreen-terrace","confirmation_token":"confirm-742-evergreen-terrace","artifact_id":"artifact-elm-st-drive"}',
                }
            ],
        }


class FakeCatalog:
    def __init__(self, tool=None):
        self.tool = tool or FakeTool()

    def has(self, name):
        return name == self.tool.name

    def get(self, name):
        return self.tool


@pytest.fixture
def dispatcher() -> LocalToolDispatcher:
    return LocalToolDispatcher(
        catalog=FakeCatalog(),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )


async def test_dispatcher_strips_rows_from_provider_result(
    dispatcher: LocalToolDispatcher,
) -> None:
    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="fetch_rows",
            parsed_input={"all_rows": True, "include_rows": True},
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {
        "fetch_id": "fetch-1",
        "total_count": 2,
        "returned_count": 2,
    }
    assert "sample_rows" not in result.content
    assert "1 Main" not in result.content


async def test_dispatcher_ignores_error_like_customer_row_fields() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(SuccessfulRowsWithErrorFieldsTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="fetch_rows",
            parsed_input={"all_rows": True, "include_rows": True},
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {
        "fetch_id": "fetch-1",
        "total_count": 2,
        "returned_count": 2,
    }

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in ("customer note", "Jane", "1 Main"):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content


async def test_dispatcher_drops_contact_and_order_data_scalars_from_dict_payload() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(ContactOrderDataTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="safe_projection_payload",
            parsed_input={},
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {"fetch_id": "fetch-1", "total_count": 1}

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in (
        "contact",
        "order_data",
        "contact-1",
        "Jane",
        "1 Main",
        "555",
    ):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content


async def test_dispatcher_drops_nested_dict_with_only_unsafe_scalars() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(NestedUnsafeOnlyTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="nested_payload",
            parsed_input={},
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {"fetch_id": "fetch-1"}

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in (
        "profile",
        "Jane",
        "1 Main",
        "555",
        "jane@example.com",
    ):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content


async def test_dispatcher_preserves_valid_allowlisted_scalar_values() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(SafeAllowlistedValuesTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="safe_values_payload",
            parsed_input={},
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {
        "fetch_id": "fetch-1",
        "job_id": "job-1",
        "total_count": 2,
        "returned_count": 1,
        "status": "ready",
        "action": "created",
        "success": True,
    }


async def test_dispatcher_projects_failed_status_payload_without_tool_error() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(FailedStatusPayloadTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="get_job_status",
            parsed_input={"job_id": "job-1"},
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {"status": "failed", "job_id": "job-1"}
    assert result.content == (
        "get_job_status completed. Provider-safe fields: job_id, status."
    )


async def test_dispatcher_emits_tool_call_event_once_for_allowed_call() -> None:
    events = []
    tool = EventObservedTool(events)
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(tool),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda event, payload: events.append((event, payload)),
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="fetch_rows",
            parsed_input={"all_rows": True},
        )
    )

    assert result.is_error is False
    assert tool.saw_tool_call_before_handler is True
    assert events == [
        (
            "tool_call",
            {
                "tool_name": "fetch_rows",
                "tool_input": {"all_rows": True},
                "tool_use_id": "call-1",
            },
        )
    ]

    event_payload = json.dumps(events[0][1], sort_keys=True)
    for handler_text in ("fetch-1", "Jane", "1 Main", "sample_rows"):
        assert handler_text not in event_payload


async def test_dispatcher_emits_tool_call_event_once_for_unknown_tool() -> None:
    events = []
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda event, payload: events.append((event, payload)),
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-unknown",
            tool_name="mcp__ups__rate_shipment",
            parsed_input={"service": "ground"},
        )
    )

    assert result.is_error is True
    assert events == [
        (
            "tool_call",
            {
                "tool_name": "mcp__ups__rate_shipment",
                "tool_input": {"service": "ground"},
                "tool_use_id": "call-unknown",
            },
        )
    ]


async def test_dispatcher_emits_tool_call_event_once_for_policy_denial() -> None:
    events = []
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda event, payload: events.append((event, payload)),
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-denied",
            tool_name="fetch_rows",
            parsed_input={"sql": "SELECT * FROM orders"},
        )
    )

    assert result.is_error is True
    assert events == [
        (
            "tool_call",
            {
                "tool_name": "fetch_rows",
                "tool_input": {"sql": "SELECT * FROM orders"},
                "tool_use_id": "call-denied",
            },
        )
    ]


async def test_dispatcher_drops_phone_or_order_shaped_numeric_count_values() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(UnsafeNumericCountValuesTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="numeric_payload",
            parsed_input={},
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {"fetch_id": "fetch-1"}

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in (
        "count",
        "total_count",
        "returned_count",
        "nested",
        "5551234567",
        "123456789012",
        "9876543210",
    ):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content


async def test_dispatcher_drops_allowlisted_keys_with_unsafe_values() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(UnsafeAllowlistedValuesTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="unsafe_values_payload",
            parsed_input={},
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {}

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in (
        "Jane",
        "jane@example.com",
        "https://labels.example/leak",
        "label_url",
        "1 Main",
        "JaneDoe",
        "5551234567",
        "1MainSt",
        "true",
        "false",
    ):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content


async def test_dispatcher_drops_compact_pii_like_allowlisted_values() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(CompactUnsafeAllowlistedValuesTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="compact_unsafe_values_payload",
            parsed_input={},
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {}

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in (
        "JaneDoe",
        "5551234567",
        "1MainSt",
        "nested_status",
    ):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content


async def test_dispatcher_drops_unsafe_prefixed_opaque_values() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(UnsafePrefixedOpaqueValuesTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="unsafe_prefixed_values_payload",
            parsed_input={},
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {}

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in (
        "fetch-JaneDoe",
        "job-5551234567",
        "safe-1MainSt",
        "artifact-jane.example.com",
        "confirm-JaneDoe",
        "safe-order-12345",
        "fetch-email-123",
        "confirm-customer-123",
        "job-phone-123",
        "artifact-name-123",
        "safe-555-123-4567",
        "fetch-123-45-6789",
        "job-987-654-3210",
        "JaneDoe",
        "5551234567",
        "123456789",
        "9876543210",
        "1MainSt",
        "order",
        "customer",
        "email",
        "phone",
        "name",
    ):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content


async def test_dispatcher_drops_human_readable_opaque_values() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(HumanReadableOpaqueValuesTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="human_readable_values_payload",
            parsed_input={},
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {}

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in (
        "fetch-bob-wilson",
        "job-robert-jones",
        "safe-742-evergreen-terrace",
        "confirm-742-evergreen-terrace",
        "artifact-elm-st-drive",
        "bob",
        "wilson",
        "robert",
        "jones",
        "evergreen",
        "terrace",
        "elm",
        "drive",
    ):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content


async def test_dispatcher_counts_mixed_lists_with_dicts_before_provider_result() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(MixedListTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="mixed_payload",
            parsed_input={"all_rows": True},
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {
        "items": {"count": 2},
    }

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in (
        "Jane",
        "1 Main",
        "safe-1",
    ):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content


async def test_dispatcher_drops_camel_case_and_plural_unsafe_keys() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(UnsafeKeyVariantTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="variant_payload",
            parsed_input={},
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {"safe_id": "safe-1"}

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in (
        "labelUrl",
        "labelURLs",
        "labelDownloadUrl",
        "https://labels.example/one",
        "https://labels.example/two",
        "https://labels.example/download",
        "documentUrl",
        "document_url",
        "documentDownloadUrl",
        "document_download_url",
        "https://documents.example/one",
        "https://documents.example/two",
        "https://documents.example/download-one",
        "https://documents.example/download-two",
        "requestBody",
        "responseBody",
        "documentBytes",
        "fileContentBase64",
        "sampleRows",
        "previewRows",
        "rawRows",
        "raw_rows",
        "sample",
        "samples",
        "labelData",
        "label_data",
        "rawResponse",
        "1 Main",
        "2 Main",
        "3 Main",
        "4 Main",
        "5 Main",
        "6 Main",
        "7 Main",
        "Jane",
        "binary-label",
        "encoded-document",
        "label-binary-data",
        "label-binary-data-two",
    ):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content


async def test_dispatcher_drops_compound_unsafe_keys_from_payload_and_summary() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(CompoundUnsafeKeyTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="compound_payload",
            parsed_input={},
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {"fetch_id": "fetch-1"}

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in (
        "shippingLabelUrls",
        "paperlessDocumentUrls",
        "rawResponseBody",
        "requestPayload",
        "responsePayload",
        "rawPayload",
        "shipmentSampleRows",
        "shipmentRawRows",
        "shipmentPreviewRows",
        "https://labels.example/leak",
        "https://documents.example/leak",
        "1 Main",
        "Jane",
        "2 Main",
        "3 Main",
        "4 Main",
        "5 Main",
        "555",
        "jane@example.com",
    ):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content


async def test_dispatcher_drops_unsafe_container_keys_with_safe_nested_values() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(UnsafeContainerKeyTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="unsafe_container_payload",
            parsed_input={},
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {"fetch_id": "fetch-1"}

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in (
        "customerData",
        "orderData",
        "contactData",
        "addressData",
        "phoneData",
        "emailData",
        "nameData",
        "fetch-2",
        "job-2",
        "safe-2",
        "ready",
        "created",
        "true",
    ):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content


async def test_dispatcher_drops_secret_container_keys_with_safe_nested_values() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(SecretContainerKeyTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="container_probe",
            parsed_input={},
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {"fetch_id": "fetch-1"}

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in (
        "secret",
        "secrets",
        "apiSecret",
        "carrierSecretData",
        "job-1",
        "fetch-2",
        "safe-2",
        "ready",
    ):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content


async def test_dispatcher_drops_request_response_raw_payload_wrappers() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(WrapperContainerKeyTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="wrapper_probe",
            parsed_input={},
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {"fetch_id": "fetch-1"}

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in (
        "carrierRequest",
        "carrierResponse",
        "raw",
        "payload",
        "apiPayload",
        "job-1",
        "fetch-2",
        "safe-2",
        "ready",
        "created",
    ):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content


async def test_dispatcher_drops_nested_dict_keys_that_are_data() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(NestedKeyDataTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="nested_key_probe",
            parsed_input={},
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {"fetch_id": "fetch-1"}

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in (
        "summary",
        "Jane Doe",
        "jane@example.com",
        "742 Main St",
        "BobWilson",
        "Jane",
        "Main",
    ):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content


async def test_dispatcher_preserves_safe_schema_metadata_without_row_values() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(SchemaMetadataTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="get_schema",
            parsed_input={},
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {
        "columns": [
            {"name": "Ship To Name", "type": "string", "nullable": False},
            {
                "field": "weight_oz",
                "data_type": "number",
                "null_count": 0,
                "non_null_count": 2,
            },
        ],
        "column_count": 2,
    }
    assert "columns" in result.content
    assert "column_count" in result.content

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in (
        "sample_values",
        "sample_rows",
        "raw_values",
        '"values"',
        "rows",
        "Jane",
        "1 Main",
    ):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content


async def test_dispatcher_preserves_safe_source_info_without_row_values() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(SourceInfoTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="get_source_info",
            parsed_input={},
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {
        "source_type": "csv",
        "row_count": 25,
        "column_count": 2,
        "columns": [
            {"name": "Order ID", "type": "string"},
            {"name": "Ship To Address 1", "type": "string"},
        ],
    }
    for safe_field in ("source_type", "row_count", "column_count", "columns"):
        assert safe_field in result.content

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in (
        "source_name",
        "Jane Orders",
        "sample_rows",
        '"values"',
        "Jane",
        "1 Main",
    ):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content


@pytest.mark.parametrize(
    "source_type",
    [
        "BobWilson",
        "JaneDoe",
        "jane@example.com",
        "c s v",
        "c/s/v",
        "c://s/v",
        " csv",
        "CSV",
    ],
)
async def test_dispatcher_drops_person_like_source_type_values(source_type) -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(UnsafeSourceTypeTool(source_type)),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="get_source_info",
            parsed_input={},
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {
        "row_count": 25,
        "column_count": 2,
    }

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    assert source_type not in provider_payload
    assert source_type not in result.content
    assert "source_type" not in provider_payload
    assert "source_type" not in result.content


async def test_dispatcher_drops_row_like_schema_column_text() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(LeakySchemaTextTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="get_schema",
            parsed_input={},
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {
        "columns": [
            {"name": "reference_id"},
            {"name": "tracking_id", "type": "string"},
        ],
        "column_count": 6,
    }

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in (
        "Jane Doe",
        "1 Main",
        "5551234567",
        "jane doe",
        "Jane Doe-Smith",
        "742 Main St",
        "Bob Wilson",
        "jane@example.com",
        "https://labels.example/leak",
        "label",
    ):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content


async def test_dispatcher_drops_person_like_schema_type_text() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(LeakySchemaTypeTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="get_schema",
            parsed_input={},
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {
        "columns": [{"name": "reference_id"}],
        "column_count": 1,
    }

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in ("Jane Doe", "Bob Wilson"):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content


async def test_dispatcher_drops_obfuscated_schema_type_tokens() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(ObfuscatedSchemaTypeTokenTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="get_schema",
            parsed_input={},
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {
        "columns": [
            {"name": "tracking_id"},
            {"name": "status"},
            {"name": "reference_id", "type": "string"},
        ],
        "column_count": 3,
    }

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in ("s/t/r/i/n/g", "n u m b e r", "String", "NUMBER"):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content


async def test_dispatcher_drops_domain_like_schema_text() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(LeakySchemaUrlTextTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="get_schema",
            parsed_input={},
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {
        "columns": [{"name": "tracking_id", "type": "string"}],
        "column_count": 4,
    }

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in (
        "labels.example/leak",
        "www.example.com",
        "documents.example/file.pdf",
        "example",
    ):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content


async def test_dispatcher_drops_compact_row_like_schema_identifiers() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(LeakyCompactSchemaIdentifierTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="get_schema",
            parsed_input={},
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {
        "columns": [{"name": "tracking_id", "type": "string"}],
        "column_count": 5,
    }

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in (
        "742MainSt",
        "JaneDoe",
        "Jane_Doe",
        "BobWilson",
    ):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content


async def test_dispatcher_drops_row_like_schema_identifiers_with_technical_fragments() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(LeakyTechnicalFragmentSchemaIdentifierTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="get_schema",
            parsed_input={},
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {
        "columns": [
            {"name": "customer_id", "type": "string"},
            {"name": "address_line_1", "type": "string"},
            {"name": "ship_to_name", "type": "string"},
            {"name": "tracking_id", "type": "string"},
        ],
        "column_count": 7,
    }

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in (
        "JaneDoeName",
        "BobWilsonId",
        "742Address",
    ):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content


async def test_dispatcher_drops_long_digit_schema_identifiers_with_technical_suffixes() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(LeakyLongDigitSchemaIdentifierTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="get_schema",
            parsed_input={},
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {
        "columns": [{"name": "tracking_id", "type": "string"}],
        "column_count": 4,
    }

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in (
        "5551234567Phone",
        "5551234567Id",
        "1234567890OrderId",
    ):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content


async def test_dispatcher_drops_separated_person_schema_identifiers_with_technical_suffixes() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(LeakySeparatedTechnicalSuffixSchemaIdentifierTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="get_schema",
            parsed_input={},
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {
        "columns": [
            {"name": "customer_id", "type": "string"},
            {"name": "address_line_1", "type": "string"},
            {"name": "ship_to_name", "type": "string"},
            {"name": "tracking_id", "type": "string"},
        ],
        "column_count": 9,
    }

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in (
        "Jane_DoeName",
        "Bob_WilsonId",
        "Jane_Doe_Address",
        "Jane_DoePhone",
        "Bob_Wilson_OrderId",
    ):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content


async def test_dispatcher_drops_single_row_value_schema_identifiers_with_technical_suffixes() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(LeakySingleTokenTechnicalSuffixSchemaIdentifierTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="get_schema",
            parsed_input={},
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {
        "columns": [
            {"name": "customer_id", "type": "string"},
            {"name": "address_line_1", "type": "string"},
            {"name": "ship_to_name", "type": "string"},
            {"name": "reference_id", "type": "string"},
            {"name": "tracking_id", "type": "string"},
        ],
        "column_count": 10,
    }

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in (
        "Jane_name",
        "Bob_id",
        "742_address",
        "alice_phone",
        "maria_customer_id",
    ):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content


async def test_dispatcher_drops_separator_form_phone_and_address_schema_identifiers() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(LeakySeparatorSchemaIdentifierTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="get_schema",
            parsed_input={},
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {
        "columns": [
            {"name": "phone_number", "type": "string"},
            {"name": "email_address", "type": "string"},
            {"name": "address_line_1", "type": "string"},
            {"name": "ship_to_address_1", "type": "string"},
            {"name": "tracking_id", "type": "string"},
        ],
        "column_count": 17,
    }

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in (
        "phone_555-123-4567",
        "address_742_main_st",
        "ship_to_address_742_main_st",
        "ship_to_742_main_st_address",
        "billing_address_742mainst",
        "ship_to_phone_555_123_4567",
        "email_jane_example_com",
        "jane_example_com",
        "name_jane",
        "ship_to_name_jane",
        "customer_name_jane",
        "email_jane",
        "ship_to_email_jane",
        "555-123-4567",
        "742_main_st",
    ):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content


async def test_dispatcher_drops_compact_separator_hybrid_address_schema_identifiers() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(LeakyCompactSeparatorHybridAddressSchemaIdentifierTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="get_schema",
            parsed_input={},
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {
        "columns": [
            {"name": "address_line_1", "type": "string"},
            {"name": "tracking_id", "type": "string"},
        ],
        "column_count": 4,
    }

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in (
        "address_742mainst",
        "address_742_mainst",
        "742mainst",
        "742_mainst",
    ):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content


async def test_dispatcher_preserves_safe_technical_schema_identifiers() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(TechnicalVocabularySchemaIdentifierTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="get_schema",
            parsed_input={},
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {
        "columns": [
            {"name": "sku", "type": "string"},
            {"name": "quantity", "type": "number"},
            {"field": "carrier", "type": "string"},
            {"name": "service_level", "type": "string"},
        ],
        "column_count": 4,
    }

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for safe_text in ("sku", "quantity", "carrier", "service_level"):
        assert safe_text in provider_payload


async def test_dispatcher_preserves_technical_camel_case_schema_identifiers() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(TechnicalCamelSchemaIdentifierTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="get_schema",
            parsed_input={},
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {
        "columns": [
            {"name": "trackingId", "type": "string"},
            {"field": "OrderId", "type": "string"},
            {"name": "PhoneNumber", "type": "string"},
        ],
        "column_count": 3,
    }

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for safe_text in ("trackingId", "OrderId", "PhoneNumber"):
        assert safe_text in provider_payload


async def test_dispatcher_handler_exception_returns_generic_provider_error() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(LeakyExceptionTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="fetch_rows",
            parsed_input={"all_rows": True},
        )
    )

    assert result.is_error is True
    assert result.content == "Tool 'fetch_rows' failed."
    assert result.sanitized_error == "Tool 'fetch_rows' failed."

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in (
        "https://labels.example/leak",
        "label_url",
        "1 Main",
        "request_body",
        "2 Main",
    ):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content
        assert leaked_text not in result.sanitized_error


async def test_dispatcher_handler_exception_log_excludes_raw_exception_text(
    caplog,
) -> None:
    caplog.set_level(
        logging.WARNING,
        logger="src.services.conversation_runtime.dispatcher",
    )
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(LeakyExceptionTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="fetch_rows",
            parsed_input={"all_rows": True},
        )
    )

    assert result.is_error is True
    assert "exception_type=RuntimeError" in caplog.text
    for leaked_text in (
        "https://labels.example/leak",
        "label_url",
        "1 Main",
        "request_body",
        "2 Main",
    ):
        assert leaked_text not in caplog.text


async def test_dispatcher_error_text_returns_generic_provider_error() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(LeakyErrorTextTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="fetch_rows",
            parsed_input={"all_rows": True},
        )
    )

    assert result.is_error is True
    assert result.content == "fetch_rows failed."
    assert result.sanitized_error == "fetch_rows failed."
    assert result.structured_payload == {"error": "fetch_rows failed."}

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in (
        "https://labels.example/leak",
        "label_url",
        "1 Main",
        "request_body",
        "2 Main",
    ):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content
        assert leaked_text not in result.sanitized_error


@pytest.mark.parametrize(
    "payload",
    [
        {"error": "label_url=https://labels.example/leak address=1 Main"},
        {"isError": True, "message": "label_url=https://labels.example/leak"},
        {"is_error": True, "message": "address=1 Main"},
    ],
)
async def test_dispatcher_json_text_errors_return_generic_provider_error(
    payload,
) -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(JsonTextErrorTool(payload)),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="fetch_rows",
            parsed_input={"all_rows": True},
        )
    )

    assert result.is_error is True
    assert result.content == "fetch_rows failed."
    assert result.sanitized_error == "fetch_rows failed."
    assert result.structured_payload == {"error": "fetch_rows failed."}

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in (
        "https://labels.example/leak",
        "label_url",
        "1 Main",
        "address",
    ):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content
        assert leaked_text not in result.sanitized_error


async def test_dispatcher_json_text_error_array_returns_generic_provider_error() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(
            JsonTextErrorTool(
                [{"error": "label_url=https://labels.example/leak address=1 Main"}],
            ),
        ),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="fetch_rows",
            parsed_input={"all_rows": True},
        )
    )

    assert result.is_error is True
    assert result.content == "fetch_rows failed."
    assert result.sanitized_error == "fetch_rows failed."
    assert result.structured_payload == {"error": "fetch_rows failed."}

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in (
        "https://labels.example/leak",
        "label_url",
        "1 Main",
        "address",
    ):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content
        assert leaked_text not in result.sanitized_error


async def test_dispatcher_raw_error_content_wins_over_later_json_success() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(RawErrorThenJsonTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="fetch_rows",
            parsed_input={"all_rows": True},
        )
    )

    assert result.is_error is True
    assert result.content == "fetch_rows failed."
    assert result.sanitized_error == "fetch_rows failed."
    assert result.structured_payload == {"error": "fetch_rows failed."}

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in (
        "https://labels.example/leak",
        "label_url",
        "1 Main",
        "fetch-1",
    ):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content
        assert leaked_text not in result.sanitized_error


async def test_dispatcher_error_dict_returns_generic_provider_error() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(LeakyErrorDictTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="fetch_rows",
            parsed_input={"all_rows": True},
        )
    )

    assert result.is_error is True
    assert result.content == "fetch_rows failed."
    assert result.sanitized_error == "fetch_rows failed."
    assert result.structured_payload == {"error": "fetch_rows failed."}

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in (
        "https://labels.example/leak",
        "label_url",
        "1 Main",
        "requestBody",
        "2 Main",
    ):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content
        assert leaked_text not in result.sanitized_error


async def test_dispatcher_success_text_payload_returns_generic_provider_result() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(LeakySuccessTextTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="text_payload",
            parsed_input={},
        )
    )

    assert result.is_error is False
    assert result.content == "text_payload completed."
    assert result.structured_payload == {"result_type": "text"}

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in (
        "https://labels.example/leak",
        "https://documents.example/leak",
        "label_url",
        "documentUrl",
        "1 Main",
    ):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content


async def test_dispatcher_extracts_later_json_content_block() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(LaterJsonContentTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="later_json_payload",
            parsed_input={},
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {"fetch_id": "fetch-1", "total_count": 2}
    assert "fetch_id" in result.content
    assert "total_count" in result.content

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in (
        "non-json preface",
        "rows",
        "Jane",
        "1 Main",
    ):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content


async def test_dispatcher_success_scalar_list_returns_count_provider_result() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(LeakySuccessListTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="list_payload",
            parsed_input={},
        )
    )

    assert result.is_error is False
    assert result.content == "list_payload completed."
    assert result.structured_payload == {"count": 3}

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in (
        "https://labels.example/leak",
        "https://documents.example/leak",
        "label_url",
        "documentUrl",
        "1 Main",
    ):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content


async def test_dispatcher_success_bytes_payload_returns_type_marker() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(LeakySuccessBytesTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="bytes_payload",
            parsed_input={},
        )
    )

    assert result.is_error is False
    assert result.content == "bytes_payload completed."
    assert result.structured_payload == {"result_type": "bytes"}

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for leaked_text in (
        "document bytes",
        "https://labels.example/leak",
        "label_url",
        "1 Main",
    ):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content


async def test_dispatcher_success_non_string_scalar_returns_type_marker() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(SuccessNumberTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="number_payload",
            parsed_input={},
        )
    )

    assert result.is_error is False
    assert result.content == "number_payload completed."
    assert result.structured_payload == {"result_type": "scalar"}
    assert "42" not in json.dumps(result.structured_payload, sort_keys=True)
    assert "42" not in result.content


async def test_dispatcher_denies_unknown_tool_before_handler_execution(
    dispatcher: LocalToolDispatcher,
) -> None:
    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="mcp__ups__rate_shipment",
            parsed_input={},
        )
    )

    assert result.is_error is True
    assert "not available" in result.content


async def test_dispatcher_turns_policy_denial_into_provider_tool_error(
    dispatcher: LocalToolDispatcher,
) -> None:
    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="fetch_rows",
            parsed_input={"sql": "SELECT * FROM orders"},
        )
    )

    assert result.is_error is True
    assert result.sanitized_error is not None
    assert "Raw SQL" in result.sanitized_error


async def test_dispatcher_policy_denial_with_leaky_reason_is_generic() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(ResolveFilterIntentTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="resolve_filter_intent",
            parsed_input={
                "intent": {
                    "field": "status",
                    "operator": "Jane 1 Main St jane@example.com",
                    "value": "ready",
                }
            },
        )
    )

    assert result.is_error is True
    assert result.content == "Tool call denied by policy."
    assert result.sanitized_error == "Tool call denied by policy."
    assert result.metadata == {}

    provider_payload = json.dumps(
        {
            "structured_payload": result.structured_payload,
            "metadata": result.metadata,
        },
        sort_keys=True,
    )
    for leaked_text in (
        "Jane",
        "1 Main",
        "jane@example.com",
        "Invalid operator",
    ):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content
        assert leaked_text not in result.sanitized_error


async def test_dispatcher_preserves_resolved_filter_workflow_state() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(ResolvedFilterIntentResultTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="resolve_filter_intent",
            parsed_input={
                "intent": {
                    "root": {
                        "logic": "AND",
                        "conditions": [
                            {
                                "column": "ship_to_state",
                                "operator": "in",
                                "operands": [
                                    {"type": "string", "value": "NY"},
                                    {"type": "string", "value": "CT"},
                                ],
                            }
                        ],
                    }
                }
            },
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {
        "status": "RESOLVED",
        "root": {
            "logic": "AND",
            "conditions": [
                {
                    "column": "ship_to_state",
                    "operator": "in",
                    "operands": [
                        {"type": "string", "value": "NY"},
                        {"type": "string", "value": "CT"},
                    ],
                }
            ],
        },
        "resolution_token": "resolved-token_123=",
        "schema_signature": "schema-1",
        "canonical_dict_version": "dict-v1",
        "source_fingerprint": "abc123",
        "compiler_version": "filter_compiler_v2",
        "mapping_version": "mapping_cache_v2",
        "normalizer_version": "column_mapping_v2",
    }

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for safe_text in ("RESOLVED", "ship_to_state", "resolved-token_123="):
        assert safe_text in provider_payload
    for leaked_text in ("Jane", "1 Main", "https://labels.example/leak"):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content


async def test_dispatcher_preserves_filter_confirmation_state() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(NeedsConfirmationFilterIntentResultTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="resolve_filter_intent",
            parsed_input={"intent": {"root": {"logic": "AND", "conditions": []}}},
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {
        "status": "NEEDS_CONFIRMATION",
        "root": {"logic": "AND", "conditions": []},
        "resolution_token": "needs-confirmation-token_123=",
        "pending_confirmations": [
            {
                "term": "NORTHEAST",
                "expansion": "NORTHEAST (CT, ME, MA...)",
                "tier": "B",
            }
        ],
    }

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for safe_text in ("NEEDS_CONFIRMATION", "NORTHEAST"):
        assert safe_text in provider_payload
    for leaked_text in ("Jane", "1 Main", "customer_name"):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content


async def test_dispatcher_preserves_confirmed_filter_spec_wrapper() -> None:
    dispatcher = LocalToolDispatcher(
        catalog=FakeCatalog(ConfirmFilterInterpretationResultTool()),
        policy=RuntimePolicyEngine(interactive_shipping=False),
        emit_frontend=lambda _event, _payload: None,
    )

    result = await dispatcher.dispatch(
        ProviderToolCall(
            call_id="call-1",
            tool_name="confirm_filter_interpretation",
            parsed_input={
                "resolution_token": "needs-confirmation-token_123=",
                "intent": {"root": {"logic": "AND", "conditions": []}},
            },
        )
    )

    assert result.is_error is False
    assert result.structured_payload == {
        "status": "RESOLVED",
        "filter_spec": {
            "status": "RESOLVED",
            "root": {
                "logic": "AND",
                "conditions": [
                    {
                        "column": "recipient_type",
                        "operator": "eq",
                        "operands": [{"type": "string", "value": "business"}],
                    }
                ],
            },
            "resolution_token": "confirmed-token_123=",
        },
        "resolution_token": "confirmed-token_123=",
    }

    provider_payload = json.dumps(result.structured_payload, sort_keys=True)
    for safe_text in ("filter_spec", "recipient_type", "confirmed-token_123="):
        assert safe_text in provider_payload
    for leaked_text in ("Jane", "https://documents.example/leak"):
        assert leaked_text not in provider_payload
        assert leaked_text not in result.content
