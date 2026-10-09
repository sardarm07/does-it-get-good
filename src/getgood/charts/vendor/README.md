# Vendored chart libraries

Chart pages load these from disk, so they work offline and need no build step. Each file
is copied byte for byte from its npm tarball, after checking the tarball against the
registry's SHA-512. Both libraries are ISC-licensed; their licences sit beside them.

| File | Package | Version | Tarball SHA-512 (npm integrity) |
| --- | --- | --- | --- |
| `d3.min.js` | `d3` | 7.9.0 | `sha512-e1U46jVP+w7Iut8Jt8ri1YsPOvFpg46k+K8TpCb0P+zjCkjkPnV7WzfDJzMHy1LnA+wj5pLT1wjO901gLXeEhA==` |
| `plot.umd.min.js` | `@observablehq/plot` | 0.6.17 | `sha512-/qaXP/7mc4MUS0s4cPPFASDRjtsWp85/TbfsciqDgU1HwYixbSbbytNuInD8AcTYC3xaxACgVX06agdfQy9W+g==` |

The files' own SHA-256s are in `getgood.charts.VENDORED`, and the tests check them.

To update one: download `https://registry.npmjs.org/<package>/-/<name>-<version>.tgz`,
compare its SHA-512 with `dist.integrity` from `https://registry.npmjs.org/<package>/<version>`,
copy the file from the tarball's `dist/`, and update this table and `VENDORED`.
