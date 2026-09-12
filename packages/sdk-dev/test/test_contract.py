"""Regression checks for linear, complete per-venue documentation examples."""

import pytest

from sdk_dev.contract import (
  ContractCatalogue,
  ContractExample,
  ContractMethod,
  render_method,
)


def method(venues: list[str]) -> ContractMethod:
  """Build an example that exposes accidental multi-venue template contexts."""
  return ContractMethod(
    example=ContractExample(
      accountVenues=venues[:2],
      constants={venue: {'value': index} for index, venue in enumerate(venues)},
      callTemplate='print("{{ accounts | join(",") }}")',
      resultTemplate='{{ constants[accounts[0]].value }}',
    ),
    catalogue=ContractCatalogue(
      callTemplate='translate("{{ accounts[0] }}")',
      resultTemplate='{{ catalogue[accounts[0]] }}',
    ),
  )


def test_examples_scale_linearly_and_keep_standalone_scripts():
  """Twelve venues produce twelve complete examples, never 4095 combinations."""
  venues = [f'venue{index}' for index in range(12)]
  examples = render_method(
    method(venues),
    preamble='import sdk',
    universe=venues,
    catalogue={venue: 'translated' for venue in venues},
  )
  assert list(examples) == venues
  for index, venue in enumerate(venues):
    assert examples[venue]['call'] == f'import sdk\n\nprint("{venue}")'
    assert examples[venue]['result'] == [str(index)]
    assert examples[venue]['catalogueCall'] == f'translate("{venue}")'
    assert examples[venue]['catalogueResult'] == 'translated'


def test_missing_example_constants_fail_instead_of_hiding_venues():
  """Even templates not accessing constants must cover all supported venues."""
  example = method(['first'])
  with pytest.raises(ValueError, match='missing example constants.*second'):
    render_method(example, preamble='', universe=['first', 'second'], catalogue={})


def test_default_selection_cannot_include_an_unsupported_venue():
  """Installation defaults never select an ineligible venue."""
  with pytest.raises(ValueError, match='unsupported default example venues.*second'):
    render_method(
      method(['first', 'second']), preamble='', universe=['first'], catalogue={}
    )


def test_no_supported_venues_produces_no_examples():
  """An entirely unsupported method has no fabricated examples."""
  assert render_method(method([]), preamble='', universe=[], catalogue={}) == {}
