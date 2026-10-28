import pytest
import yaml

from kubepick import cli, kubeconfig
from kubepick.config import default_config
from kubepick.scanners import LoggedOut

AWS_CLUSTERS = [
	{'cloud': "aws", 'account': "team-prod", 'profile': "team-prod/Admin", 'region': "eu-central-1", 'name': "web"},
	{'cloud': "aws", 'account': "team-dev", 'profile': "team-dev/Admin", 'region': "eu-west-1", 'name': "api"},
]

def use_scanner(monkeypatch, cloud, result, unreachable=None):
	scanner = result if callable(result) else (lambda config: (result, unreachable or {}))
	monkeypatch.setitem(cli.CLOUDS, cloud, (cli.CLOUDS[cloud][0], scanner))
	monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/" + name)

def test_sync_saves_the_list_and_reports_new_clusters(monkeypatch, capsys):
	use_scanner(monkeypatch, "aws", AWS_CLUSTERS[:1])
	cli.sync(default_config(), ["aws"])
	use_scanner(monkeypatch, "aws", AWS_CLUSTERS)
	cli.sync(default_config(), ["aws"])
	out = capsys.readouterr().out
	assert "2 cluster(s) in 2 account(s), 1 new" in out
	assert "+ team-dev / api" in out
	assert [c['name'] for c in cli.load_cache()['clusters']] == ["web", "api"]

def test_a_logged_out_cloud_keeps_the_saved_list(monkeypatch, capsys):
	use_scanner(monkeypatch, "aws", AWS_CLUSTERS)
	cli.sync(default_config(), ["aws"])
	def logged_out(config):
		raise LoggedOut("Error loading SSO Token")
	use_scanner(monkeypatch, "aws", logged_out)
	cli.sync(default_config(), ["aws"])
	out = capsys.readouterr().out
	assert "not logged in, keeping the saved list (2 cluster(s)). Run `kubepick login aws`" in out
	assert "Error loading SSO Token" in out
	assert len(cli.load_cache()['clusters']) == 2

def test_an_account_that_needs_its_own_login_keeps_its_saved_clusters(monkeypatch, capsys):
	use_scanner(monkeypatch, "aws", AWS_CLUSTERS)
	cli.sync(default_config(), ["aws"])
	use_scanner(monkeypatch, "aws", AWS_CLUSTERS[:1], {"team-dev": ("team-dev", "AADSTS50076: run az login")})
	cli.sync(default_config(), ["aws"])
	out = capsys.readouterr().out
	assert "1 account(s) not logged in, kept their saved clusters: team-dev" in out
	assert "AADSTS50076" in out
	assert sorted(c['name'] for c in cli.load_cache()['clusters']) == ["api", "web"]

def test_a_failing_scan_is_reported_and_keeps_the_saved_list(monkeypatch, capsys):
	use_scanner(monkeypatch, "aws", AWS_CLUSTERS)
	cli.sync(default_config(), ["aws"])
	def broken(config):
		raise RuntimeError("boom")
	use_scanner(monkeypatch, "aws", broken)
	cli.sync(default_config(), ["aws"])
	assert "failed, keeping the saved list (2 cluster(s)): boom" in capsys.readouterr().out
	assert len(cli.load_cache()['clusters']) == 2

def test_syncing_one_cloud_leaves_the_others_alone(monkeypatch):
	use_scanner(monkeypatch, "aws", AWS_CLUSTERS)
	use_scanner(monkeypatch, "gcp", [{'cloud': "gcp", 'account': "p", 'region': "europe-west1-b", 'name': "g"}])
	cli.sync(default_config(), ["aws", "gcp"])
	use_scanner(monkeypatch, "aws", [])
	cli.sync(default_config(), ["aws"])
	assert [c['name'] for c in cli.load_cache()['clusters']] == ["g"]

def test_add_and_remove_end_to_end(monkeypatch, tmp_path, capsys):
	use_scanner(monkeypatch, "aws", AWS_CLUSTERS)
	cli.sync(default_config(), ["aws"])

	def fake_add(data, cluster, name):
		data['clusters'].append({'name': name, 'cluster': {'server': "https://example.test"}})
		data['users'].append({'name': name, 'user': {}})
		data['contexts'].append({'name': name, 'context': {'cluster': name, 'user': name}})
	monkeypatch.setattr(cli, "add_to_kubeconfig", fake_add)

	path = tmp_path / "kubeconfig"
	cli.add(default_config(), path, "team-prod", True)
	assert [c['name'] for c in yaml.safe_load(path.read_text())['contexts']] == ["AWS-web-PROD-eucentral1"]

	cli.add(default_config(), path, "team-prod", True)  # second time: nothing new
	assert "already added as AWS-web-PROD-eucentral1" in capsys.readouterr().out

	cli.remove(path, "web", True)
	assert yaml.safe_load(path.read_text())['contexts'] == []
	assert kubeconfig.load_state(kubeconfig.state_path(path)) == {}


