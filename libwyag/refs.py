import os
import collections

from .repository import GitRepository

def ref_resolve(repo, ref):
    """Follow a ref (e.g. 'HEAD' or 'refs/heads/master') until it resolves to a SHA-1."""
    path = repo.repo_file(ref)
    if not path or not os.path.isfile(path):
        return None
    with open(path, "r") as f:
        data = f.read().strip()
    if data.startswith("ref: "):
        return ref_resolve(repo, data[5:])
    else:
        return data


def ref_create(repo, ref_name, sha):
    """Create or update a ref (e.g. refs/heads/branchname) to point to given SHA-1."""
    ref_path = repo.repo_file(ref_name, mkdir=True)
    with open(ref_path, "w") as f:
        f.write(sha + "\n")


def ref_list(repo, path=None):
    """Recursively list references under 'refs', returning an OrderedDict."""
    if path is None:
        path = repo.repo_dir("refs")
    refs = collections.OrderedDict()
    if not path:
        return refs

    for name in sorted(os.listdir(path)):
        full = os.path.join(path, name)
        if os.path.isdir(full):
            refs[name] = ref_list(repo, full)
        else:
            # It's a file containing a SHA or 'ref: ...'
            refs[name] = ref_resolve(repo, os.path.relpath(full, repo.gitdir))
    return refs


def show_ref(repo, refs_dict, with_hash=True, prefix=""):
    """Recursive function to print refs (used by show-ref command)."""
    for name, val in refs_dict.items():
        if isinstance(val, dict):
            # subdirectory
            show_ref(repo, val, with_hash=with_hash,
                     prefix=(f"{prefix}/{name}" if prefix else name))
        else:
            if val:  # a valid SHA
                if prefix:
                    ref_name = f"{prefix}/{name}"
                else:
                    ref_name = name
                if with_hash:
                    print(f"{val} {ref_name}")
                else:
                    print(ref_name)

