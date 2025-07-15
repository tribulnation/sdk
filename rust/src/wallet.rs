use crate::errors::AuthedError;

pub struct WithdrawalMethod {
  pub network: String,
  pub fee: String,
  pub min_amount: Option<String>,
}

#[async_trait::async_trait]
pub trait Wallet {
  async fn withdraw(&self, currency: &str, address: &str, amount: String, network: Option<&str>) -> Result<(), AuthedError>;
  async fn get_deposit_address(&self, currency: &str, network: Option<&str>) -> Result<String, AuthedError>;
  async fn get_withdrawal_methods(&self, currency: &str) -> Result<Vec<WithdrawalMethod>, AuthedError>;
} 