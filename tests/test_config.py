import subprocess

import pytest

from kubepick.config import EXAMPLE_CONFIG, config_dir, load_config, login_command
from kubepick.scanners import AWS_LOGIN_HINTS, discover_aws_profiles, needs_login


def write(path, text):
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(text)

def test_defaults_without_a_file():
	config = load_config()
	assert config['naming']['template'] == "{cloud}-{label}-{env}-{region}"
	assert config['aws']['regions'] == []

def test_the_example_configuration_is_valid():
	write(config_dir() / "config.yaml", EXAMPLE_CONFIG)
	assert load_config()['naming']['labels'] == []

def test_file_values_override_the_defaults_per_section(tmp_path):
	write(config_dir() / "config.yaml", "aws:\n  regions: [eu-west-1]\nnaming:\n  labels:\n    - {match: 'x', label: y}\n")
	config = load_config()
	assert config['aws']['regions'] == ["eu-west-1"]
	assert config['aws']['role_preference'] == []
	assert config['naming']['labels'] == [{'match': "x", 'label': "y"}]
	assert config['naming']['template'] == "{cloud}-{label}-{env}-{region}"

@pytest.mark.parametrize("text", [
	"naming:\n  template: '{cloud}-{nonsense}'\n",
	"naming:\n  labels:\n    - {match: '(', label: y}\n",
	"naming:\n  labels:\n    - {match: 'x'}\n",
])
def test_invalid_naming_is_rejected(text):
	write(config_dir() / "config.yaml", text)
	with pytest.raises(ValueError):
		load_config()

def test_login_commands(isolated_home):
	config = load_config()
	assert login_command("gcp", config) == ["gcloud", "auth", "login", "--update-adc"]
	assert login_command("azure", config) == ["az", "login"]
	config['azure']['tenant'] = "t1"
	assert login_command("azure", config) == ["az", "login", "--tenant", "t1"]
	config['aws']['login'] = "granted sso login --sso-start-url https://x.example/start"
	assert login_command("aws", config) == ["granted", "sso", "login", "--sso-start-url", "https://x.example/start"]

def test_aws_login_is_guessed_only_from_a_single_sso_session(isolated_home):
	aws = isolated_home / ".aws" / "config"
	config = load_config()
	assert login_command("aws", config) is None
	write(aws, "[sso-session corp]\nsso_start_url = https://x\n")
	assert login_command("aws", config) == ["aws", "sso", "login", "--sso-session", "corp"]
	write(aws, "[sso-session a]\n[sso-session b]\n")
	assert login_command("aws", config) is None

GRANTED_PROFILE = """
[profile {name}/Admin]
granted_sso_start_url = {url}
granted_sso_region = eu-central-1
granted_sso_account_id = 111
granted_sso_role_name = Admin
credential_process = granted credential-process --profile {name}/Admin
"""

def test_aws_login_uses_granted_when_the_profiles_get_their_credentials_from_it(isolated_home):
	aws = isolated_home / ".aws" / "config"
	config = load_config()
	# the sso-session is there too, but logging in to it doesn't give Granted's profiles credentials
	write(aws, "[sso-session default]\nsso_start_url = https://corp/start\n" + GRANTED_PROFILE.format(name="a", url="https://corp/start"))
	assert login_command("aws", config) == [
		"granted", "sso", "login", "--sso-start-url", "https://corp/start", "--sso-region", "eu-central-1"]
	write(aws, GRANTED_PROFILE.format(name="a", url="https://one/start") + GRANTED_PROFILE.format(name="b", url="https://two/start"))
	assert login_command("aws", config) is None
	config['aws']['profiles'] = ["b/Admin"]
	assert login_command("aws", config)[4] == "https://two/start"

def test_aws_profiles_one_per_account_preferring_configured_roles(isolated_home):
	write(isolated_home / ".aws" / "config", """
[profile dev/ReadOnly]
sso_account_id = 111
sso_role_name = ReadOnly
[profile dev/Admin]
sso_account_id = 111
sso_role_name = Admin
[profile prod/Admin]
granted_sso_account_id = 222
granted_sso_role_name = Admin
[profile static-keys]
aws_access_key_id = abc
""")
	config = load_config()
	assert discover_aws_profiles(config) == ["dev/Admin", "prod/Admin"]  # first alphabetically when no preference
	config['aws']['role_preference'] = ["ReadOnly", "Admin"]
	assert discover_aws_profiles(config) == ["dev/ReadOnly", "prod/Admin"]
	config['aws']['profiles'] = ["static-keys"]
	assert discover_aws_profiles(config) == ["static-keys"]

