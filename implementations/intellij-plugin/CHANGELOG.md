# Changelog

All notable changes to the Extensions for arc42 IntelliJ plugin will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-06

### Added
- Initial release
- arc42 tool window for browsing architecture documents written in AsciiDoc
- Support for links extension: typed links between elements (decisions, requirements, inputs, stakeholder roles)
- Support for triggers extension: event-driven decision revisits
- Link visualization showing owned links and inverse links for each element
- Real-time validation of links rules (L1, L3-L8, B1)
- Dual view modes: group elements by arc42 section or by element kind
- Live updates as AsciiDoc files change (debounced, 300ms)
- Navigation support: double-click or Enter to jump to element source locations
- Follow `include::` directives across multiple files
- Read-only interface: documents remain the source of truth
- Works during IDE indexing (DumbAware service)

### Limitations
- Triggers rules T1-T17 validation not yet implemented
- Historical status view for revisits not yet supported
- Baseline management UI not available

[Unreleased]: https://github.com/avrilfanomar/extensions-for-arc42/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/avrilfanomar/extensions-for-arc42/releases/tag/v0.1.0
