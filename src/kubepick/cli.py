import argparse
import copy
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from kubepick import __version__
from kubepick.config import EXAMPLE_CONFIG, cache_dir, config_file, load_config, login_command
from kubepick.kubeconfig import (
	DEFAULT_KUBECONFIG,
	add_to_kubeconfig,
	load_kubeconfig,
	load_state,
	remove_from_kubeconfig,
	rename_in_kubeconfig,
	save_kubeconfig,
	save_state,
	state_path,
)
from kubepick.names import PREFIXES, propose_name, unique_name
from kubepick.scanners import CLOUDS, INSTALL_URLS
from kubepick.util import cluster_id, now

STALE_AFTER_DAYS = 7


### Saved list ###

def cache_file():
	return cache_dir() / "clusters.json"

def load_cache():
	try:
		return json.loads(cache_file().read_text())
	except (OSError, ValueError):
		return {'synced': {}, 'clusters': []}

def save_cache(cache):
	cache_file().parent.mkdir(parents=True, exist_ok=True)
	cache_file().write_text(json.dumps(cache, indent=1))

def interactive():
	return sys.stdin.isatty() and sys.stdout.isatty()

def missing_cli_message(cloud):
	return "{} CLI not installed, get it at {}".format(CLOUDS[cloud][0], INSTALL_URLS[cloud])

# Which AWS regions to scan: --regions, then --all-regions, then the configuration, then the regions remembered
# from the last full scan. An empty list means every region.
def regions_to_scan(config, cache, regions, all_regions):
	if regions:
		return regions
	if all_regions:
		return []
	return config['aws']['regions'] or cache.get('aws_regions') or []

# Scanning every region of every account is slow, but clusters usually live in a handful of them
def offer_to_remember(cache, clusters):
	found = sorted({c['region'] for c in clusters})
	if not found:
		return
	print("         clusters are in {} region(s): {}".format(len(found), ", ".join(found)))
	try:
		answer = input("         Scan only these regions from now on? [Y/n] ").strip().lower()
	except EOFError:
		print()
		return
	if answer in ("", "y", "yes"):
		cache['aws_regions'] = found
		print("         Remembered. `kubepick sync --all-regions` checks every region again.")

def sync(config, clouds, regions=None, all_regions=False):
	cache = load_cache()
	for cloud in clouds:
		prefix = PREFIXES[cloud]
		cli, scanner = CLOUDS[cloud]
		old = [c for c in cache['clusters'] if c['cloud'] == cloud]
		if shutil.which(cli) is None:
			print("{:<6} skipped, {}".format(prefix, missing_cli_message(cloud)))
			continue

		scan_config = config
		chosen = []
		if cloud == "aws":
			chosen = regions_to_scan(config, cache, regions, all_regions)
			scan_config = copy.deepcopy(config)
			scan_config['aws']['regions'] = chosen

		try:
			clusters = scanner(scan_config)
		except Exception as error:
			print("{:<6} failed, keeping the saved list ({} cluster(s)): {}".format(prefix, len(old), error))
			continue
		if clusters is None:
			# keep what we knew, so a logged out cloud doesn't empty the list
			print("{:<6} not logged in, keeping the saved list ({} cluster(s)). Run `kubepick login {}` to refresh it".format(prefix, len(old), cloud))
			continue

		known = {cluster_id(c) for c in old}
		new = [c for c in clusters if cluster_id(c) not in known]
		cache['clusters'] = [c for c in cache['clusters'] if c['cloud'] != cloud] + clusters
		cache['synced'][cloud] = now()
		print("{:<6} {} cluster(s) in {} account(s){}".format(prefix, len(clusters), len({c['account'] for c in clusters}),
			", {} new".format(len(new)) if old and new else ""))
		for c in new if old else []:
			print("         + {} / {}".format(c['account'], c['name']))
		if cloud == "aws" and chosen:
			print("         scanned {}; `kubepick sync --all-regions` checks every region".format(
				"{} regions".format(len(chosen)) if len(chosen) > 6 else ", ".join(chosen)))
		elif cloud == "aws" and interactive():
			offer_to_remember(cache, clusters)
	save_cache(cache)
	print("\nRun `kubepick add` to choose which ones to add to your kubeconfig.")


### Login ###