### AWS regions ###

def region_recorder(monkeypatch, clusters):
	seen = []
	def scanner(config):
		seen.append(config['aws']['regions'])
		return clusters, {}
	use_scanner(monkeypatch, "aws", scanner)
	return seen

def test_a_full_scan_can_remember_the_regions_that_have_clusters(monkeypatch, capsys):
	seen = region_recorder(monkeypatch, AWS_CLUSTERS)
	monkeypatch.setattr(cli, "interactive", lambda: True)
	asked = []
	monkeypatch.setattr("builtins.input", lambda prompt: asked.append(prompt) or "")
	cli.sync(default_config(), ["aws"])
	assert seen == [[]]
	assert cli.load_cache()['aws_regions'] == ["eu-central-1", "eu-west-1"]
	assert "Scan only these regions from now on?" in asked[0]
	assert "clusters are in 2 region(s): eu-central-1, eu-west-1" in capsys.readouterr().out

	cli.sync(default_config(), ["aws"])
	assert seen[-1] == ["eu-central-1", "eu-west-1"]
	assert "scanned eu-central-1, eu-west-1; `kubepick sync --all-regions` checks every region" in capsys.readouterr().out

def test_declining_keeps_scanning_every_region(monkeypatch):
	seen = region_recorder(monkeypatch, AWS_CLUSTERS)
	monkeypatch.setattr(cli, "interactive", lambda: True)
	monkeypatch.setattr("builtins.input", lambda prompt: "n")
	cli.sync(default_config(), ["aws"])
	cli.sync(default_config(), ["aws"])
	assert seen == [[], []]
	assert 'aws_regions' not in cli.load_cache()

def test_nothing_is_asked_or_remembered_without_a_terminal(monkeypatch):
	region_recorder(monkeypatch, AWS_CLUSTERS)
	monkeypatch.setattr(cli, "interactive", lambda: False)
	monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("must not ask"))
	cli.sync(default_config(), ["aws"])
	assert 'aws_regions' not in cli.load_cache()

def test_region_precedence_flag_then_all_regions_then_config_then_remembered():
	config = default_config()
	cache = {'aws_regions': ["remembered-1"]}
	assert cli.regions_to_scan(config, cache, None, False) == ["remembered-1"]
	config['aws']['regions'] = ["configured-1"]
	assert cli.regions_to_scan(config, cache, None, False) == ["configured-1"]
	assert cli.regions_to_scan(config, cache, None, True) == []
	assert cli.regions_to_scan(config, cache, ["flag-1"], True) == ["flag-1"]

def test_regions_flag_and_all_regions_flag_are_parsed():
	args = cli.build_parser().parse_args(["sync", "aws", "--regions", "eu-west-1,us-west-2"])
	assert args.regions == ["eu-west-1", "us-west-2"] and args.all_regions is False
	assert cli.build_parser().parse_args(["sync", "--all-regions"]).all_regions is True

def test_end_of_input_at_the_question_counts_as_no(monkeypatch):
	region_recorder(monkeypatch, AWS_CLUSTERS)
	monkeypatch.setattr(cli, "interactive", lambda: True)
	def end_of_input(prompt):
		raise EOFError
	monkeypatch.setattr("builtins.input", end_of_input)
	cli.sync(default_config(), ["aws"])
	assert 'aws_regions' not in cli.load_cache()


### Login ###

def record_logins(monkeypatch):
	logged_in = []
	monkeypatch.setattr(cli, "login", lambda config, clouds: logged_in.append(clouds))
	monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/" + name)
	return logged_in

def test_login_without_arguments_asks_which_cloud(monkeypatch):
	logged_in = record_logins(monkeypatch)
	monkeypatch.setattr(cli, "interactive", lambda: True)
	offered = []
	monkeypatch.setattr(cli, "choose", lambda lines, header: offered.extend(lines) or ["azure"])
	cli.main(["login"])
	assert logged_in == [["azure"]]
	assert [key for text, key in offered] == ["aws", "azure", "gcp"]

