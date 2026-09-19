# %% [markdown]
# # Deribit Market prototype handoff
#
# The qualified public prototype is now in [market/public.py](market/public.py).
# Run it through `sdk-dev poc run`; it never opens private credentials or places orders.
#
# The previous exploratory notebook mixed public mainnet and private testnet calls.
# It used obsolete Rules fee fields, guessed spot fee denomination, passed inverse
# notional quantities as base units and constructed a next-funding timestamp locally.
# Its historical “Full” coverage claims did not establish current SDK compatibility.
# It has been retired rather than promoted. Git history retains the private experiments;
# private Market methods and trading remain unsupported by the package.
