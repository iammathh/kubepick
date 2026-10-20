import json
import os
import shutil
import tempfile
from pathlib import Path

import yaml

from kubepick.util import run

DEFAULT_KUBECONFIG = Path.home() / ".kube" / "config"

def state_path(kubeconfig_path):
	return kubeconfig_path.with_name("kubepick-managed.json")

def load_kubeconfig(path):
	data = yaml.safe_load(path.read_text()) if path.exists() else {}
	data = data or {}
	data.setdefault('apiVersion', "v1")
	data.setdefault('kind', "Config")
	for key in ["clusters", "users", "contexts"]:
		data[key] = data.get(key) or []
	return data

# Keeps one backup of the previous version and replaces the file atomically
def save_kubeconfig(path, data):
	if path.exists():
		shutil.copy2(path, path.with_name(path.name + ".bak-kubepick"))
	temporary = path.with_name(path.name + ".tmp-kubepick")
	temporary.write_text(yaml.dump(data, sort_keys=False))
	os.chmod(temporary, 0o600)
	os.replace(temporary, path)

# Which context was added for which cluster, so `add` can mark what is already there and `rm` knows the origin
def load_state(path):
	try:
		return json.loads(path.read_text())
	except (OSError, ValueError):
		return {}

def save_state(path, state):
	path.write_text(json.dumps(state, indent=1))

# Fetch the credentials with the cloud's own CLI into a throwaway kubeconfig
def fetch_credentials(cluster, target):
	if cluster['cloud'] == "aws":
		result = run(["aws", "eks", "update-kubeconfig", "--name", cluster['name'], "--region", cluster['region'],
			"--profile", cluster['profile'], "--kubeconfig", target])
	elif cluster['cloud'] == "azure":
		result = run(["az", "aks", "get-credentials", "--subscription", cluster['subscription_id'], "--resource-group", cluster['resource_group'],
			"--name", cluster['name'], "--file", target, "--overwrite-existing", "--only-show-errors"])
		if result.returncode == 0 and cluster['aad'] and shutil.which("kubelogin"):
			# reuse the `az login` session instead of prompting for a device code on every connection
			result = run(["kubelogin", "convert-kubeconfig", "-l", "azurecli", "--kubeconfig", target])
	else:
		result = run(["gcloud", "container", "clusters", "get-credentials", cluster['name'], "--location", cluster['region'], "--project", cluster['account']],
			env={**os.environ, 'KUBECONFIG': target})
	if result.returncode != 0:
		raise RuntimeError((result.stderr.strip().splitlines() or ["command failed"])[-1])

# GUI apps started from the Dock don't get the shell's PATH, so the exec plugin gets absolute paths
def make_gui_safe(user):
	exec_config = user.get('exec')
	if not exec_config:
		return
	command = shutil.which(exec_config['command'])
	if command:
		exec_config['command'] = command
	directories = []
	for binary in ["aws", "granted", "az", "gcloud", "gke-gcloud-auth-plugin", "kubelogin"]:
		found = shutil.which(binary)
		if found and os.path.dirname(found) not in directories:
			directories.append(os.path.dirname(found))
	directories += ["/usr/local/bin", "/usr/bin", "/bin"]
	env = [e for e in (exec_config.get('env') or []) if e['name'] != "PATH"]
	exec_config['env'] = env + [{'name': "PATH", 'value': ":".join(directories)}]

# Add the cluster to the kubeconfig data under the given name; cluster and user entries get the same name so removal is clean
def add_to_kubeconfig(data, cluster, name):
	work = tempfile.mkdtemp()
	try:
		target = os.path.join(work, "config")
		fetch_credentials(cluster, target)
		with open(target) as fetched_file:
			fetched = yaml.safe_load(fetched_file)
	finally:
		shutil.rmtree(work, ignore_errors=True)

	context = fetched['contexts'][0]['context']
	cluster_entry = next(c for c in fetched['clusters'] if c['name'] == context['cluster'])
	user_entry = next(u for u in fetched['users'] if u['name'] == context['user'])
	make_gui_safe(user_entry['user'])

	for key in ["clusters", "users", "contexts"]:
		data[key] = [e for e in data[key] if e['name'] != name]
	data['clusters'].append({'name': name, 'cluster': cluster_entry['cluster']})
	data['users'].append({'name': name, 'user': user_entry['user']})
	data['contexts'].append({'name': name, 'context': {'cluster': name, 'user': name}})

def remove_from_kubeconfig(data, name):
	removed = next((c for c in data['contexts'] if c['name'] == name), None)
	data['contexts'] = [c for c in data['contexts'] if c['name'] != name]
	if removed is None:
		return
	# drop the cluster and user too, unless another context still uses them
	if not any(c['context'].get('cluster') == removed['context'].get('cluster') for c in data['contexts']):
		data['clusters'] = [c for c in data['clusters'] if c['name'] != removed['context'].get('cluster')]
	if not any(c['context'].get('user') == removed['context'].get('user') for c in data['contexts']):
		data['users'] = [u for u in data['users'] if u['name'] != removed['context'].get('user')]
	if data.get('current-context') == name:
		del data['current-context']

# Rename a context. The cluster and user entries are renamed with it when only this context uses them and they carry
# its name (the ones kubepick adds do), shared or unrelated entries keep their names.
def rename_in_kubeconfig(data, old, new):
	context = next(c for c in data['contexts'] if c['name'] == old)
	context['name'] = new
	for key, reference in (("clusters", "cluster"), ("users", "user")):
		used_by_others = any(c is not context and c['context'].get(reference) == old for c in data['contexts'])
		taken = any(e['name'] == new for e in data[key])
		if context['context'].get(reference) == old and not used_by_others and not taken:
			for entry in data[key]:
				if entry['name'] == old:
					entry['name'] = new
			context['context'][reference] = new
	if data.get('current-context') == old:
		data['current-context'] = new
