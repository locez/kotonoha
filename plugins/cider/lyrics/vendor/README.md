# Vendored Cider PluginKit

`ciderapp-pluginkit-1.0.0-pre.1-e7bcba04.tgz` contains the prebuilt npm package
for `@ciderapp/pluginkit` from Cider's `cider-4` branch at commit
`e7bcba04aeb342470df740878857e4d1805cb48b`.

The upstream package is not published to npm. Installing it directly from GitHub
runs its `prepack` build on every clean install, and that build is not reproducible
in CI because its own package manifest and lockfile differ. Keeping the small
prebuilt package here makes Kotonoha's frozen install deterministic. The archive
includes PluginKit's MIT license.

SHA-256:

```text
e9b661f9e2312987d35424b1e397a56b8767afeb5d86c6ca080e4163bbd1b476
```
