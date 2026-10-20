<p align="center">
  <img src="assets/logo.svg" alt="kubepick logo" width="120">
</p>

<h1 align="center">kubepick</h1>

<p align="center">
  <b>Log in, pick your clusters, get a clean kubeconfig.</b><br>
  AWS, Azure and GCP from one list, with names you can read.
</p>

<p align="center">
  <img src="assets/showreel.gif" alt="kubepick in 30 seconds: log in, sync, pick clusters, get readable names and a clean kubeconfig" width="880">
</p>

## Install

```shell
uv tool install git+https://github.com/iammathh/kubepick
```

One command: it installs `kubepick` into its own isolated environment, and doesn't change your shell setup or any
system files. [uv](https://docs.astral.sh/uv/getting-started/installation/) is the only thing you need first
(`brew install uv` on a Mac, `curl -LsSf https://astral.sh/uv/install.sh | sh` on Linux), and it fetches a suitable Python if you don't have one. If it tells you that
`~/.local/bin` is not on your `PATH`, run `uv tool update-shell` once.

| | |
| --- | --- |
| Try it without installing | `uvx --from git+https://github.com/iammathh/kubepick kubepick --help` |
| Update | `uv tool upgrade kubepick` |
| Remove | `uv tool uninstall kubepick` |
| Prefer pipx? | `pipx install git+https://github.com/iammathh/kubepick` |

## Use it

```shell
kubepick login    # choose which cloud to log in to
kubepick sync     # scan your clouds for clusters, the first scan takes a minute
kubepick add      # pick clusters, confirm their names, done
kubepick rm       # later: pick contexts to remove
```

Pick with [fzf](https://github.com/junegunn/fzf) (`brew install fzf` on a Mac, `sudo apt install fzf` or `sudo dnf install fzf` on Linux). Each cloud also needs its own CLI,
but you can start with just one, and kubepick tells you what is missing and where to get it:

| Cloud | CLI | Also needed |
| --- | --- | --- |
| AWS | `aws` | an SSO profile per account in `~/.aws/config` |
| Azure | `az` | `kubelogin` for clusters that use Entra ID |
| GCP | `gcloud` | `gke-gcloud-auth-plugin` |

```console
$ kubepick sync
AWS    43 cluster(s) in 19 account(s), 2 new
         + platform-prod / batch
         + analytics-dev / etl
AZURE  17 cluster(s) in 8 account(s)
GCP    5 cluster(s) in 3 account(s)

$ kubepick add
  AWS    platform-prod        api                 eu-central-1
✓ AWS    platform-prod        batch               eu-west-1            → AWS-batch-PROD-euwest1
  AZURE  analytics-dev        aks-analytics       germanywestcentral
> GCP    data-sandbox         gke-etl             europe-west4-a
  Tab: select several   Enter: confirm   ✓ → name = already added

GCP / data-sandbox / gke-etl (europe-west4-a)
  Name [GCP-gke-etl-SANDBOX-europewest4a]:
  added as GCP-gke-etl-SANDBOX-europewest4a
```

## Why kubepick

Working with many cloud accounts usually ends in one of two messes: a kubeconfig with every cluster in it and names like
`arn:aws:eks:eu-central-1:123456789012:cluster/web`, or hunting for the right account, region and
`aws eks update-kubeconfig` call every time you need one cluster. kubepick scans your clouds, lets you choose clusters,
proposes a name for each one, and writes them to your kubeconfig, so `kubectl`, Lens, Headlamp, k9s and friends all see
them. Removing a cluster works the same way.

- **One list for three clouds.** EKS, AKS and GKE, found through the CLIs you already use and are logged in with.
- **Names that follow your convention.** `AWS-platform-PROD-eucentral1`, or whatever template you configure.
- **You decide what goes in.** Nothing is added unless you pick it, and nothing is removed unless you pick it.
- **No credentials stored.** Entries call the cloud CLIs for tokens, exactly like the ones the CLIs write themselves.
- **Quiet when logged out.** A cloud you are logged out of keeps its saved list and prints a single line.
- **Safe to run.** The previous kubeconfig is backed up before every change, and entries from other sources are left alone.

## Commands

| Command | What it does |
| --- | --- |
| `kubepick sync [aws\|azure\|gcp]` | Scan the clouds and save the list of clusters. It only runs when you ask. |
| `kubepick add` | Choose clusters from the list, confirm or edit each proposed name, and add them to the kubeconfig. Clusters you already added show the name they got (`✓ → name`). Choosing one again asks whether to add it again, to refresh it or give it another name. This is the default command. |
| `kubepick rename [OLD NEW]` | Give an added context another name. Without names it asks which contexts, and tells you the name your naming rules would give. Nothing is fetched from the cloud, and the cluster and user entries of the context are renamed with it. |
| `kubepick rm` | Choose contexts and remove them, together with the cluster and user entries nothing else uses. |
| `kubepick login [aws\|azure\|gcp]` | Log in to a cloud, using the `login` commands from the configuration. Without a name it asks which clouds (all three are listed, those whose CLI is missing are marked with where to get it), `--all` logs in to every one. |
| `kubepick init` | Write an example configuration to `~/.config/kubepick/config.yaml`. |

`add` and `rm` also accept:

- `--match REGEX` selects every entry matching the regex instead of asking, handy in scripts
- `--yes` accepts the proposed names and skips the confirmation
- `--kubeconfig PATH` changes another file than `~/.kube/config`

`sync` also accepts `--regions eu-west-1,us-west-2` and `--all-regions`, see [Regions and speed](#regions-and-speed).

## Names

A name is built from a template, by default `{cloud}-{label}-{env}-{region}`:

| Field | Value |
| --- | --- |
| `cloud` | `AWS`, `AZURE` or `GCP` |
| `label` | the `label` of the first rule in `naming.labels` whose regex matches the account (AWS account, Azure subscription or GCP project), otherwise the cluster name with the words in `naming.strip` cut out |
| `env` | `PROD`, `STAGE`, `DEV` or `SANDBOX` when the account name contains that word, or when the cluster name did and `naming.strip` cut it out, otherwise empty |
| `region` | the region without dashes, such as `eucentral1` |
| `account`, `cluster` | the account and cluster names as they are. For AWS the account name is the one in the IAM Identity Center portal (see below) |

Empty fields are dropped together with the separator in front of them. With the rule `{match: 'platform', label: core}`, the
cluster `web` in the account `platform-prod` in `eu-central-1` is proposed as `AWS-core-PROD-eucentral1`. If a name is
already taken, the cluster name or a number is added. You can always type a different name.

### Cutting words out of cluster names

Cluster names often repeat what the rest of the name already says: environment, region code, kind of cluster. List those
words under `naming.strip` and they are removed from the cluster name, whatever is left becomes the label:

```yaml
naming:
  strip: [prod, 'eu[cw]\d', eks]
  remove_dashes: false
  lowercase: false
```

With that, the cluster `prod-euc1-payments-api-eks` in the account `payments-prod` (eu-central-1) is proposed as
`AWS-payments-api-PROD-eucentral1`: the words are gone from the label, and `PROD` is back in capitals as the environment.
Each word is matched against a whole part between dashes, ignoring case, and can be a regular expression. If everything
would be stripped, the original name is kept. A matching `naming.labels` rule still takes precedence.

Add `remove_dashes: true` to also remove the dashes inside that label, so it reads like a single word:
`AWS-paymentsapi-PROD-eucentral1`. The dashes between the parts of the name stay, and a label you wrote yourself under
`naming.labels` is used exactly as you wrote it.

`lowercase: true` makes that label lowercase too, handy for clusters named like `CRM` or `myAKSCluster`. The capitals of the
cloud (`AWS`) and of the environment (`PROD`) stay, and, as with `remove_dashes`, a label from `naming.labels` is left alone.

## Configuration

kubepick works without any configuration. To fit it to your setup, run `kubepick init` to write an example to
`~/.config/kubepick/config.yaml` (or `$XDG_CONFIG_HOME/kubepick/config.yaml`) and edit it. Everything specific to your setup
lives in that one file: login commands, naming rules, and which accounts, regions and projects to scan.

```yaml
aws:
  login: aws sso login --sso-session my-org
  role_preference: [AdministratorAccess, ReadOnlyAccess]
  regions: [us-east-1, eu-west-1]
  profiles: [dev/AdministratorAccess]
azure:
  tenant: 00000000-0000-0000-0000-000000000000
  login: az login --tenant 00000000-0000-0000-0000-000000000000
  subscriptions: [my-subscription]
gcp:
  login: gcloud auth login --update-adc
  projects: [my-project]
naming:
  template: "{cloud}-{label}-{env}-{region}"
  labels:
    - match: 'platform-prod'
      label: platform
  strip: [prod, 'eu[cw]\d', eks]
```

| Setting | Default |
| --- | --- |
| `aws.login` | `aws sso login --sso-session <name>` when `~/.aws/config` has exactly one sso-session, otherwise you have to set it. Use it for tools such as Granted: `granted sso login --sso-start-url ...` |
| `aws.role_preference` | When an account has several roles, the first one in this list wins, otherwise the first profile alphabetically |
| `aws.regions` | Every enabled region, or the ones remembered from the last full scan |
| `aws.profiles` | One profile per account, found from the SSO profiles in `~/.aws/config`. Set it to scan exactly these profiles, also non-SSO ones |
| `aws.account_names` | Names from the IAM Identity Center portal, read with `granted sso generate` when Granted is installed and logged in, otherwise the part of the profile name before the role (which goes stale when an account is renamed). Map account ids (quoted) to names to override them |
| `azure.tenant`, `azure.login` | `az login`, with `--tenant` when a tenant is set |
| `azure.subscriptions` | All enabled subscriptions. Names or ids |
| `gcp.login` | `gcloud auth login --update-adc` |
| `gcp.projects` | All projects you can see |
| `naming.template`, `naming.labels`, `naming.strip`, `naming.remove_dashes`, `naming.lowercase` | See [Names](#names). `strip` is empty and the other two are off by default, so names are proposed as they are |

## Regions and speed

AWS has no call that lists the clusters of every region, so the first scan checks every enabled region of every account.
That is thorough and slow, a minute or more with dozens of accounts. When the scan finishes, kubepick tells you which regions
had clusters and offers to scan only those from now on:

```console
AWS    43 cluster(s) in 19 account(s)
         clusters are in 4 region(s): ap-northeast-1, eu-central-1, eu-west-1, us-west-2
         Scan only these regions from now on? [Y/n]
```

After that, `kubepick sync` is a fraction of the time and says which regions it scanned. A cluster created in a new region
shows up after `kubepick sync --all-regions`. You can also pin the regions in the configuration with `aws.regions`, or pass
`--regions eu-west-1,us-west-2` for a single run.

## What it changes

- Only `add` and `rm` write to your kubeconfig, and the previous file is copied to `<kubeconfig>.bak-kubepick` first.
- The contexts it adds are listed in `kubepick-managed.json` next to the kubeconfig. Other contexts are only removed if you pick them in `rm`.
- Each added context has its own cluster and user entry with the same name, so removing it leaves nothing behind.
- The exec plugin of each entry gets absolute paths. Apps started from the Dock or a launcher don't have your shell's `PATH`, and could not find the cloud CLIs otherwise.
- The saved cluster list is a cache in `~/.cache/kubepick/`. Delete it any time.

## Troubleshooting

**`sync` says a cloud is not logged in, but I just logged in.**
Check that `kubepick login <cloud>` runs the command you use. For AWS, set `aws.login` if you use Granted or several sso-sessions.
An AWS scan that fails for only some accounts is also treated as logged out, because a partial list would make clusters look deleted.

**A cluster is missing.**
You may have no access to it, it may be in a region that is not scanned (`kubepick sync --all-regions`), or it may be
filtered out by `aws.regions`, `aws.profiles`, `azure.subscriptions` or `gcp.projects`.

**Azure asks for a device code every time.**
Install [`kubelogin`](https://github.com/Azure/kubelogin), then `kubepick rm` and `kubepick add` the cluster again. kubepick
converts Entra ID entries to reuse your `az login` session when it can find `kubelogin`.

**The cluster works with `kubectl` but not in my GUI app.**
Run `kubepick rm` and `kubepick add` again after installing or moving a cloud CLI, so the absolute paths in the entry are updated.

**I want to change the name of a cluster I added.**
Run `kubepick rename`, or `kubepick rename OLD NEW` if you know the names. Choosing the cluster again in `kubepick add` also lets you rename it, and refreshes its entries at the same time.

**I want to undo a change.**
Copy `~/.kube/config.bak-kubepick` back over `~/.kube/config`.

## Limits

- AWS accounts come from SSO profiles in `~/.aws/config`, including those generated by [Granted](https://github.com/fwdcloudsec/granted). Other profile types can be listed under `aws.profiles`.
- Clusters in accounts you have no access to cannot be found, and look the same as accounts without clusters.
- EKS, AKS and GKE only. Tested on macOS and Linux.

## Contributing

Bug reports and pull requests are welcome, see [CONTRIBUTING.md](CONTRIBUTING.md). Changes are listed in
[CHANGELOG.md](CHANGELOG.md).

## License

Public domain, see [LICENSE](LICENSE).
