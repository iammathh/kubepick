# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- `kubepick add` shows the name each added cluster got. Choosing an added cluster again asks whether to add it again, to refresh
  it or give it another name.
- `naming.strip`: words to cut out of cluster names when proposing a name, for example `prod-euc1-payments-api-eks` becomes
  `payments-api`. An environment word that is cut out is kept as the capitalised `env`. Empty by default.
- `naming.remove_dashes`: remove the dashes inside a label made from the cluster name, `payments-api` becomes `paymentsapi`.
  Off by default.
- `naming.lowercase`: make a label made from the cluster name lowercase. Off by default.
- `kubepick rename [OLD NEW]` gives an added context another name without contacting the cloud, and suggests the name your
  naming rules would give.

### Changed
- `kubepick login` without arguments asks which clouds to log in to instead of logging in to all of them. `--all` keeps the old behaviour.
- Clouds whose CLI is not installed are listed in the login picker, marked with a link to where to get the CLI, and `sync` and `login` print the same link when they skip one.

## [0.1.0] - 2026-10-16

First release.

### Added
- `kubepick sync`, `add`, `rm`, `login` and `init`.
- Scanning of AWS (EKS), Azure (AKS) and GCP (GKE) clusters.
- Proposed context names from a configurable template and label rules.
- Configuration file for everything specific to a setup: login commands, role preference, regions,
  subscriptions, projects and naming rules.
- Remembering the AWS regions that have clusters after a full scan, `--regions` and `--all-regions`.
