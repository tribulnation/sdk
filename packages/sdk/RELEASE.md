# tribulnation-sdk 2.1.0 release candidate

Register KuCoin's credential-free public Market in MarketSDK. The KuCoin extra
now requires tribulnation-kucoin >=0.3.0, which adds Classic spot and linear
perpetual data with native exchange IDs `spot` and `perp`.

Publish core first, then KuCoin 0.3.0. The extra becomes installable once the
implementation is published; consumers should adopt the pair together.
Private Wallet/Earn/Report behavior is unchanged by this core registration.

Publication requires fresh all-venue read-suite and applicable Market consistency
evidence against the merged Catalogue. Terminal rollout is handled separately
by the owner; this release does not enable Terminal collection or deployment.
