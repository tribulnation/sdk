# tribulnation-sdk 2.0.2

Add `ManagedResource` so venue implementations can apply independent exception
translation and retry policies to resource entry and cleanup.

SDK context-manager entry and exit no longer apply method middleware to the whole
lifecycle. Decorated calls made during acquisition and cleanup still receive the
active context's retries and logging. Ownership, rollback, reverse cleanup, and
suppression behavior are preserved.

Publish this SDK patch before the implementation patches that require it.