def test_login_errors_are_recognised_for_plain_sso_and_granted():
	assert needs_login("Error loading SSO Token: Token for x does not exist", AWS_LOGIN_HINTS)
	assert needs_login("The SSO session associated with this profile has expired", AWS_LOGIN_HINTS)
	assert needs_login("please login using 'granted sso login --sso-start-url ...'", AWS_LOGIN_HINTS)
	assert not needs_login("An error occurred (AccessDeniedException) when calling ListClusters", AWS_LOGIN_HINTS)


def test_the_strip_list_is_validated(isolated_home):
	write(config_dir() / "config.yaml", "naming:\n  strip: [prod, 'eu[cw]\\d']\n")
	assert load_config()['naming']['strip'] == ["prod", "eu[cw]\\d"]
	for text in ["naming:\n  strip: prod\n", "naming:\n  strip: ['(']\n"]:
		write(config_dir() / "config.yaml", text)
		with pytest.raises(ValueError):
			load_config()


def test_remove_dashes_is_off_by_default_and_must_be_a_boolean(isolated_home):
	assert load_config()['naming']['remove_dashes'] is False
	write(config_dir() / "config.yaml", "naming:\n  remove_dashes: true\n")
	assert load_config()['naming']['remove_dashes'] is True
	write(config_dir() / "config.yaml", "naming:\n  remove_dashes: sometimes\n")
	with pytest.raises(ValueError):
		load_config()


def test_lowercase_is_off_by_default_and_must_be_a_boolean(isolated_home):
	assert load_config()['naming']['lowercase'] is False
	write(config_dir() / "config.yaml", "naming:\n  lowercase: true\n")
	assert load_config()['naming']['lowercase'] is True
	write(config_dir() / "config.yaml", "naming:\n  lowercase: maybe\n")
	with pytest.raises(ValueError):
		load_config()


### AWS account names ###

from types import SimpleNamespace  # noqa: E402

from kubepick import scanners  # noqa: E402

AWS_CONFIG = """
[profile stale-name/Admin]
sso_account_id = 111
sso_role_name = Admin
sso_start_url = https://corp.awsapps.com/start
sso_region = eu-central-1
[profile other/Admin]
sso_account_id = 222
sso_session = corp
[sso-session corp]
sso_start_url = https://corp2.awsapps.com/start
sso_region = us-east-1
"""

GRANTED_OUTPUT = """[profile Portal-Name/Admin]
sso_account_id = 111
sso_role_name = Admin

[profile Portal-Name/ReadOnly]
sso_account_id = 111

[profile Second/Admin]
sso_account_id = 222
"""

def fake_granted(monkeypatch, result, calls=None):
	def fake_run(args, env=None, timeout=None):
		if calls is not None:
			calls.append((args, timeout))
		if isinstance(result, Exception):
			raise result
		return result
	monkeypatch.setattr(scanners, "run", fake_run)
	monkeypatch.setattr(scanners.shutil, "which", lambda name: "/usr/bin/" + name)

def accounts_from(isolated_home):
	write(isolated_home / ".aws" / "config", AWS_CONFIG)
	return scanners.discover_aws_accounts(load_config())

def test_account_ids_are_carried_with_the_profiles(isolated_home):
	assert accounts_from(isolated_home) == {"other/Admin": "222", "stale-name/Admin": "111"}

def test_portal_names_replace_the_profile_names_and_are_asked_once_per_portal(isolated_home, monkeypatch):
	accounts = accounts_from(isolated_home)
	calls = []
	fake_granted(monkeypatch, SimpleNamespace(returncode=0, stdout=GRANTED_OUTPUT, stderr=""), calls)
	names = scanners.aws_account_names(load_config(), accounts)
	assert names == {"stale-name/Admin": "Portal-Name", "other/Admin": "Second"}
	assert sorted(args[-1] for args, _ in calls) == ["https://corp.awsapps.com/start", "https://corp2.awsapps.com/start"]
	assert sorted(args[args.index("--sso-region") + 1] for args, _ in calls) == ["eu-central-1", "us-east-1"]
	assert all(timeout for _, timeout in calls)

@pytest.mark.parametrize("result", [
	SimpleNamespace(returncode=1, stdout="", stderr="not logged in"),
	SimpleNamespace(returncode=0, stdout="garbage without sections", stderr=""),
	subprocess.TimeoutExpired("granted", 30),
	FileNotFoundError("granted"),
])
def test_names_fall_back_to_the_profile_when_granted_fails(isolated_home, monkeypatch, result):
	accounts = accounts_from(isolated_home)
	fake_granted(monkeypatch, result)
	assert scanners.aws_account_names(load_config(), accounts) == {"stale-name/Admin": "stale-name", "other/Admin": "other"}

