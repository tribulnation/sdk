"""Subaccount labels shared by history and snapshots.

Hyperliquid splits an account into two economic compartments. History and
snapshots must spell them identically or nothing reconciles: the audit matches a
compartment's balance change against the observations attributed to it, and a
label present on only one side reads as a compartment that gained a balance from
nowhere. Defined once here, imported by both.
"""

UNIFIED = 'unified'
"""The main pool: spot balances and every perp dex's collateral."""

STAKING = 'staking'
"""Staked HYPE, delegated or undelegated. Cannot trade until undelegated."""