def login(config, clouds):
	for cloud in clouds:
		prefix = PREFIXES[cloud]
		if shutil.which(CLOUDS[cloud][0]) is None:
			print("{:<6} skipped, {}".format(prefix, missing_cli_message(cloud)))
			continue
		command = login_command(cloud, config)
		if command is None:
			print("{:<6} set `{}.login` in {} (no single sso-session found in ~/.aws/config to guess it from)".format(prefix, cloud, config_file()))
			continue
		if shutil.which(command[0]) is None:
			print("{:<6} skipped, {} not found".format(prefix, command[0]))
			continue
		print("{:<6} {}".format(prefix, " ".join(command)))
		subprocess.run(command)

# Ask which clouds to log in to, so a bare `kubepick login` doesn't open a browser for each of them
def pick_clouds(config):
	if not interactive():
		sys.exit("kubepick: say which cloud to log in to: kubepick login aws|azure|gcp, or kubepick login --all")
	missing = [cloud for cloud, (cli, _) in CLOUDS.items() if shutil.which(cli) is None]
	if len(missing) == len(CLOUDS):
		print("No cloud CLI found. Install at least one of them:")
		for cloud in CLOUDS:
			print("  {:<6} {}".format(PREFIXES[cloud], INSTALL_URLS[cloud]))
		return []

	# every cloud is listed, so it is clear what else is possible and what is missing for it
	lines = []
	for cloud in CLOUDS:
		if cloud in missing:
			lines.append(("✗ {:<6} {}".format(PREFIXES[cloud], missing_cli_message(cloud)), cloud))
		else:
			command = " ".join(login_command(cloud, config) or ["(set {}.login in the configuration)".format(cloud)])
			lines.append(("  {:<6} {}".format(PREFIXES[cloud], command[:70]), cloud))
	return choose(lines, "Which cloud do you want to log in to?   Tab: select several   Enter: confirm   ✗ = CLI not installed")


### Selection ###

# lines: [(text shown, key returned)]. Returns the keys of the chosen lines (several with Tab).
def choose(lines, header, pattern=None):
	if pattern is not None:
		return [key for text, key in lines if re.search(pattern, text, re.IGNORECASE)]
	if shutil.which("fzf") is None:
		sys.exit("fzf is required for selecting, see https://github.com/junegunn/fzf, or pass --match REGEX")
	result = subprocess.run(["fzf", "--multi", "--reverse", "--height=80%", "--delimiter=\t", "--with-nth=1", "--header={}".format(header)],
		input="\n".join("{}\t{}".format(text, key) for text, key in lines), stdout=subprocess.PIPE, text=True)
	return [line.split("\t")[-1] for line in result.stdout.splitlines()]

def ask_name(default, taken):
	while True:
		name = input("  Name [{}]: ".format(default)).strip() or default
		if name in taken:
			print("  '{}' already exists".format(name))
			continue
		return name

def confirm(prompt):
	try:
		return input(prompt).strip().lower() in ("y", "yes")
	except EOFError:
		print()
		return False


### Add and remove ###