def test_names_fall_back_without_granted_installed(isolated_home, monkeypatch):
	accounts = accounts_from(isolated_home)
	monkeypatch.setattr(scanners.shutil, "which", lambda name: None)
	monkeypatch.setattr(scanners, "run", lambda *a, **k: pytest.fail("must not run granted"))
	assert scanners.aws_account_names(load_config(), accounts)["stale-name/Admin"] == "stale-name"

def test_configured_account_names_win_over_the_portal(isolated_home, monkeypatch):
	accounts = accounts_from(isolated_home)
	fake_granted(monkeypatch, SimpleNamespace(returncode=0, stdout=GRANTED_OUTPUT, stderr=""))
	config = load_config()
	config['aws']['account_names'] = {"111": "mine"}
	assert scanners.aws_account_names(config, accounts)["stale-name/Admin"] == "mine"

def test_account_names_must_be_a_mapping(isolated_home):
	write(config_dir() / "config.yaml", "aws:\n  account_names: [a]\n")
	with pytest.raises(ValueError, match="account_names"):
		load_config()

def test_scan_aws_records_the_portal_name_and_account_id(isolated_home, monkeypatch):
	write(isolated_home / ".aws" / "config", AWS_CONFIG)
	fake_granted(monkeypatch, SimpleNamespace(returncode=0, stdout=GRANTED_OUTPUT, stderr=""))
	monkeypatch.setattr(scanners, "list_eks", lambda profile, region: ["web"] if profile.startswith("stale") else [])
	config = load_config()
	config['aws']['regions'] = ["eu-west-1"]
	assert scanners.scan_aws(config) == ([
		{'cloud': "aws", 'account': "Portal-Name", 'account_id': "111", 'profile': "stale-name/Admin", 'region': "eu-west-1", 'name': "web"}], {})

EXPIRED = "Error loading SSO Token: Token for corp does not exist"

def test_an_account_that_needs_a_login_is_reported_instead_of_logging_out_the_cloud(isolated_home, monkeypatch):
	write(isolated_home / ".aws" / "config", AWS_CONFIG)
	fake_granted(monkeypatch, SimpleNamespace(returncode=0, stdout=GRANTED_OUTPUT, stderr=""))
	monkeypatch.setattr(scanners, "list_eks",
		lambda profile, region: ["web"] if profile.startswith("stale") else scanners.NeedsLogin(EXPIRED))
	config = load_config()
	config['aws']['regions'] = ["eu-west-1"]
	clusters, unreachable = scanners.scan_aws(config)
	assert [c['name'] for c in clusters] == ["web"]
	assert unreachable == {"222": ("Second", EXPIRED)}

def test_a_login_error_that_goes_away_on_a_second_try_is_not_reported(isolated_home, monkeypatch):
	write(isolated_home / ".aws" / "config", AWS_CONFIG)
	fake_granted(monkeypatch, SimpleNamespace(returncode=0, stdout=GRANTED_OUTPUT, stderr=""))
	tries = []
	def flaky(profile, region):
		tries.append(profile)
		return scanners.NeedsLogin(EXPIRED) if profile == "other/Admin" and tries.count(profile) == 1 else ["web"]
	monkeypatch.setattr(scanners, "list_eks", flaky)
	config = load_config()
	config['aws']['regions'] = ["eu-west-1"]
	clusters, unreachable = scanners.scan_aws(config)
	assert len(clusters) == 2 and unreachable == {}

def test_a_cloud_is_logged_out_only_when_no_account_works(isolated_home, monkeypatch):
	write(isolated_home / ".aws" / "config", AWS_CONFIG)
	fake_granted(monkeypatch, SimpleNamespace(returncode=0, stdout=GRANTED_OUTPUT, stderr=""))
	monkeypatch.setattr(scanners, "list_eks", lambda profile, region: scanners.NeedsLogin(EXPIRED))
	config = load_config()
	config['aws']['regions'] = ["eu-west-1"]
	with pytest.raises(scanners.LoggedOut, match="Token for corp"):
		scanners.scan_aws(config)

def test_regions_are_listed_through_another_portal_when_the_first_is_logged_out(isolated_home, monkeypatch):
	write(isolated_home / ".aws" / "config", AWS_CONFIG)
	calls = []
	def fake_run(args, env=None, timeout=None):
		calls.append(args[args.index("--profile") + 1])
		if args[-1] == "--no-cli-pager" and calls[-1] == "other/Admin":
			return SimpleNamespace(returncode=255, stdout="", stderr=EXPIRED)
		return SimpleNamespace(returncode=0, stdout='{"Regions": [{"RegionName": "eu-west-1"}]}', stderr="")
	monkeypatch.setattr(scanners, "run", fake_run)
	assert scanners.all_aws_regions(["other/Admin", "stale-name/Admin"]) == ["eu-west-1"]
	assert calls == ["other/Admin", "stale-name/Admin"]
