import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.services.ai import reader_agent_decision_service as reader


@pytest.mark.parametrize('cost', [None, 'invalid', '-1', 'NaN', 'Infinity'])
def test_tokens_survive_missing_or_invalid_cost(cost):
    usage = reader._extract_openrouter_usage({'usage': {
        'prompt_tokens': 18, 'completion_tokens': 42, 'cost': cost,
    }})
    assert usage is not None
    assert (usage.input_tokens, usage.output_tokens) == (18, 42)
    assert usage.estimated_cost_usd is None


def test_independent_usage_fields_and_real_zero():
    usage = reader._extract_openrouter_usage({'usage': {
        'prompt_tokens': True, 'completion_tokens': 42, 'cost': 0,
    }})
    assert usage.input_tokens is None
    assert usage.output_tokens == 42
    assert usage.estimated_cost_usd == Decimal('0')


def test_retry_cost_unknown_does_not_discard_known_tokens():
    usage = reader._sum_reader_llm_usage(
        reader.ReaderLlmUsage(18, 42, None),
        reader.ReaderLlmUsage(20, 10, Decimal('.01')),
    )
    assert (usage.input_tokens, usage.output_tokens) == (38, 52)
    assert usage.estimated_cost_usd is None


def test_parse_failure_then_transport_failure_preserves_previous_billable_usage():
    call = AsyncMock(side_effect=[
        reader.ReaderLlmResponse('invalid json', reader.ReaderLlmUsage(18, 42, None)),
        reader.ReaderLlmResponseError(status_code=502, code=None, message='failed',
                                      usage=reader.ReaderLlmUsage(2, 3, None)),
    ])
    with pytest.raises(reader.ReaderLlmResponseError) as error:
        asyncio.run(reader.request_reader_decision_with_usage({}, llm_call=call))
    assert error.value.usage.input_tokens == 20
    assert error.value.usage.output_tokens == 45
    assert error.value.usage.estimated_cost_usd is None


@pytest.mark.parametrize('bad_token', [True, -1, 1.5, 'invalid', float('inf')])
def test_common_ledger_rejects_invalid_tokens_without_losing_other_usage(bad_token):
    from app.services.common.ai_provider_usage import AiProviderUsageOperation, build_ai_provider_usage_record
    attempt = AiProviderUsageOperation(feature_key='ai_reader', stage_key='decision').start_attempt(
        provider='river', requested_model='test', request_mode='nonstream')
    record = build_ai_provider_usage_record(attempt, status='success', response_json={'usage': {
        'prompt_tokens': bad_token, 'completion_tokens': 42, 'cost': 0,
    }})
    assert record.input_tokens is None
    assert record.output_tokens == 42
    assert record.cost_usd == Decimal('0') and record.cost_source == 'provider_reported'


def test_unknown_retry_does_not_become_zero_or_complete_total():
    total = reader._sum_reader_llm_usage(reader.ReaderLlmUsage(None, 4, None),
                                        reader.ReaderLlmUsage(20, 6, Decimal('.01')))
    assert total.input_tokens is None
    assert total.output_tokens == 10
    assert total.estimated_cost_usd is None


def test_failure_persistence_keeps_tokens_when_cost_is_unknown():
    from types import SimpleNamespace
    from app.services.ai import reader_agent_session_service as session
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(rowcount=1)
    asyncio.run(session.mark_reader_llm_decision_failed(
        db, llm_decision_id=123, error_message='invalid decision',
        usage=reader.ReaderLlmUsage(18, 42, None)))
    params = db.execute.await_args.args[1]
    assert (params['input_tokens'], params['output_tokens']) == (18, 42)
    assert params['estimated_cost_usd'] is None
