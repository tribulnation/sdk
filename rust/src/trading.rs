use crate::types::{Side, TimeInForce};
use crate::errors::AuthedError;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LimitOrder {
  pub side: Side,
  pub qty: String,
  pub price: String,
  pub time_in_force: Option<TimeInForce>,
  pub post_only: Option<bool>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MarketOrder {
  pub side: Side,
  pub qty: String,
  pub time_in_force: Option<TimeInForce>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Order {
  Limit(LimitOrder),
  Market(MarketOrder),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PlaceOrderResponse {
  pub order_id: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum OrderStatus {
  New,
  PartiallyFilled,
  Filled,
  Canceled,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct QueryOrderResponse {
  pub status: OrderStatus,
  pub executed_qty: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Balance {
  pub free: String,
  pub locked: String,
}

#[async_trait::async_trait]
pub trait Trading {
  async fn place_order(&self, symbol: &str, order: Order) -> Result<PlaceOrderResponse, AuthedError>;
  async fn cancel_order(&self, symbol: &str, order_id: &str) -> Result<(), AuthedError>;
  async fn cancel_all_orders(&self, symbol: &str) -> Result<(), AuthedError>;
  async fn query_order(&self, symbol: &str, order_id: &str) -> Result<QueryOrderResponse, AuthedError>;
  async fn get_balance(&self, currency: &str) -> Result<Balance, AuthedError>;
} 
