import re

PREFIXES = {"aws": "AWS", "azure": "AZURE", "gcp": "GCP"}

ENVIRONMENTS = [
	("PROD", {"prod", "production"}),
	("STAGE", {"stage", "staging"}),
	("DEV", {"dev"}),
	("SANDBOX", {"sandbox"}),
]

def words(text):
	return set(re.split(r"[^a-z0-9]+", text.lower()))

def detect_env(account):
	tokens = words(account)
	for env, names in ENVIRONMENTS:
		if tokens & names:
			return env
	return None

# Cut the listed words out of a cluster name, each one matched against a whole part between dashes
def strip_words(name, patterns):
	if not patterns:
		return name
	compiled = [re.compile(str(pattern), re.IGNORECASE) for pattern in patterns]
	kept = [part for part in re.split(r"[-_.]", name) if part and not any(c.fullmatch(part) for c in compiled)]
	return "-".join(kept) or name

def propose_name(cluster, naming):
	label = next((rule['label'] for rule in naming['labels'] if re.search(rule['match'], cluster['account'], re.IGNORECASE)), None)
	from_cluster_name = label is None
	if from_cluster_name:
		label = strip_words(cluster['name'], naming['strip'])
	env = detect_env(cluster['account'])
	# an environment word cut out of the cluster name stays as the env: it is more specific than the account's
	cluster_env = detect_env(cluster['name'])
	if from_cluster_name and cluster_env and cluster_env.lower() not in words(label):
		env = cluster_env
	if env and env.lower() in words(label):
		env = None

	# these only reshape a label made from the cluster name, a label you wrote yourself is used as it is
	if from_cluster_name and naming['remove_dashes']:
		label = label.replace("-", "")
	if from_cluster_name and naming['lowercase']:
		label = label.lower()

	values = {
		'cloud': PREFIXES[cluster['cloud']],
		'label': label,
		'env': env or "",
		'region': cluster['region'].replace("-", ""),
		'account': cluster['account'],
		'cluster': cluster['name'],
	}
	# drop empty fields together with the separator in front of them
	template = naming['template']
	for key, value in values.items():
		if not value:
			template = re.sub(r"[-_.]?\{%s\}" % key, "", template, count=1)
	return template.format(**values)

# Avoid clashing with a context that already exists
def unique_name(name, cluster, taken):
	for candidate in [name, "{}-{}".format(name, cluster['name'])]:
		if candidate not in taken:
			return candidate
	number = 2
	while "{}-{}".format(name, number) in taken:
		number += 1
	return "{}-{}".format(name, number)
