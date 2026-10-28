import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone


def run(args, env=None, timeout=None):
	return subprocess.run(args, capture_output=True, text=True, env=env, timeout=timeout, stdin=subprocess.DEVNULL if timeout else None)

def now():
	return datetime.now(timezone.utc).isoformat(timespec="seconds")

def cluster_id(cluster):
	# the AWS account id survives a rename of the account, the name doesn't
	return "|".join([cluster['cloud'], cluster.get('account_id') or cluster['account'], cluster['region'], cluster['name']])

# The account a cluster belongs to, as scanners name the accounts they could not reach
def account_key(cluster):
	return cluster.get('account_id') or cluster.get('subscription_id') or cluster['account']

# Run fn over all jobs in parallel with a single in-place progress line, returning {job: result}
def parallel(label, jobs, fn, workers):
	results = {}
	with ThreadPoolExecutor(max_workers=workers) as executor:
		futures = {executor.submit(fn, *job): job for job in jobs}
		for done, future in enumerate(as_completed(futures), start=1):
			results[futures[future]] = future.result()
			if sys.stderr.isatty():
				print("\r  {} {}/{}".format(label, done, len(jobs)), end='', file=sys.stderr, flush=True)
	if sys.stderr.isatty():
		print("\r" + " " * 60 + "\r", end='', file=sys.stderr)
	return results
