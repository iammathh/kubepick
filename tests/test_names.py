from kubepick.config import default_config
from kubepick.names import detect_env, propose_name, strip_words, unique_name


def cluster(cloud="aws", account="team-prod", name="web", region="eu-central-1"):
	return {'cloud': cloud, 'account': account, 'name': name, 'region': region}

def naming(**overrides):
	return {**default_config()['naming'], **overrides}

def test_environment_is_detected_from_the_account_name():
	assert detect_env("billing-prod") == "PROD"
	assert detect_env("Platform---STAGING") == "STAGE"
	assert detect_env("team-sandbox") == "SANDBOX"
	assert detect_env("analytics") is None

def test_default_name_uses_cloud_cluster_env_and_region():
	assert propose_name(cluster(), naming()) == "AWS-web-PROD-eucentral1"

def test_empty_parts_are_dropped_with_their_separator():
	assert propose_name(cluster(account="analytics"), naming()) == "AWS-web-eucentral1"

def test_label_rule_replaces_the_cluster_name():
	rules = naming(labels=[{'match': "platform", 'label': "core"}])
	assert propose_name(cluster(account="platform-prod"), rules) == "AWS-core-PROD-eucentral1"

def test_label_rules_match_case_insensitively_and_first_rule_wins():
	rules = naming(labels=[{'match': "PLATFORM", 'label': "first"}, {'match': "platform", 'label': "second"}])
	assert propose_name(cluster(account="platform-dev"), rules) == "AWS-first-DEV-eucentral1"

def test_env_is_not_repeated_when_the_label_already_has_it():
	assert propose_name(cluster(account="team-sandbox", name="demo-sandbox"), naming()) == "AWS-demo-sandbox-eucentral1"

def test_other_clouds_and_regions():
	assert propose_name(cluster("azure", "team-dev", "aks1", "germanywestcentral"), naming()) == "AZURE-aks1-DEV-germanywestcentral"
	assert propose_name(cluster("gcp", "proj-dev", "gke1", "europe-west4-a"), naming()) == "GCP-gke1-DEV-europewest4a"

def test_custom_template():
	assert propose_name(cluster(), naming(template="{account}/{cluster}")) == "team-prod/web"

def test_unique_name_appends_the_cluster_then_a_number():
	c = cluster()
	assert unique_name("a", c, set()) == "a"
	assert unique_name("a", c, {"a"}) == "a-web"
	assert unique_name("a", c, {"a", "a-web"}) == "a-2"
	assert unique_name("a", c, {"a", "a-web", "a-2"}) == "a-3"


### Stripping words from the cluster name ###


STRIP = ["prod", "eu[cw]\\d", "eks"]

def stripped(**overrides):
	return naming(**{'strip': STRIP, **overrides})

def test_listed_words_are_cut_out_of_the_cluster_name():
	assert strip_words("prod-euc1-payments-api-eks", STRIP) == "payments-api"

def test_only_whole_parts_are_removed_and_case_does_not_matter():
	assert strip_words("Prod-weeks-eks-api", STRIP) == "weeks-api"
	assert strip_words("EUW1_web", STRIP) == "web"

def test_nothing_is_stripped_without_a_list():
	assert strip_words("prod-euc1-payments-api-eks", []) == "prod-euc1-payments-api-eks"

def test_a_name_that_would_be_empty_stays_as_it_is():
	assert strip_words("prod-eks", STRIP) == "prod-eks"

def test_the_stripped_name_becomes_the_label_and_the_environment_stays_in_capitals():
	named = cluster(account="payments-prod", name="prod-euc1-payments-api-eks")
	assert propose_name(named, stripped()) == "AWS-payments-api-PROD-eucentral1"

def test_the_environment_is_taken_from_the_cluster_name_when_the_account_has_none():
	named = cluster(account="analytics", name="stage-euw1-web-eks", region="eu-west-1")
	assert propose_name(named, stripped(strip=["stage", "eu[cw]\\d", "eks"])) == "AWS-web-STAGE-euwest1"

def test_an_environment_word_that_was_stripped_is_kept_and_wins_over_the_accounts():
	named = cluster(account="team-sandbox", name="shop-dev")
	assert propose_name(named, stripped(strip=["dev"])) == "AWS-shop-DEV-eucentral1"

