"""Offline CLI and publication gates reject absent or mismatched evidence."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner
import yaml

from sdk_dev.cli.results import app, required_venues, select_account
from sdk_dev.cli import results
from sdk_dev.repo import repo_root
from tribulnation.sdk import MarketSDK
from tribulnation.sdk.impl.accounts import Binance, Hyperliquid


def test_account_selection_does_not_match_substrings():
  """Use configured aliases without requiring unrelated credentials."""
  sdk = MarketSDK(accounts={'trade': Binance(), 'other': Hyperliquid(public=True)})
  assert select_account(sdk, 'binance', None) == 'trade'
  with pytest.raises(ValueError, match='does not match'):
    select_account(sdk, 'binance', 'other')
  with pytest.raises(ValueError):
    select_account(sdk, 'bina', None)


def test_ambiguous_account_and_testnet_do_not_attest_mainnet():
  """No arbitrary first account, or testnet substitution, can become release evidence."""
  sdk = MarketSDK(
    accounts={
      'one': Binance(),
      'two': Binance(),
      'test': Hyperliquid(venue='hyperliquid_testnet', public=True),
    }
  )
  with pytest.raises(ValueError, match='select one explicitly'):
    select_account(sdk, 'binance', None)
  assert select_account(sdk, 'binance', 'two') == 'two'
  with pytest.raises(ValueError, match='does not match'):
    select_account(sdk, 'hyperliquid', 'test')


def test_release_requires_every_declared_implementation():
  """A core report cannot stand in for the implementations it routes to."""
  root = repo_root()
  venues = required_venues(root, 'sdk')
  assert {'binance', 'coinbase', 'dydx', 'hyperliquid', 'mexc'} <= set(venues)
  assert required_venues(root, 'binance') == ['binance']
  for venue in ('ethereum', 'kucoin', 'deribit'):
    assert venue in venues
    assert required_venues(root, venue) == [venue]
  with pytest.raises(ValueError, match='No consistency release-evidence policy'):
    required_venues(root, 'unknown')


def test_release_cli_rejects_failed_report(monkeypatch: pytest.MonkeyPatch):
  """The release command must propagate provenance or inventory failures."""
  check = Mock(side_effect=ValueError('missing required checks'))
  monkeypatch.setattr(results, 'verify_one', check)
  result = CliRunner().invoke(
    app, ['release', 'binance', '--catalogue', 'catalogue/data']
  )
  assert result.exit_code == 1 and 'Release blocked' in result.output
  assert check.call_args.kwargs['venue'] == 'binance'


def test_release_workflow_verifies_exact_candidate_before_publish():
  """A newer main commit or bypassed PR check cannot bypass the publication gate."""
  path = repo_root() / '.github/workflows/release.yml'
  workflow = yaml.safe_load(path.read_text())
  jobs = workflow['jobs']
  for job in ('check', 'release'):
    checkout = jobs[job]['steps'][0]
    assert (
      checkout['with']['ref'] == '${{ github.event.pull_request.merge_commit_sha }}'
    )
  steps = jobs['release']['steps']
  verify = next(
    i
    for i, step in enumerate(steps)
    if 'sdk-dev results release' in step.get('run', '')
  )
  publish = next(
    i
    for i, step in enumerate(steps)
    if step.get('uses', '').startswith('pypa/gh-action-pypi-publish')
  )
  assert verify < publish


def test_release_pr_has_offline_evidence_job():
  """Exchange credentials are unnecessary in the PR's evidence validation job."""
  path = repo_root() / '.github/workflows/check.yml'
  job = yaml.safe_load(path.read_text())['jobs']['release_evidence']
  assert "startsWith(github.head_ref, 'release/')" in job['if']
  assert any('sdk-dev results release' in step.get('run', '') for step in job['steps'])
  assert 'secrets.' not in str(job)
