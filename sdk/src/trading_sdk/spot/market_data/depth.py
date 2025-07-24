from typing_extensions import Protocol, TypedDict 

class BookEntry(TypedDict):
  price: str
  quantity: str

class OrderBook(TypedDict):
  bids: list[BookEntry]
  asks: list[BookEntry]

class Depth(Protocol):
  async def depth(self, symbol: str, *, limit: int | None = None) -> OrderBook:
    """Get the order book for a given symbol.
    
    - `symbol`: The symbol being traded, e.g. `BTCUSDT`.
    - `limit`: The maximum number of bids/asks to return.
    """
    ...