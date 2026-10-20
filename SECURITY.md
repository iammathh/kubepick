# Security

kubepick stores no credentials. The kubeconfig entries it writes call the cloud CLIs (`aws`, `az`, `gcloud` and their
plugins) to get tokens when needed, the same way entries written by those CLIs do.

It runs those CLIs and edits your kubeconfig, after copying it to `<kubeconfig>.bak-kubepick`.

If you find a security problem, please report it privately through GitHub's "Report a vulnerability" button on the
repository's Security tab instead of opening a public issue.
