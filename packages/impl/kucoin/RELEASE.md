# tribulnation-kucoin 0.2.1

Translate native client acquisition and cleanup failures through managed resource
adapters. Entry and exit policies remain independent; this release adds no automatic
resource retries. Decorated calls inside the lifecycle retain context middleware.

Requires tribulnation-sdk >=2.0.2. Publish after the SDK patch release.

The release workflow requires fresh passing read-only qualification for this exact
version and dependency floor before publication.
