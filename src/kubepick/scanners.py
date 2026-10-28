import json
import random
import shutil
import subprocess
import time
from configparser import ConfigParser

from kubepick.config import aws_parser
from kubepick.util import parallel, run

# Every scanner returns (clusters, unreachable): the clusters it found, and {account key: (account, error)} for the
# accounts whose login has expired while others still work. When no account works it raises LoggedOut.
# Any other problem is raised, so it is shown as what it is instead of looking like a logout.

AWS_LOGIN_HINTS = ("sso login", "token has expired", "sso session", "error loading sso token", "identity center token")
AZURE_LOGIN_HINTS = ("aadsts", "az login")
PORTAL_TIMEOUT = 30

def needs_login(stderr, hints):
	text = stderr.lower()
	return any(hint in text for hint in hints)

def last_line(stderr):
	return (stderr.strip().splitlines() or ["command failed"])[-1]

class LoggedOut(Exception):
	pass

class NeedsLogin:
	def __init__(self, error):
		self.error = error

# Run fn over all jobs like parallel(), but don't let one login error stand for a whole cloud: jobs that report one are
# tried again with less parallelism (many CLIs refreshing the same token at once can trip over each other), and
# only when every job needs a login is the cloud logged out.
def scan_jobs(label, jobs, fn, workers):
	results = parallel(label, jobs, fn, workers)
	failed = [job for job, result in results.items() if isinstance(result, NeedsLogin)]
	if failed and len(failed) < len(jobs):
		results.update(parallel(label, failed, fn, workers=min(workers, 4)))
	errors = [result.error for result in results.values() if isinstance(result, NeedsLogin)]
	if jobs and len(errors) == len(jobs):
		raise LoggedOut(errors[0])
	return results


### AWS (EKS) ###

# Retry throttled calls (many parallel credential fetches), fail fast on anything else
def list_eks(profile, region):
	for attempt in range(4):
		result = run(["aws", "eks", "list-clusters", "--profile", profile, "--region", region, "--output", "json", "--no-cli-pager"])
		if result.returncode == 0 or not any(e in result.stderr for e in ["Throttl", "TooManyRequests", "Rate exceeded"]):
			break
		time.sleep(2 ** attempt + random.random())
	if needs_login(result.stderr, AWS_LOGIN_HINTS):
		return NeedsLogin(last_line(result.stderr))
	if result.returncode != 0:
		# no access to EKS in this region is normal (service control policies, disabled regions)
		return []
	try:
		return json.loads(result.stdout or "{}").get('clusters', [])
	except ValueError:
		return []

# {profile: account id} with one profile per account, from the SSO profiles in ~/.aws/config
def discover_aws_accounts(config):
	parser = aws_parser()
	if config['aws']['profiles']:
		return {profile: profile_account_id(parser, profile) for profile in sorted(config['aws']['profiles'])}

	preference = config['aws']['role_preference']
	accounts = {}
	for section in parser.sections():
		if not section.startswith("profile "):
			continue
		profile = section[len("profile "):]
		settings = parser[section]
		account_id = settings.get("sso_account_id") or settings.get("granted_sso_account_id")
		if account_id is None:
			continue
		role = settings.get("sso_role_name") or settings.get("granted_sso_role_name") or profile.split("/")[-1]
		rank = preference.index(role) if role in preference else len(preference)
		# ties go to the first profile alphabetically, so the choice doesn't depend on the order in the file
		if account_id not in accounts or (rank, profile) < accounts[account_id][:2]:
			accounts[account_id] = (rank, profile, account_id)
	return {profile: account_id for rank, profile, account_id in sorted(accounts.values(), key=lambda a: a[1])}

def discover_aws_profiles(config):
	return sorted(discover_aws_accounts(config))

def profile_account_id(parser, profile):
	section = "profile " + profile
	if parser.has_section(section):
		return parser[section].get("sso_account_id") or parser[section].get("granted_sso_account_id")
	return None

# Where each profile logs in: {(start url, region)}, from the profile itself or from its sso-session
def sso_portals(parser, profiles):
	portals = set()
	for profile in profiles:
		section = "profile " + profile
		if not parser.has_section(section):
			continue
		settings = parser[section]
		if settings.get("sso_session") and parser.has_section("sso-session " + settings["sso_session"]):
			session = parser["sso-session " + settings["sso_session"]]
			url, region = session.get("sso_start_url"), session.get("sso_region")
		else:
			url = settings.get("sso_start_url") or settings.get("granted_sso_start_url")
			region = settings.get("sso_region") or settings.get("granted_sso_region")
		if url and region:
			portals.add((url, region))
	return sorted(portals)

# {account id: name} for one portal, as granted prints it. Granted needs a login of its own,
# so anything that goes wrong just means no names from this portal.
def portal_account_names(url, region):
	try:
		result = run(["granted", "sso", "generate", "--sso-region", region, "--no-credential-process", url], timeout=PORTAL_TIMEOUT)
	except (OSError, subprocess.TimeoutExpired):
		return {}
	if result.returncode != 0:
		return {}
	parser = ConfigParser(allow_no_value=True, interpolation=None)
	try:
		parser.read_string(result.stdout)
	except Exception:
		return {}
	names = {}
	for section in parser.sections():
		account_id = parser[section].get("sso_account_id")
		if section.startswith("profile ") and account_id and "/" in section:
			names.setdefault(account_id, section[len("profile "):].rsplit("/", 1)[0])
	return names

