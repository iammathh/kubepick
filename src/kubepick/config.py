import os
import re
import shlex
import string
from configparser import ConfigParser
from pathlib import Path

import yaml

# Everything specific to a setup (SSO URL, tenant, role names, naming rules) lives in this file and never in the code.

NAME_FIELDS = {"cloud", "label", "env", "region", "account", "cluster"}

EXAMPLE_CONFIG = """# kubepick configuration, see the README for details. Every setting is optional.

aws:
  # How to log in when the SSO session has expired (`kubepick login aws`).
  # Without this, kubepick uses `aws sso login --sso-session <name>` when ~/.aws/config has exactly one sso-session.
  # login: aws sso login --sso-session my-org
  # login: granted sso login --sso-start-url https://my-org.awsapps.com/start --sso-region eu-central-1

  # Accounts are found from the SSO profiles in ~/.aws/config. If an account has several roles,
  # the first one in this list wins, otherwise the first profile alphabetically.
  # role_preference: [AdministratorAccess, ReadOnlyAccess]

  # Scan only these regions (much faster) instead of every enabled region.
  # regions: [us-east-1, eu-west-1]

  # Use exactly these profiles instead of discovering them from ~/.aws/config.
  # profiles: [dev/AdministratorAccess, prod/ReadOnlyAccess]

  # Account names come from the IAM Identity Center portal (needs Granted, and a login). Set a name here to override one,
  # by account id (quoted, so leading zeros survive).
  # account_names:
  #   "123456789012": platform-prod

azure:
  # tenant: 00000000-0000-0000-0000-000000000000    # used by `az login --tenant`
  # login: az login --tenant 00000000-0000-0000-0000-000000000000
  # subscriptions: [my-subscription, 11111111-1111-1111-1111-111111111111]   # names or ids, default: all

gcp:
  # login: gcloud auth login --update-adc
  # projects: [my-project]   # default: all projects you can see

naming:
  # Proposed context names, empty parts are dropped. Fields: cloud, label, env, region, account, cluster
  template: "{cloud}-{label}-{env}-{region}"

  # label is the first rule whose regex matches the account (AWS account name, Azure subscription or GCP project).
  # Without a match it is the cluster name, minus the words listed under strip.
  labels: []
  #  - match: 'platform-prod'
  #    label: platform

  # Words to cut out of the cluster name, matched against each part between dashes (case-insensitive, regex allowed).
  # prod-euc1-payments-api-eks becomes payments-api with the list below.
  # env (PROD, STAGE, DEV, SANDBOX) is detected from the account name, or else from the cluster name, so it isn't lost.
  strip: []
  #  - prod
  #  - 'eu[cw]\\d'
  #  - eks

  # Remove the dashes inside a label made from the cluster name: payments-api becomes paymentsapi.
  # Labels you write yourself under labels are used as they are.
  remove_dashes: false

  # Make a label made from the cluster name lowercase: CRM becomes crm. Capitals in the cloud (AWS) and in env (PROD) stay.
  lowercase: false
"""


def config_dir():
	return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "kubepick"

def cache_dir():
	return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "kubepick"

def config_file():
	return config_dir() / "config.yaml"

def default_config():
	return {
		'aws': {'login': None, 'role_preference': [], 'regions': [], 'profiles': [], 'account_names': {}},
		'azure': {'login': None, 'tenant': None, 'subscriptions': []},
		'gcp': {'login': None, 'projects': []},
		'naming': {'template': "{cloud}-{label}-{env}-{region}", 'labels': [], 'strip': [], 'remove_dashes': False, 'lowercase': False},
	}

def validate(config):
	naming = config['naming']
	fields = {name for _, name, _, _ in string.Formatter().parse(naming['template']) if name}
	if not fields <= NAME_FIELDS:
		raise ValueError("naming.template uses unknown field(s) {}, use: {}".format(", ".join(sorted(fields - NAME_FIELDS)), ", ".join(sorted(NAME_FIELDS))))
	for index, rule in enumerate(naming['labels']):
		if not isinstance(rule, dict) or 'match' not in rule or 'label' not in rule:
			raise ValueError("naming.labels[{}] needs both 'match' and 'label'".format(index))
		try:
			re.compile(rule['match'])
		except re.error as error:
			raise ValueError("naming.labels[{}].match is not a valid regex: {}".format(index, error))
	if not isinstance(config['aws']['account_names'], dict):
		raise ValueError("aws.account_names must map account ids to names")
	for setting in ("remove_dashes", "lowercase"):
		if not isinstance(naming[setting], bool):
			raise ValueError("naming.{} must be true or false".format(setting))
	if not isinstance(naming['strip'], list):
		raise ValueError("naming.strip must be a list of words")
	for index, word in enumerate(naming['strip']):
		try:
			re.compile(str(word))
		except re.error as error:
			raise ValueError("naming.strip[{}] is not a valid regex: {}".format(index, error))

def load_config(path=None):
	path = path or config_file()
	config = default_config()
	if path.exists():
		loaded = yaml.safe_load(path.read_text()) or {}
		if not isinstance(loaded, dict):
			raise ValueError("{} must contain a mapping".format(path))
		for section, values in loaded.items():
			if section in config and isinstance(values, dict):
				config[section].update(values)
	validate(config)
	return config

def aws_config_path():
	return Path(os.environ.get("AWS_CONFIG_FILE") or Path.home() / ".aws" / "config")

def aws_parser():
	parser = ConfigParser(allow_no_value=True, interpolation=None)
	parser.read(aws_config_path())
	return parser

# The command that logs in to a cloud, or None when it can't be guessed and has to be configured
def login_command(cloud, config):
	configured = config[cloud].get('login')
	if configured:
		return shlex.split(configured)
	if cloud == "aws":
		sessions = [s[len("sso-session "):] for s in aws_parser().sections() if s.startswith("sso-session ")]
		return ["aws", "sso", "login", "--sso-session", sessions[0]] if len(sessions) == 1 else None
	if cloud == "azure":
		tenant = config['azure'].get('tenant')
		return ["az", "login"] + (["--tenant", tenant] if tenant else [])
	return ["gcloud", "auth", "login", "--update-adc"]