def add(config, kubeconfig_path, pattern, assume_yes):
	cache = load_cache()
	if len(cache['clusters']) == 0:
		print("No saved cluster list yet, scanning first..\n")
		sync(config, list(CLOUDS))
		cache = load_cache()

	stale = [PREFIXES[c] for c, synced in cache['synced'].items() if (datetime.now(timezone.utc) - datetime.fromisoformat(synced)).days >= STALE_AFTER_DAYS]
	if stale:
		print("The list of {} is older than {} days, run `kubepick sync` to refresh it.\n".format("/".join(stale), STALE_AFTER_DAYS))

	state_file = state_path(kubeconfig_path)
	state = load_state(state_file)
	added = {cid: name for name, cid in state.items()}

	clusters = {cluster_id(c): c for c in cache['clusters']}
	lines = [
		("{} {:<6} {:<48} {:<12} {:<38} {:<20} {}".format("✓" if cid in added else " ", PREFIXES[c['cloud']], c['account'],
			c.get('account_id') or "", c['name'], c['region'], "→ {}".format(added[cid]) if cid in added else "").rstrip(), cid)
		for cid, c in sorted(clusters.items(), key=lambda i: (i[1]['cloud'], i[1]['account'].lower(), i[1]['name']))
	]
	chosen = choose(lines, "Tab: select several   Enter: confirm   ✓ → name = already added, choose it again to refresh or rename", pattern)
	if len(chosen) == 0:
		print("Nothing selected")
		return

	data = load_kubeconfig(kubeconfig_path)
	taken = {c['name'] for c in data['contexts']}
	count = 0
	for cid in chosen:
		cluster = clusters[cid]
		existing = added.get(cid)
		print("\n{} / {} ({})".format(cluster['account'], cluster['name'], cluster['region']))
		if existing:
			if assume_yes:
				print("  already added as {}".format(existing))
				continue
			if not confirm("  already added as {}. Add it again, to refresh it or give it another name? [y/N] ".format(existing)):
				print("  keeping {}".format(existing))
				continue
			default, others = existing, taken - {existing}
		else:
			default, others = unique_name(propose_name(cluster, config['naming']), cluster, taken), taken
		name = default if assume_yes else ask_name(default, others)
		try:
			add_to_kubeconfig(data, cluster, name)
		except Exception as error:
			print("  failed: {}".format(error))
			continue
		# a new name replaces the old context, and keeps being the current one if it was
		if existing and name != existing:
			was_current = data.get('current-context') == existing
			remove_from_kubeconfig(data, existing)
			state.pop(existing, None)
			taken.discard(existing)
			if was_current:
				data['current-context'] = name
		taken.add(name)
		state[name] = cid
		count += 1
		print("  {} as {}".format(("renamed" if name != existing else "refreshed") if existing else "added", name))

	if count > 0:
		save_kubeconfig(kubeconfig_path, data)
		save_state(state_file, state)
		print("\nAdded or updated {} cluster(s) in {}".format(count, kubeconfig_path))

def remove(kubeconfig_path, pattern, assume_yes):
	data = load_kubeconfig(kubeconfig_path)
	state_file = state_path(kubeconfig_path)
	state = load_state(state_file)
	if len(data['contexts']) == 0:
		print("No contexts in {}".format(kubeconfig_path))
		return

	lines = [
		("{:<55} {}".format(c['name'], "added by kubepick" if c['name'] in state else ""), c['name'])
		for c in sorted(data['contexts'], key=lambda c: c['name'].lower())
	]
	chosen = choose(lines, "Tab: select several   Enter: confirm", pattern)
	if len(chosen) == 0:
		print("Nothing selected")
		return

	print("Remove from {}:".format(kubeconfig_path))
	for name in chosen:
		print("  - {}{}".format(name, "" if name in state else "   (not added by kubepick)"))
	if not assume_yes and input("Remove {} context(s)? [y/N] ".format(len(chosen))).strip().lower() != "y":
		print("Cancelled")
		return

	for name in chosen:
		remove_from_kubeconfig(data, name)
		state.pop(name, None)
	save_kubeconfig(kubeconfig_path, data)
	save_state(state_file, state)
	print("Removed {} context(s)".format(len(chosen)))


def rename(config, kubeconfig_path, old, new):
	data = load_kubeconfig(kubeconfig_path)
	state_file = state_path(kubeconfig_path)
	state = load_state(state_file)
	names = {c['name'] for c in data['contexts']}
	clusters = {cluster_id(c): c for c in load_cache()['clusters']}

	if old:
		chosen = [old]
	else:
		if len(names) == 0:
			print("No contexts in {}".format(kubeconfig_path))
			return
		lines = [
			("{:<55} {}".format(c['name'], "added by kubepick" if c['name'] in state else ""), c['name'])
			for c in sorted(data['contexts'], key=lambda c: c['name'].lower())
		]
		chosen = choose(lines, "Tab: select several   Enter: confirm   Which contexts do you want to rename?")
		if len(chosen) == 0:
			print("Nothing selected")
			return

	count = 0
	for name in chosen:
		if name not in names:
			sys.exit("kubepick: no context named {}".format(name))
		if not old:
			print("\n{}".format(name))
			cluster = clusters.get(state.get(name))
			suggestion = propose_name(cluster, config['naming']) if cluster else None
			if suggestion and suggestion != name and suggestion not in names:
				print("  your naming rules suggest {}".format(suggestion))
			new = ask_name(name, names - {name})
		if new == name:
			continue
		if new in names:
			sys.exit("kubepick: a context named {} already exists".format(new))
		rename_in_kubeconfig(data, name, new)
		if name in state:
			state[new] = state.pop(name)
		names.discard(name)
		names.add(new)
		count += 1
		print("  {} -> {}".format(name, new))

	if count == 0:
		print("Nothing renamed")
		return
	save_kubeconfig(kubeconfig_path, data)
	save_state(state_file, state)
	print("Renamed {} context(s) in {}".format(count, kubeconfig_path))