# Account names for the profiles: your own overrides, else the names of the IAM Identity Center portal, else the part
# of the profile name before the role, which goes stale when an account is renamed.
def aws_account_names(config, accounts):
	names = {}
	if accounts and shutil.which("granted"):
		for url, region in sso_portals(aws_parser(), accounts):
			names.update(portal_account_names(url, region))
	names.update({str(account_id): name for account_id, name in config['aws']['account_names'].items()})
	return {profile: names.get(account_id) or profile.split("/")[0] for profile, account_id in accounts.items()}

# Every region, asked through the first profile of each SSO portal until one is logged in: profiles can log in
# through different sso-sessions, and `kubepick login` may only have refreshed one of them.
def all_aws_regions(profiles):
	parser = aws_parser()
	tried, error = set(), None
	for profile in profiles:
		portals = tuple(sso_portals(parser, [profile]))
		if portals in tried:
			continue
		tried.add(portals)
		# any region can list all regions, profiles don't necessarily have a default one
		result = run(["aws", "ec2", "describe-regions", "--profile", profile, "--region", "us-east-1", "--output", "json", "--no-cli-pager"])
		if result.returncode == 0:
			return sorted(region['RegionName'] for region in json.loads(result.stdout)['Regions'])
		if not needs_login(result.stderr, AWS_LOGIN_HINTS):
			raise RuntimeError(last_line(result.stderr))
		error = "{}: {}".format(profile, last_line(result.stderr))
	raise LoggedOut(error)

def scan_aws(config):
	accounts = discover_aws_accounts(config)
	profiles = list(accounts)
	if len(profiles) == 0:
		return [], {}

	regions = config['aws']['regions'] or all_aws_regions(profiles)
	results = scan_jobs("AWS", [(p, r) for p in profiles for r in regions], list_eks, workers=12)
	account_names = aws_account_names(config, accounts)

	# credentials are cached per account, so an expired session can show up on only some accounts. Their clusters
	# would look deleted, so they are reported as unreachable and keep what was saved for them.
	unreachable = {}
	for (profile, region), result in results.items():
		if isinstance(result, NeedsLogin):
			unreachable[accounts[profile] or account_names[profile]] = (account_names[profile], result.error)
	return [
		{'cloud': "aws", 'account': account_names[profile], 'account_id': accounts[profile], 'profile': profile, 'region': region, 'name': name}
		for (profile, region), names in sorted(results.items()) if not isinstance(names, NeedsLogin) for name in names
	], unreachable


### Azure (AKS) ###

def list_aks(subscription_id):
	result = run(["az", "aks", "list", "--subscription", subscription_id, "--only-show-errors", "-o", "json",
		"--query", "[].{name:name,resource_group:resourceGroup,region:location,aad:aadProfile.managed}"])
	if needs_login(result.stderr, AZURE_LOGIN_HINTS):
		return NeedsLogin(last_line(result.stderr))
	if result.returncode != 0:
		return []
	return json.loads(result.stdout or "[]")

def scan_azure(config):
	token = run(["az", "account", "get-access-token", "-o", "none", "--only-show-errors"])
	if token.returncode != 0:
		raise LoggedOut(last_line(token.stderr))
	result = run(["az", "account", "list", "--only-show-errors", "-o", "json", "--query", "[?state=='Enabled'].{id:id,name:name}"])
	wanted = config['azure']['subscriptions']
	subscriptions = {s['id']: s['name'] for s in json.loads(result.stdout or "[]") if not wanted or s['id'] in wanted or s['name'] in wanted}

	# a subscription in another tenant can need its own login (MFA, conditional access) while the rest work
	results = scan_jobs("Azure", [(s,) for s in subscriptions], list_aks, workers=12)
	unreachable = {subscription_id: (subscriptions[subscription_id], result.error)
		for (subscription_id,), result in results.items() if isinstance(result, NeedsLogin)}
	return [
		{'cloud': "azure", 'account': subscriptions[subscription_id], 'subscription_id': subscription_id, 'resource_group': c['resource_group'],
			'region': c['region'], 'aad': bool(c['aad']), 'name': c['name']}
		for (subscription_id,), clusters in sorted(results.items(), key=lambda r: subscriptions[r[0][0]])
		if not isinstance(clusters, NeedsLogin) for c in clusters
	], unreachable


### GCP (GKE) ###

def list_gke(project_id):
	result = run(["gcloud", "container", "clusters", "list", "--project", project_id, "--format", "json(name,location)"])
	if result.returncode != 0:
		# most projects don't have the GKE API enabled
		return []
	return json.loads(result.stdout or "[]")

def scan_gcp(config):
	token = run(["gcloud", "auth", "print-access-token"])
	if token.returncode != 0:
		raise LoggedOut(last_line(token.stderr))
	projects = config['gcp']['projects']
	if not projects:
		result = run(["gcloud", "projects", "list", "--format", "json(projectId)"])
		projects = [p['projectId'] for p in json.loads(result.stdout or "[]")]

	results = parallel("GCP", [(p,) for p in projects], list_gke, workers=16)
	return [
		{'cloud': "gcp", 'account': project_id, 'region': c['location'], 'name': c['name']}
		for (project_id,), clusters in sorted(results.items()) for c in clusters
	], {}


# where to get the CLI of each cloud
INSTALL_URLS = {
	"aws": "https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html",
	"azure": "https://learn.microsoft.com/cli/azure/install-azure-cli",
	"gcp": "https://cloud.google.com/sdk/docs/install",
}

# cloud -> (CLI it needs, scanner)
CLOUDS = {
	"aws": ("aws", scan_aws),
	"azure": ("az", scan_azure),
	"gcp": ("gcloud", scan_gcp),
}