def test_login_offers_every_cloud_and_marks_the_ones_whose_cli_is_missing(monkeypatch):
	logged_in = record_logins(monkeypatch)
	monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/aws" if name == "aws" else None)
	monkeypatch.setattr(cli, "interactive", lambda: True)
	offered = {}
	monkeypatch.setattr(cli, "choose", lambda lines, header: offered.update({key: text for text, key in lines}) or [])
	cli.main(["login"])
	assert list(offered) == ["aws", "azure", "gcp"]
	assert "not installed" not in offered["aws"]
	assert offered["azure"].startswith("✗") and "az CLI not installed" in offered["azure"] and cli.INSTALL_URLS["azure"] in offered["azure"]
	assert "gcloud CLI not installed" in offered["gcp"] and cli.INSTALL_URLS["gcp"] in offered["gcp"]
	assert logged_in == []

def test_login_with_no_cloud_cli_lists_where_to_get_them_instead_of_asking(monkeypatch, capsys):
	logged_in = record_logins(monkeypatch)
	monkeypatch.setattr(cli.shutil, "which", lambda name: None)
	monkeypatch.setattr(cli, "interactive", lambda: True)
	monkeypatch.setattr(cli, "choose", lambda lines, header: pytest.fail("nothing to choose from"))
	cli.main(["login"])
	out = capsys.readouterr().out
	assert "No cloud CLI found" in out
	assert all(url in out for url in cli.INSTALL_URLS.values())
	assert logged_in == []

def test_logging_in_to_a_cloud_without_its_cli_says_where_to_get_it(monkeypatch, capsys):
	monkeypatch.setattr(cli.shutil, "which", lambda name: None)
	cli.login(default_config(), ["gcp"])
	assert "skipped, gcloud CLI not installed, get it at {}".format(cli.INSTALL_URLS["gcp"]) in capsys.readouterr().out

def test_sync_skips_a_cloud_without_its_cli_and_says_where_to_get_it(monkeypatch, capsys):
	monkeypatch.setattr(cli.shutil, "which", lambda name: None)
	cli.sync(default_config(), ["azure"])
	assert "skipped, az CLI not installed, get it at {}".format(cli.INSTALL_URLS["azure"]) in capsys.readouterr().out

def test_choosing_nothing_logs_in_nowhere(monkeypatch, capsys):
	logged_in = record_logins(monkeypatch)
	monkeypatch.setattr(cli, "interactive", lambda: True)
	monkeypatch.setattr(cli, "choose", lambda lines, header: [])
	cli.main(["login"])
	assert logged_in == []
	assert "Nothing selected" in capsys.readouterr().out

def test_login_all_and_named_clouds_do_not_ask(monkeypatch):
	logged_in = record_logins(monkeypatch)
	monkeypatch.setattr(cli, "choose", lambda lines, header: pytest.fail("must not ask"))
	cli.main(["login", "--all"])
	cli.main(["login", "gcp", "aws"])
	assert logged_in == [["aws", "azure", "gcp"], ["gcp", "aws"]]

def test_aws_login_that_cannot_be_guessed_lists_the_granted_portals(isolated_home, monkeypatch, capsys):
	(isolated_home / ".aws").mkdir()
	(isolated_home / ".aws" / "config").write_text("".join(
		"[profile {0}/Admin]\ngranted_sso_start_url = https://{0}/start\ngranted_sso_region = eu-central-1\n"
		"credential_process = granted credential-process --profile {0}/Admin\n".format(name) for name in ["one", "two"]))
	monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/" + name)
	cli.login(default_config(), ["aws"])
	out = capsys.readouterr().out
	assert "your Granted profiles log in through 2 portals" in out
	assert "granted sso login --sso-start-url https://two/start --sso-region eu-central-1" in out

def test_login_without_arguments_and_without_a_terminal_refuses_to_guess(monkeypatch):
	logged_in = record_logins(monkeypatch)
	monkeypatch.setattr(cli, "interactive", lambda: False)
	with pytest.raises(SystemExit) as stopped:
		cli.main(["login"])
	assert "say which cloud" in str(stopped.value)
	assert logged_in == []


### Added clusters: show the name, add again, rename ###

WEB = "aws|team-prod|eu-central-1|web"
API = "aws|team-dev|eu-west-1|api"

# The real thing replaces the entries of a name that already exists, so does the fake
def fake_add_context(data, cluster, name):
	for key in ("clusters", "users", "contexts"):
		data[key] = [e for e in data[key] if e['name'] != name]
	data['clusters'].append({'name': name, 'cluster': {'server': "https://example.test"}})
	data['users'].append({'name': name, 'user': {}})
	data['contexts'].append({'name': name, 'context': {'cluster': name, 'user': name}})

