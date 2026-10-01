# Synthetic Trivy native fixture

The Go helper is compiled only in the isolated test lab against the pinned Trivy module graph. It creates a single historic advisory and synthetic Debian package version boundary for verifier tests. It is not a public feed, never replaces production caches, and is not copied into runtime images. Run with one new, owned destination directory; generated database and metadata are fingerprinted before and after tests.