### Command line ###

def init():
	path = config_file()
	if path.exists():
		print("{} already exists".format(path))
		return
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(EXAMPLE_CONFIG)
	print("Wrote an example configuration to {}".format(path))

def build_parser():
	parser = argparse.ArgumentParser(prog="kubepick", description="Choose which AWS, Azure and GCP clusters go into your kubeconfig.")
	parser.add_argument("--version", action="version", version="kubepick {}".format(__version__))
	commands = parser.add_subparsers(dest="command")

	for name, help_text in [("sync", "scan the clouds and save the list of clusters"), ("login", "log in to the clouds")]:
		command = commands.add_parser(name, help=help_text)
		command.add_argument("clouds", nargs="*", help="only these clouds: {} (default: all)".format(", ".join(CLOUDS)))
		if name == "login":
			command.add_argument("--all", action="store_true", help="log in to every cloud without asking")
		if name == "sync":
			command.add_argument("--regions", metavar="LIST", type=lambda value: [r for r in value.split(",") if r],
				help="scan only these AWS regions, comma separated, this time")
			command.add_argument("--all-regions", action="store_true", help="scan every AWS region, ignoring the configured and remembered ones")

	for name, help_text in [("add", "choose clusters from the list and add them to the kubeconfig (default command)"),
			("rm", "choose contexts and remove them from the kubeconfig")]:
		command = commands.add_parser(name, help=help_text)
		command.add_argument("--kubeconfig", type=str, default=str(DEFAULT_KUBECONFIG), help="kubeconfig to change (default: ~/.kube/config)")
		command.add_argument("--match", metavar="REGEX", help="select every entry matching the regex instead of asking")
		command.add_argument("--yes", action="store_true", help="don't ask for names or confirmation, use the proposed names")

	rename_parser = commands.add_parser("rename", help="give a context another name, without contacting any cloud")
	rename_parser.add_argument("old", nargs="?", help="current name of the context, leave out to choose from a list")
	rename_parser.add_argument("new", nargs="?", help="new name")
	rename_parser.add_argument("--kubeconfig", type=str, default=str(DEFAULT_KUBECONFIG), help="kubeconfig to change (default: ~/.kube/config)")

	commands.add_parser("init", help="write an example configuration file")
	return parser

def main(argv=None):
	parser = build_parser()
	args = parser.parse_args(argv)
	if args.command is None:
		args = parser.parse_args(["add"])

	if args.command == "init":
		return init()

	if args.command in ("sync", "login"):
		unknown = [c for c in args.clouds if c not in CLOUDS]
		if unknown:
			parser.error("unknown cloud: {} (choose from {})".format(", ".join(unknown), ", ".join(CLOUDS)))

	try:
		config = load_config()
	except ValueError as error:
		sys.exit("kubepick: invalid configuration in {}: {}".format(config_file(), error))

	try:
		if args.command == "sync":
			sync(config, args.clouds or list(CLOUDS), args.regions, args.all_regions)
		elif args.command == "login":
			clouds = args.clouds or (list(CLOUDS) if args.all else pick_clouds(config))
			if clouds:
				login(config, clouds)
			else:
				print("Nothing selected")
		else:
			kubeconfig = Path(args.kubeconfig).expanduser()
			if args.command == "rm":
				remove(kubeconfig, args.match, args.yes)
			elif args.command == "rename":
				if bool(args.old) != bool(args.new):
					parser.error("give both the current and the new name, or neither to choose from a list")
				rename(config, kubeconfig, args.old, args.new)
			else:
				add(config, kubeconfig, args.match, args.yes)
	except (KeyboardInterrupt, EOFError):
		print()
		sys.exit(130)
