# Marketplace screenshots

The screenshots for the JetBrains Marketplace listing are generated, not captured by hand:

| File | Shows |
|---|---|
| `01-overview.png` | The arc42 tool window beside the document, grouped by arc42 section |
| `02-links.png` | A decision with the links written at it (`→`) and the links into it (`←`) |
| `03-group-by-kind.png` | The elements grouped by kind |
| `04-triggers.png` | A decision's revisit subscriptions and history |
| `05-problems.png` | A broken link target reported while the document is still unsaved (rule L3) |

## Regenerating them

From `implementations/intellij-plugin`, on Linux with Xvfb:

```bash
timeout 600 xvfb-run -a -s "-screen 0 1920x1080x24" ./gradlew runIdeForScreenshots
```

The outer `timeout` covers a dialog that blocks startup before the driver runs. Add `-PplatformLocalPath=/path/to/ide` to use an installed IDE of branch 253 instead of downloading IntelliJ IDEA. The shots then show that IDE's extras, such as PyCharm's "Start Free Trial" button, its Python interpreter, and its Python tool windows in the side bar.

The task:

1. Copies `extensions/triggers/EN/example.adoc` into a scratch project under `build/screenshot-project/`.
2. Starts the IDE on that project, with the plugin and the development-only [screenshot driver](../screenshot-driver).
3. The driver sets the Light theme and a 1280 × 800 window, and hides the status bar. It then arranges the tool window for each screenshot, writes the screenshots into this directory, and exits the IDE.

If the driver fails, it writes `failure.png` and the IDE exits with 1. Look for `[screenshots]` lines in the output to see which step failed.

## Uploading them

The Marketplace doesn't take screenshots from the plugin build. Upload them under **Media** on the plugin's page at <https://plugins.jetbrains.com>.