def with_added_clusters(monkeypatch, tmp_path, *patterns):
	use_scanner(monkeypatch, "aws", AWS_CLUSTERS)
	cli.sync(default_config(), ["aws"])
	calls = []
	monkeypatch.setattr(cli, "add_to_kubeconfig", lambda data, cluster, name: calls.append(name) or fake_add_context(data, cluster, name))
	path = tmp_path / "kubeconfig"
	for pattern in patterns:
		cli.add(default_config(), path, pattern, True)
	return path, calls

def answers(monkeypatch, *typed):
	remaining = iter(typed)
	monkeypatch.setattr("builtins.input", lambda prompt: next(remaining))

def saved(path):
	return yaml.safe_load(path.read_text())

def test_the_list_shows_the_name_an_added_cluster_got(monkeypatch, tmp_path):
	path, _ = with_added_clusters(monkeypatch, tmp_path, "team-prod")
	shown = {}
	monkeypatch.setattr(cli, "choose", lambda lines, header, pattern=None: shown.update({key: text for text, key in lines}) or [])
	cli.add(default_config(), path, None, False)
	assert shown[WEB].startswith("✓") and shown[WEB].endswith("→ AWS-web-PROD-eucentral1")
	assert shown[API].startswith(" ") and "→" not in shown[API]

def test_choosing_an_added_cluster_again_can_give_it_a_new_name(monkeypatch, tmp_path):
	path, _ = with_added_clusters(monkeypatch, tmp_path, "team-prod")
	data = saved(path)
	data['current-context'] = "AWS-web-PROD-eucentral1"
	path.write_text(yaml.dump(data))
	monkeypatch.setattr(cli, "choose", lambda lines, header, pattern=None: [WEB])
	answers(monkeypatch, "y", "prod-web")
	cli.add(default_config(), path, None, False)
	data = saved(path)
	assert [c['name'] for c in data['contexts']] == ["prod-web"]
	assert [c['name'] for c in data['clusters']] == [c['name'] for c in data['users']] == ["prod-web"]
	assert data['current-context'] == "prod-web"
	assert cli.load_state(cli.state_path(path)) == {"prod-web": WEB}

def test_adding_again_under_the_same_name_refreshes_the_entries(monkeypatch, tmp_path, capsys):
	path, calls = with_added_clusters(monkeypatch, tmp_path, "team-prod")
	monkeypatch.setattr(cli, "choose", lambda lines, header, pattern=None: [WEB])
	answers(monkeypatch, "yes", "")
	cli.add(default_config(), path, None, False)
	assert calls == ["AWS-web-PROD-eucentral1"] * 2
	assert [c['name'] for c in saved(path)['contexts']] == ["AWS-web-PROD-eucentral1"]
	assert "refreshed as AWS-web-PROD-eucentral1" in capsys.readouterr().out

def test_declining_to_add_again_changes_nothing(monkeypatch, tmp_path, capsys):
	path, calls = with_added_clusters(monkeypatch, tmp_path, "team-prod")
	before = path.read_text()
	monkeypatch.setattr(cli, "choose", lambda lines, header, pattern=None: [WEB])
	answers(monkeypatch, "")
	cli.add(default_config(), path, None, False)
	assert calls == ["AWS-web-PROD-eucentral1"]
	assert path.read_text() == before
	assert "keeping AWS-web-PROD-eucentral1" in capsys.readouterr().out

def test_a_new_name_that_another_context_has_is_refused_and_asked_again(monkeypatch, tmp_path):
	path, _ = with_added_clusters(monkeypatch, tmp_path, "team-prod", "team-dev")
	monkeypatch.setattr(cli, "choose", lambda lines, header, pattern=None: [WEB])
	answers(monkeypatch, "y", "AWS-api-DEV-euwest1", "fresh-name")
	cli.add(default_config(), path, None, False)
	assert sorted(c['name'] for c in saved(path)['contexts']) == ["AWS-api-DEV-euwest1", "fresh-name"]

def test_adding_again_with_yes_leaves_added_clusters_alone(monkeypatch, tmp_path, capsys):
	path, calls = with_added_clusters(monkeypatch, tmp_path, "team-prod", "team-prod")
	assert calls == ["AWS-web-PROD-eucentral1"]
	assert "already added as AWS-web-PROD-eucentral1" in capsys.readouterr().out

