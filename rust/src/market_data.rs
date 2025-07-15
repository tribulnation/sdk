use chrono::NaiveDateTime;

use crate::errors::UnauthedError;

pub struct BookEntry {
  pub amount: String,
  pub price: String,
}

pub struct OrderBook {
  pub asks: Vec<BookEntry>,
  pub bids: Vec<BookEntry>,
}

pub struct Trade {
  pub price: String,
  pub quantity: String,
  pub time: NaiveDateTime,
  pub buyer_maker: bool,
}

pub struct AggTradeParams<'a> {
  pub limit: Option<usize>,
  pub start: Option<NaiveDateTime>,
  pub start_id: Option<&'a str>,
  pub end: Option<NaiveDateTime>,
}

impl<'a> Default for AggTradeParams<'a> {
  fn default() -> Self {
    Self {
      limit: None,
      start: None,
      start_id: None,
      end: None,
    }
  }
}

#[async_trait::async_trait]
pub trait MarketData {
  async fn order_book(&self, symbol: &str, limit: Option<usize>) -> Result<OrderBook, UnauthedError>;
  /// Recent trades, sorted by increasing time (recent last).
  async fn trades(&self, symbol: &str, limit: Option<usize>) -> Result<Vec<Trade>, UnauthedError>;
  /// Aggregate trades, sorted by increasing time (recent last).
  async fn agg_trades(&self, symbol: &str, params: AggTradeParams) -> Result<Vec<Trade>, UnauthedError>;
}