def test_the_account_still_decides_the_environment_when_nothing_was_stripped():
	named = cluster(account="team-sandbox", name="shop-dev")
	assert propose_name(named, naming()) == "AWS-shop-dev-SANDBOX-eucentral1"

def test_a_label_rule_keeps_the_accounts_environment():
	rules = stripped(strip=["dev"], labels=[{'match': "team", 'label': "core"}])
	assert propose_name(cluster(account="team-prod", name="dev-web"), rules) == "AWS-core-PROD-eucentral1"

def test_a_label_rule_still_wins_over_stripping():
	rules = stripped(labels=[{'match': "platform", 'label': "core"}])
	assert propose_name(cluster(account="platform-prod", name="prod-api"), rules) == "AWS-core-PROD-eucentral1"

def test_without_a_strip_list_names_are_proposed_as_before():
	named = cluster(account="analytics", name="prod-euc1-web")
	assert propose_name(named, naming()) == "AWS-prod-euc1-web-eucentral1"


### Removing the dashes inside a label ###

def compact(**overrides):
	return naming(**{'remove_dashes': True, **overrides})

def test_dashes_inside_a_label_from_the_cluster_name_can_be_removed():
	assert propose_name(cluster(account="analytics", name="payments-api"), compact()) == "AWS-paymentsapi-eucentral1"

def test_the_dashes_between_the_parts_of_the_name_stay():
	named = cluster(account="payments-prod", name="prod-euc1-payments-api-eks")
	assert propose_name(named, compact(strip=STRIP)) == "AWS-paymentsapi-PROD-eucentral1"

def test_a_label_you_wrote_is_used_as_it_is():
	rules = compact(labels=[{'match': "platform", 'label': "control-plane"}])
	assert propose_name(cluster(account="platform-prod"), rules) == "AWS-control-plane-PROD-eucentral1"

def test_the_environment_is_not_repeated_when_the_label_still_has_it():
	assert propose_name(cluster(account="analytics", name="qa-shop-prod"), compact()) == "AWS-qashopprod-eucentral1"

def test_dashes_are_kept_by_default():
	assert propose_name(cluster(account="analytics", name="payments-api"), naming()) == "AWS-payments-api-eucentral1"


### Lowercase labels ###

def lower(**overrides):
	return naming(**{'lowercase': True, **overrides})

def test_a_label_from_the_cluster_name_can_be_made_lowercase():
	assert propose_name(cluster(account="analytics", name="myAKSCluster"), lower()) == "AWS-myakscluster-eucentral1"

def test_the_capitals_of_the_cloud_and_the_environment_stay():
	named = cluster("azure", "shop-prod", "CRM-Api", "germanywestcentral")
	assert propose_name(named, lower()) == "AZURE-crm-api-PROD-germanywestcentral"

def test_lowercase_leaves_a_label_you_wrote_alone():
	rules = lower(labels=[{'match': "platform", 'label': "CorePlatform"}])
	assert propose_name(cluster(account="platform-prod"), rules) == "AWS-CorePlatform-PROD-eucentral1"

def test_lowercase_works_together_with_strip_and_removing_dashes():
	named = cluster(account="analytics", name="PROD-EUC1-Order-Service-EKS")
	assert propose_name(named, lower(strip=STRIP, remove_dashes=True)) == "AWS-orderservice-PROD-eucentral1"

def test_capitals_are_kept_by_default():
	assert propose_name(cluster(account="analytics", name="myAKSCluster"), naming()) == "AWS-myAKSCluster-eucentral1"


def test_labels_and_env_match_the_portal_name_not_the_profile():
	rules = naming(labels=[{'match': "training", 'label': "learn"}])
	renamed = cluster(account="data-team-training")
	assert propose_name(renamed, rules) == "AWS-learn-eucentral1"
	assert propose_name(cluster(account="web-team-sandbox"), rules) == "AWS-web-SANDBOX-eucentral1"
	assert propose_name(cluster(account="data-team-training"), rules) != propose_name(cluster(account="web-team-sandbox"), rules)