def test_rename_with_both_names_renames_the_context_and_remembers_it(monkeypatch, tmp_path, capsys):
	path, calls = with_added_clusters(monkeypatch, tmp_path, "team-prod")
	cli.rename(default_config(), path, "AWS-web-PROD-eucentral1", "prod-web")
	data = saved(path)
	assert [c['name'] for c in data['contexts']] == ["prod-web"]
	assert [c['name'] for c in data['clusters']] == [c['name'] for c in data['users']] == ["prod-web"]
	assert cli.load_state(cli.state_path(path)) == {"prod-web": WEB}
	assert calls == ["AWS-web-PROD-eucentral1"]  # nothing was fetched again
	assert "AWS-web-PROD-eucentral1 -> prod-web" in capsys.readouterr().out

def test_rename_refuses_unknown_and_taken_names(monkeypatch, tmp_path):
	path, _ = with_added_clusters(monkeypatch, tmp_path, "team-prod", "team-dev")
	with pytest.raises(SystemExit) as unknown:
		cli.rename(default_config(), path, "nope", "x")
	assert "no context named nope" in str(unknown.value)
	with pytest.raises(SystemExit) as taken:
		cli.rename(default_config(), path, "AWS-web-PROD-eucentral1", "AWS-api-DEV-euwest1")
	assert "already exists" in str(taken.value)
	assert sorted(c['name'] for c in saved(path)['contexts']) == ["AWS-api-DEV-euwest1", "AWS-web-PROD-eucentral1"]

def test_rename_without_names_asks_and_suggests_the_name_from_your_rules(monkeypatch, tmp_path, capsys):
	path, _ = with_added_clusters(monkeypatch, tmp_path, "team-prod")
	monkeypatch.setattr(cli, "choose", lambda lines, header, pattern=None: ["AWS-web-PROD-eucentral1"])
	config = default_config()
	config['naming']['template'] = "{cluster}-{region}"
	answers(monkeypatch, "web-here")
	cli.rename(config, path, None, None)
	assert [c['name'] for c in saved(path)['contexts']] == ["web-here"]
	assert "your naming rules suggest web-eucentral1" in capsys.readouterr().out

def test_pressing_enter_keeps_the_name_when_renaming(monkeypatch, tmp_path, capsys):
	path, _ = with_added_clusters(monkeypatch, tmp_path, "team-prod")
	before = path.read_text()
	monkeypatch.setattr(cli, "choose", lambda lines, header, pattern=None: ["AWS-web-PROD-eucentral1"])
	answers(monkeypatch, "")
	cli.rename(default_config(), path, None, None)
	assert path.read_text() == before
	assert "Nothing renamed" in capsys.readouterr().out

def test_rename_on_the_command_line_needs_both_names_or_none(monkeypatch, tmp_path):
	path, _ = with_added_clusters(monkeypatch, tmp_path, "team-prod")
	with pytest.raises(SystemExit) as stopped:
		cli.main(["rename", "--kubeconfig", str(path), "AWS-web-PROD-eucentral1"])
	assert stopped.value.code == 2
	cli.main(["rename", "--kubeconfig", str(path), "AWS-web-PROD-eucentral1", "prod-web"])
	assert [c['name'] for c in saved(path)['contexts']] == ["prod-web"]


def test_the_picker_shows_the_aws_account_id(monkeypatch, tmp_path):
	with_id = [dict(AWS_CLUSTERS[0], account_id="123456789012"), AWS_CLUSTERS[1]]
	use_scanner(monkeypatch, "aws", with_id)
	use_scanner(monkeypatch, "gcp", [{'cloud': "gcp", 'account': "p", 'region': "europe-west1-b", 'name': "g"}])
	cli.sync(default_config(), ["aws", "gcp"])
	offered = []
	monkeypatch.setattr(cli, "choose", lambda lines, header, pattern=None: offered.extend(text for text, _ in lines) or [])
	cli.add(default_config(), tmp_path / "kubeconfig", None, False)
	aws = next(t for t in offered if "team-prod" in t)
	assert "123456789012" in aws
	assert aws.index("team-prod") < aws.index("123456789012") < aws.index("web")
	assert "team-dev" in next(t for t in offered if "api" in t)  # a record without an id still lists

def test_cluster_id_survives_an_account_rename():
	from kubepick.util import cluster_id
	before = dict(AWS_CLUSTERS[0], account_id="123456789012")
	after = dict(before, account="renamed")
	assert cluster_id(before) == cluster_id(after)
	assert cluster_id({'cloud': "gcp", 'account': "p", 'region': "r", 'name': "n"}) == "gcp|p|r|n"
