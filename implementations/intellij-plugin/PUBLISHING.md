# Publishing to JetBrains Marketplace

## Secrets

None of these belong in the repository. Set them in the shell, or put the token in `~/.gradle/gradle.properties`.

| What | Locally | GitHub secret |
|---|---|---|
| Marketplace token ([generate](https://plugins.jetbrains.com/author/me/tokens)) | `ORG_GRADLE_PROJECT_intellijPlatformPublishingToken`, or `intellijPlatformPublishingToken=` in `~/.gradle/gradle.properties` | `JETBRAINS_MARKETPLACE_TOKEN` |
| Signing certificate chain (PEM text) | `CERTIFICATE_CHAIN` | `PLUGIN_SIGNING_CERTIFICATE_CHAIN` |
| Signing private key (PEM text) | `PRIVATE_KEY` | `PLUGIN_SIGNING_PRIVATE_KEY` |
| Private key password | `PRIVATE_KEY_PASSWORD` | `PLUGIN_SIGNING_PASSWORD` |

Signing by the author is optional: the Marketplace signs every plugin as well. An IDE shows a warning when it installs a plugin without an author signature, so sign it. To create a key and a self-signed certificate, follow [Plugin Signing](https://plugins.jetbrains.com/docs/intellij/plugin-signing.html#generate-private-key):

```bash
openssl genpkey -aes-256-cbc -algorithm RSA -out private_encrypted.pem -pkeyopt rsa_keygen_bits:4096
openssl rsa -in private_encrypted.pem -out private.pem
openssl req -key private.pem -new -x509 -days 3650 -out chain.crt
export CERTIFICATE_CHAIN="$(cat chain.crt)" PRIVATE_KEY="$(cat private.pem)" PRIVATE_KEY_PASSWORD=...
```

Keep the key outside the repository and back it up: later versions must be signed with the same key.

## Checks

The commands below run from `implementations/intellij-plugin`. Add `-PplatformLocalPath=/path/to/ide` to build against an installed IDE of branch 253 instead of downloading one.

```bash
./gradlew verifyPluginStructure verifyPluginProjectConfiguration test buildPlugin
./gradlew verifyPlugin   # downloads the recommended IDEs to check compatibility against
```

## First release: upload by hand

The Marketplace accepts the first version of a plugin only through its website. `publishPlugin` works only after that.

1. `./gradlew signPlugin` writes `build/distributions/arc42ext-intellij-<version>-signed.zip`.
2. On <https://plugins.jetbrains.com/plugin/add>, upload that zip, and choose the license (Apache-2.0) and the tags.
3. Under **Media** on the plugin's admin page, upload the screenshots from `screenshots/` (see below).
4. JetBrains reviews the plugin, which usually takes 1–3 business days.

## Later releases

1. Raise `version` in `gradle.properties`, and add a `## [<version>]` section to `CHANGELOG.md`. The build copies that section into the change notes.
2. Commit, then tag the commit, e.g. `git tag v0.2.0 && git push origin v0.2.0`.
3. Either run the **Publish Plugin** workflow in GitHub Actions on the tag and choose a channel, or run `./gradlew publishPlugin` locally. To publish to a channel other than the default, add `-PpluginChannel=beta`.

## Screenshots

The Marketplace takes screenshots through the **Media** section of the admin page, not from the plugin build. They should be at least 1200 × 760. The plugin's own screenshots are generated, not captured by hand; see [screenshots/README.md](screenshots/README.md).

Regenerate them whenever the tool window changes, and upload them again.
