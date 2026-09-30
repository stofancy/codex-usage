"""End-to-end throughput from complete turns; synthetic logs only."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from codex_usage import cli, stats
from codex_usage.parser import Session, collect, parse_rollout, to_local
from codex_usage.render import tables

SID = '00000000-0000-0000-0000-000000000001'
BASE = datetime(2026, 9, 30, tzinfo=timezone.utc)


def event(second, kind, payload):
    return json.dumps({'timestamp': (BASE + timedelta(seconds=second)).isoformat(),
                       'type': kind, 'payload': payload})


def turn(start=0, output=100, seconds=10, model='m', complete=True):
    return [
        event(start, 'event_msg', {'type': 'task_started', 'turn_id': str(start)}),
        event(start, 'turn_context', {'model': model}),
        event(start + seconds - 1, 'event_msg', {
            'type': 'token_count', 'info': {'last_token_usage': {
                'input_tokens': 1000, 'output_tokens': output}}}),
        *([event(start + seconds, 'event_msg', {
            'type': 'task_complete', 'turn_id': str(start)})] if complete else []),
    ]


def write(tmp_path, lines, suffix=''):
    path = tmp_path / f'rollout-2026-09-30T00-00-00-{SID}{suffix}.jsonl'
    path.write_text('\n'.join(lines) + '\n')
    return str(path)


def test_weighted_tps_and_untimed_output(tmp_path):
    rec = parse_rollout(write(tmp_path, turn() + turn(20, 900, 30)
                              + turn(120, 5000, complete=False)))
    assert stats.rec_tokens(rec)[2] == 6000
    assert stats.rec_timing(rec) == (1000, 40)
    assert stats.rec_tps(rec) == 25  # Average of rates would give the wrong answer.
    agg = stats.aggregate_models([rec], {})['m']
    assert stats.tps(*agg[7:9]) == 25


@pytest.mark.parametrize('start,end', [(1, 11), (0, 9)])
def test_window_clipping_keeps_tokens_but_excludes_partial_timing(tmp_path, start, end):
    rec = parse_rollout(write(tmp_path, turn()),
                        (to_local(BASE + timedelta(seconds=start)),
                         to_local(BASE + timedelta(seconds=end))))
    assert stats.rec_tokens(rec)[2] == 100
    assert stats.rec_tps(rec) is None


def test_duplicate_snapshot_does_not_inflate_tps(tmp_path):
    lines = turn()
    info = {'last_token_usage': {'input_tokens': 1000, 'output_tokens': 100},
            'total_token_usage': {'input_tokens': 1000, 'output_tokens': 100}}
    lines[2] = event(8, 'event_msg', {'type': 'token_count', 'info': info})
    lines.insert(3, event(9, 'event_msg', {'type': 'token_count', 'info': info}))
    rec = parse_rollout(write(tmp_path, lines))
    assert stats.rec_tps(rec) == 10


def test_multimodel_turn_unknown_and_model_filter(tmp_path):
    lines = turn()
    lines.insert(3, event(9, 'turn_context', {'model': 'other'}))
    lines.insert(4, event(9, 'event_msg', {'type': 'token_count', 'info': {
        'last_token_usage': {'input_tokens': 1000, 'output_tokens': 100}}}))
    rec = parse_rollout(write(tmp_path, lines + turn(20, 200, 10)))
    assert stats.rec_tps(rec) == 20
    assert stats.rec_tps(rec, 'other') is None
    stats.apply_filters([rec], model='other')
    assert stats.rec_tps(rec) is None


def test_pagination_merges_timing(tmp_path):
    write(tmp_path, turn())
    write(tmp_path, turn(20, 200, 10), '_00000000-0000-0000-0000-000000000002')
    recs = collect(str(tmp_path), to_local(BASE), to_local(BASE + timedelta(days=1)))
    assert len(recs) == 1
    assert stats.rec_tps(recs[0]) == 15


@pytest.mark.parametrize('view', ['flat', 'models', 'day', 'day_model', 'family', 'family_model'])
def test_views_and_json_use_same_weighted_tps(tmp_path, capsys, view):
    rec = parse_rollout(write(tmp_path, turn()))
    unknown = Session(file='f', sid='unknown', uuids=[], models={'m': [1000, 0, 900, 0, 1]})
    recs = [rec, unknown]
    if view == 'flat':
        tables.view_flat(recs, {})
    elif view == 'models':
        tables.view_models(recs, {})
    elif view.startswith('day'):
        tables.view_by_day(recs, {}, view == 'day_model')
    else:
        tables.view_families(recs, {}, view == 'family_model', False)
    output = capsys.readouterr().out
    assert 'TPS' in output and '10.0' in output
    cli._emit_json(recs, {})
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert rows[0]['tps'] == rows[0]['models']['m']['tps'] == 10
    assert rows[1]['tps'] is None


@pytest.mark.parametrize('change', ['mismatched_id', 'zero_duration', 'missing_start'])
def test_invalid_turn_timing_is_unknown(tmp_path, change):
    lines = turn()
    if change == 'mismatched_id':
        lines[-1] = event(10, 'event_msg', {'type': 'task_complete', 'turn_id': 'other'})
    elif change == 'zero_duration':
        lines[-1] = event(0, 'event_msg', {'type': 'task_complete', 'turn_id': '0'})
    else:
        lines = lines[1:]
    rec = parse_rollout(write(tmp_path, lines))
    assert stats.rec_tokens(rec)[2] == 100
    assert stats.rec_tps(rec) is None
