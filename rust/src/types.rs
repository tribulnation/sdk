#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Side {
  Buy,
  Sell,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TimeInForce {
  GTC,
  IOC,
  FOK,
}
