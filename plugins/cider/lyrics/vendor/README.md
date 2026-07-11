# Vendored Cider PluginKit

`ciderapp-pluginkit-1.0.0-pre.1-e7bcba04.tgz` contains the prebuilt npm package
for `@ciderapp/pluginkit` from Cider's `cider-4` branch at commit
`e7bcba04aeb342470df740878857e4d1805cb48b`.

The upstream package is not published to npm. Installing it directly from GitHub
runs its `prepack` build on every clean install, and that build is not reproducible
in CI because its own package manifest and lockfile differ. Keeping the small
prebuilt package here makes Kotonoha's frozen install deterministic. The archive
includes PluginKit's MIT license. Its package manifest is patched to point the
root and mDNS type exports at the generated `.d.mts` declarations; upstream's
`.d.ts` files at this commit are empty.

SHA-256:

```text
688a704ddbda8125ac4a68db501708e04ec30848c8a1604cb1e101fd66f86819
```
