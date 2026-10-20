import yaml

from kubepick import kubeconfig
from kubepick.kubeconfig import add_to_kubeconfig, load_kubeconfig, remove_from_kubeconfig, rename_in_kubeconfig, save_kubeconfig, state_path

CLUSTER = {'cloud': "aws", 'account': "team", 'profile': "team/Admin", 'region': "eu-central-1", 'name': "web"}

# What `aws eks update-kubeconfig` writes: names are ARNs and the credentials come from an exec plugin
def fake_fetch(cluster, target):
	arn = "arn:aws:eks:{}:1:cluster/{}".format(cluster['region'], cluster['name'])
	with open(target, "w") as f:
		yaml.dump({
			'apiVersion': "v1", 'kind': "Config", 'current-context': arn,
			'clusters': [{'name': arn, 'cluster': {'server': "https://example.test", 'certificate-authority-data': "x"}}],
			'users': [{'name': arn, 'user': {'exec': {'apiVersion': "client.authentication.k8s.io/v1beta1", 'command': "aws",
				'args': ["eks", "get-token"], 'env': [{'name': "AWS_PROFILE", 'value': cluster['profile']}]}}}],
			'contexts': [{'name': arn, 'context': {'cluster': arn, 'user': arn}}],
		}, f)

def test_added_context_gets_the_chosen_name_everywhere(monkeypatch):
	monkeypatch.setattr(kubeconfig, "fetch_credentials", fake_fetch)
	data = load_kubeconfig(kubeconfig.Path("/nonexistent"))
	add_to_kubeconfig(data, CLUSTER, "AWS-web")
	assert data['contexts'] == [{'name': "AWS-web", 'context': {'cluster': "AWS-web", 'user': "AWS-web"}}]
	assert [c['name'] for c in data['clusters']] == ["AWS-web"]
	assert [u['name'] for u in data['users']] == ["AWS-web"]

def test_exec_plugin_keeps_its_profile_and_gets_a_path_for_gui_apps(monkeypatch):
	monkeypatch.setattr(kubeconfig, "fetch_credentials", fake_fetch)
	data = load_kubeconfig(kubeconfig.Path("/nonexistent"))
	add_to_kubeconfig(data, CLUSTER, "AWS-web")
	env = {e['name']: e['value'] for e in data['users'][0]['user']['exec']['env']}
	assert env['AWS_PROFILE'] == "team/Admin"
	assert "/usr/bin" in env['PATH'].split(":")

def test_adding_the_same_name_replaces_instead_of_duplicating(monkeypatch):
	monkeypatch.setattr(kubeconfig, "fetch_credentials", fake_fetch)
	data = load_kubeconfig(kubeconfig.Path("/nonexistent"))
	add_to_kubeconfig(data, CLUSTER, "AWS-web")
	add_to_kubeconfig(data, CLUSTER, "AWS-web")
	assert len(data['contexts']) == len(data['clusters']) == len(data['users']) == 1

def test_remove_drops_the_cluster_and_user_unless_shared(monkeypatch):
	monkeypatch.setattr(kubeconfig, "fetch_credentials", fake_fetch)
	data = load_kubeconfig(kubeconfig.Path("/nonexistent"))
	add_to_kubeconfig(data, CLUSTER, "one")
	add_to_kubeconfig(data, {**CLUSTER, 'name': "two"}, "two")
	data['current-context'] = "one"
	# a hand-made context sharing the entries of "two"
	data['contexts'].append({'name': "alias-of-two", 'context': {'cluster': "two", 'user': "two"}})

	remove_from_kubeconfig(data, "one")
	assert sorted(c['name'] for c in data['contexts']) == ["alias-of-two", "two"]
	assert sorted(c['name'] for c in data['clusters']) == ["two"]
	assert 'current-context' not in data

	remove_from_kubeconfig(data, "two")
	assert [c['name'] for c in data['clusters']] == ["two"]  # still used by alias-of-two
	remove_from_kubeconfig(data, "alias-of-two")
	assert data['clusters'] == data['users'] == data['contexts'] == []

def test_removing_an_unknown_context_changes_nothing(monkeypatch):
	monkeypatch.setattr(kubeconfig, "fetch_credentials", fake_fetch)
	data = load_kubeconfig(kubeconfig.Path("/nonexistent"))
	add_to_kubeconfig(data, CLUSTER, "one")
	remove_from_kubeconfig(data, "missing")
	assert len(data['contexts']) == 1

def test_save_backs_up_the_previous_file_and_keeps_it_private(tmp_path):
	path = tmp_path / "config"
	path.write_text("apiVersion: v1\nkind: Config\nclusters: []\n")
	data = load_kubeconfig(path)
	data['preferences'] = {}
	save_kubeconfig(path, data)
	assert (tmp_path / "config.bak-kubepick").read_text().startswith("apiVersion: v1")
	assert oct(path.stat().st_mode)[-3:] == "600"
	assert state_path(path) == tmp_path / "kubepick-managed.json"


### Renaming ###

def context(name, cluster=None, user=None):
	return {'name': name, 'context': {'cluster': cluster or name, 'user': user or name}}

def entries(*names):
	return [{'name': n, 'cluster': {}} for n in names]

def test_rename_renames_the_context_with_its_cluster_and_user():
	data = {'contexts': [context("old")], 'clusters': entries("old"), 'users': [{'name': "old", 'user': {}}], 'current-context': "old"}
	rename_in_kubeconfig(data, "old", "new")
	assert data['contexts'] == [context("new")]
	assert [c['name'] for c in data['clusters']] == ["new"]
	assert [u['name'] for u in data['users']] == ["new"]
	assert data['current-context'] == "new"

def test_rename_leaves_entries_that_another_context_uses():
	data = {
		'contexts': [context("old"), context("other", cluster="old", user="old")],
		'clusters': entries("old"), 'users': entries("old"), 'current-context': "other",
	}
	rename_in_kubeconfig(data, "old", "new")
	assert [c['name'] for c in data['contexts']] == ["new", "other"]
	assert [c['name'] for c in data['clusters']] == ["old"]
	assert data['contexts'][0]['context'] == {'cluster': "old", 'user': "old"}
	assert data['current-context'] == "other"

def test_rename_keeps_a_cluster_entry_that_has_a_different_name():
	data = {'contexts': [context("old", cluster="arn:cluster", user="arn:user")], 'clusters': entries("arn:cluster"), 'users': entries("arn:user")}
	rename_in_kubeconfig(data, "old", "new")
	assert data['contexts'][0] == context("new", cluster="arn:cluster", user="arn:user")
	assert [c['name'] for c in data['clusters']] == ["arn:cluster"]

def test_rename_does_not_take_over_an_unrelated_entry_with_the_new_name():
	data = {'contexts': [context("old")], 'clusters': entries("old", "new"), 'users': entries("old")}
	rename_in_kubeconfig(data, "old", "new")
	assert data['contexts'][0]['context'] == {'cluster': "old", 'user': "new"}
	assert sorted(c['name'] for c in data['clusters']) == ["new", "old"]
