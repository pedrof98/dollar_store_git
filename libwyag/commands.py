import argparse
import sys
import os
from datetime import datetime
import collections
import configparser
import fnmatch

from .repository import repo_find, repo_create
from .objects import (
    GitBlob, GitTree, GitCommit, GitTag, object_read, object_write,
    object_find, object_resolve, kvlm_parse, kvlm_serialize,
    tree_parse, tree_serialize, GitTreeLeaf
)
from .index import index_read, index_write, GitIndexEntry
from .refs import ref_resolve, ref_list, show_ref, ref_create

##################################################
# COMMANDS
##################################################

def cmd_init(args):
    repo_create(args.path)


def cmd_cat_file(args):
    repo = repo_find()
    sha = object_find(repo, args.object, fmt=args.type.encode())
    obj = object_read(repo, sha)
    # Print raw object contents to stdout (uncompressed)
    sys.stdout.buffer.write(obj.serialize())


def cmd_hash_object(args):
    if args.write:
        repo = repo_find()
    else:
        repo = None

    with open(args.path, "rb") as f:
        data = f.read()

    # Choose constructor
    fmt = args.type.encode()
    if fmt == b'commit':
        o = GitCommit(data)
    elif fmt == b'tree':
        o = GitTree(data)
    elif fmt == b'tag':
        o = GitTag(data)
    else:
        o = GitBlob(data)

    sha = object_write(o, repo)
    print(sha)


def cmd_show_ref(args):
    repo = repo_find()
    refs = ref_list(repo)
    show_ref(repo, refs, with_hash=True, prefix="refs")


def cmd_rev_parse(args):
    repo = repo_find()
    if args.type:
        fmt = args.type.encode()
    else:
        fmt = None
    sha = object_find(repo, args.name, fmt=fmt, follow=True)
    print(sha)


def cmd_ls_tree(args):
    repo = repo_find()
    tree_sha = object_find(repo, args.tree, fmt=b"tree")
    tree_obj = object_read(repo, tree_sha)
    def print_item(item, prefix=""):
        # Determine file mode
        mode = item.mode
        if len(mode) == 5:
            # e.g. '100644'
            # Take the first 2 digits for type detection
            t = mode[:2]
        else:
            t = mode[:3]

        if t == b'040':
            obj_type = "tree"
        elif t == b'100':
            obj_type = "blob"
        elif t == b'120':
            obj_type = "blob"  # symlink
        elif t == b'160':
            obj_type = "commit"  # submodule
        else:
            raise Exception(f"Weird mode {mode}")

        print("{0} {1} {2}\t{3}".format(
            mode.decode("ascii"), obj_type, item.sha, os.path.join(prefix, item.path)
        ))

    def recurse_tree(sha, prefix=""):
        t_obj = object_read(repo, sha)
        for leaf in t_obj.items:
            if args.recursive and leaf.mode.startswith(b'04'):
                recurse_tree(leaf.sha, os.path.join(prefix, leaf.path))
            else:
                print_item(leaf, prefix)

    recurse_tree(tree_sha)


def cmd_checkout(args):
    repo = repo_find()
    obj = object_read(repo, object_find(repo, args.commit))

    # If the object is a commit, get its tree
    if obj.fmt == b'commit':
        tree_sha = obj.kvlm[b'tree'].decode("ascii")
        obj = object_read(repo, tree_sha)

    # The directory must be empty or not exist
    dest_path = os.path.realpath(args.path)
    if os.path.exists(dest_path):
        if not os.path.isdir(dest_path):
            raise Exception(f"Not a directory: {dest_path}")
        if os.listdir(dest_path):
            raise Exception(f"Directory not empty: {dest_path}")
    else:
        os.makedirs(dest_path)

    def tree_checkout(tree_obj, path):
        for item in tree_obj.items:
            f_obj = object_read(repo, item.sha)
            dest = os.path.join(path, item.path)
            if f_obj.fmt == b'tree':
                os.mkdir(dest)
                tree_checkout(f_obj, dest)
            elif f_obj.fmt == b'blob':
                # For simplicity, ignoring symlinks
                with open(dest, "wb") as fd:
                    fd.write(f_obj.blobdata)

    tree_checkout(obj, dest_path)


def cmd_rm(args):
    repo = repo_find()
    _rm(repo, args.path)


def _rm(repo, paths, delete=True, skip_missing=False):
    idx = index_read(repo)
    worktree = repo.worktree + os.sep

    abspaths = []
    for p in paths:
        ap = os.path.abspath(p)
        if not ap.startswith(worktree):
            raise Exception(f"Cannot remove path outside of worktree: {p}")
        abspaths.append(ap)

    kept = []
    removed = []

    for e in idx.entries:
        full_path = os.path.join(repo.worktree, e.name)
        if full_path in abspaths:
            removed.append(full_path)
        else:
            kept.append(e)

    # Check for missing paths
    for p in abspaths:
        if p not in removed and not skip_missing:
            raise Exception(f"Cannot remove path not in index: {p}")

    if delete:
        for rm_path in removed:
            if os.path.exists(rm_path):
                os.unlink(rm_path)

    idx.entries = kept
    index_write(repo, idx)


def cmd_add(args):
    repo = repo_find()
    _add(repo, args.path)


def _add(repo, paths, skip_missing=False):
    """Add files to the index (staging)."""
    # First remove them from the index if present
    _rm(repo, paths, delete=False, skip_missing=True)

    idx = index_read(repo)
    worktree = repo.worktree + os.sep

    for p in paths:
        ap = os.path.abspath(p)
        if not ap.startswith(worktree):
            raise Exception(f"File outside of worktree: {p}")
        if not os.path.isfile(ap):
            raise Exception(f"Not a file or does not exist: {p}")

        with open(ap, "rb") as fd:
            from .objects import GitBlob, object_write
            blob_data = fd.read()
            blob = GitBlob(blob_data)
            sha = object_write(blob, repo)

        stat_res = os.stat(ap)
        ctime_s = int(stat_res.st_ctime)
        ctime_ns = stat_res.st_ctime_ns % 10**9
        mtime_s = int(stat_res.st_mtime)
        mtime_ns = stat_res.st_mtime_ns % 10**9

        ie = GitIndexEntry(
            ctime=(ctime_s, ctime_ns),
            mtime=(mtime_s, mtime_ns),
            dev=stat_res.st_dev,
            ino=stat_res.st_ino,
            mode_type=0b1000,  # '100' in octal => regular file
            mode_perms=0o644,
            uid=stat_res.st_uid,
            gid=stat_res.st_gid,
            fsize=stat_res.st_size,
            sha=sha,
            flag_assume_valid=False,
            flag_stage=0,
            name=os.path.relpath(ap, repo.worktree)
        )
        idx.entries.append(ie)

    index_write(repo, idx)


def cmd_log(args):
    repo = repo_find()
    start_sha = object_find(repo, args.commit, fmt=b"commit")
    seen = set()

    print("digraph wyaglog{")
    print(" node[shape=rect]")
    _log_graphviz(repo, start_sha, seen)
    print("}")


def _log_graphviz(repo, sha, seen):
    if sha in seen:
        return
    seen.add(sha)

    commit = object_read(repo, sha)
    msg = commit.kvlm[None].decode("utf-8").strip().replace("\\","\\\\").replace("\"","\\\"")
    if "\n" in msg:
        msg = msg.split("\n",1)[0]
    print(f" c_{sha} [label=\"{sha[:8]}: {msg}\"]")

    if b'parent' in commit.kvlm:
        parents = commit.kvlm[b'parent']
        if not isinstance(parents, list):
            parents = [parents]
        for p in parents:
            parent_sha = p.decode("ascii")
            print(f" c_{sha} -> c_{parent_sha};")
            _log_graphviz(repo, parent_sha, seen)


def cmd_status(args):
    repo = repo_find()
    idx = index_read(repo)

    _cmd_status_branch(repo)
    _cmd_status_head_index(repo, idx)
    print()
    _cmd_status_index_worktree(repo, idx)


def _cmd_status_branch(repo):
    head_path = repo.repo_file("HEAD")
    with open(head_path, "r") as f:
        head_content = f.read().strip()
    if head_content.startswith("ref: refs/heads/"):
        branch = head_content[16:]
        print(f"On branch {branch}")
    else:
        # detached HEAD
        from .objects import object_find
        sha = object_find(repo, "HEAD")
        print(f"Head detached at {sha}")


def _cmd_status_head_index(repo, idx):
    print("Changes to be committed:")
    head_tree = _tree_to_dict(repo, "HEAD")
    paths_in_index = {e.name for e in idx.entries}

    # compare HEAD tree with index
    # 1. If a file is in index but not in HEAD => "added"
    # 2. If a file is in both but different => "modified"
    # 3. If a file is in HEAD but not in index => "deleted"
    #  (We skip complexities like rename detection, etc.)
    for e in idx.entries:
        if e.name not in head_tree:
            print(f" added: {e.name}")
        else:
            if head_tree[e.name] != e.sha:
                print(f" modified: {e.name}")
            del head_tree[e.name]

    for remaining in head_tree.keys():
        print(f" deleted: {remaining}")


def _cmd_status_index_worktree(repo, idx):
    print("Changes not staged for commit:")

    # Build a list of all files in the worktree
    all_files = []
    gitdir_prefix = repo.gitdir + os.sep

    for root, dirs, files in os.walk(repo.worktree):
        # skip .git folder
        if root == repo.gitdir or root.startswith(gitdir_prefix):
            continue
        for f in files:
            full_path = os.path.join(root, f)
            rel_path = os.path.relpath(full_path, repo.worktree)
            all_files.append(rel_path)

    # Compare index entries with actual files
    #  - If missing => "deleted"
    #  - If timestamp changed => compare content => possibly "modified"
    for e in idx.entries:
        full_path = os.path.join(repo.worktree, e.name)
        if not os.path.exists(full_path):
            print(f" deleted: {e.name}")
        else:
            st = os.stat(full_path)
            ctime_ns = e.ctime[0]*10**9 + e.ctime[1]
            mtime_ns = e.mtime[0]*10**9 + e.mtime[1]
            if st.st_ctime_ns != ctime_ns or st.st_mtime_ns != mtime_ns:
                # If changed, check contents
                with open(full_path, "rb") as fd:
                    from .objects import GitBlob, object_write
                    new_data = fd.read()
                    new_blob = GitBlob(new_data)
                    new_sha = object_write(new_blob, None)  # Not storing in repo
                    if new_sha != e.sha:
                        print(f" modified: {e.name}")
        if e.name in all_files:
            all_files.remove(e.name)

    print()
    print("Untracked files:")
    # the rest of all_files are untracked
    # ignoring .gitignore rules, or partial support is possible
    for f in all_files:
        print(f"  {f}")


def _tree_to_dict(repo, ref, prefix=""):
    """Return a dict of {path -> sha} for the tree corresponding to ref."""
    from .objects import object_find, object_read
    tree_sha = object_find(repo, ref, fmt=b"tree")
    if not tree_sha:
        return {}
    t_obj = object_read(repo, tree_sha)
    result = {}

    for leaf in t_obj.items:
        full_path = os.path.join(prefix, leaf.path)
        if leaf.mode.startswith(b'04'):
            # It's a subtree
            subtree = _tree_to_dict(repo, leaf.sha, full_path)
            result.update(subtree)
        else:
            result[full_path] = leaf.sha
    return result


def cmd_commit(args):
    repo = repo_find()
    idx = index_read(repo)
    tree_sha = _tree_from_index(repo, idx)

    # Build commit object
    parent = object_find(repo, "HEAD", fmt=b"commit", follow=False)  # might be None if no HEAD
    author = _gitconfig_user_get()
    timestamp = datetime.now()
    message = args.message if args.message else "Commit message"

    new_commit_sha = _commit_create(repo, tree_sha, parent, author, timestamp, message)

    # Update HEAD (if on a branch)
    head_path = repo.repo_file("HEAD")
    with open(head_path, "r") as f:
        head_content = f.read().strip()
    if head_content.startswith("ref: "):
        # It's referencing a branch
        ref_path = head_content[5:]
        ref_create(repo, ref_path, new_commit_sha)
    else:
        # Detached HEAD
        with open(head_path, "w") as f:
            f.write(new_commit_sha + "\n")


def _commit_create(repo, tree_sha, parent_sha, author, timestamp, message):
    commit = GitCommit()
    kvlm = collections.OrderedDict()
    kvlm[b"tree"] = tree_sha.encode("ascii")
    if parent_sha:
        kvlm[b"parent"] = parent_sha.encode("ascii")

    # Format timezone
    tz_offset_sec = timestamp.astimezone().utcoffset().total_seconds()
    sign = "+" if tz_offset_sec >= 0 else "-"
    tz_offset_sec = abs(int(tz_offset_sec))
    hrs = tz_offset_sec // 3600
    mins = (tz_offset_sec % 3600) // 60
    tz_str = f"{sign}{hrs:02d}{mins:02d}"

    # "author" + "committer"
    date_str = str(int(timestamp.timestamp()))
    author_val = f"{author} {date_str} {tz_str}".encode("utf-8")

    kvlm[b"author"] = author_val
    kvlm[b"committer"] = author_val
    kvlm[None] = message.encode("utf-8")

    commit.kvlm = kvlm
    return object_write(commit, repo)


def _tree_from_index(repo, idx):
    """Construct a tree object from the current index's entries."""
    # Build a dict from directory -> list of items (files or subdirs)
    contents = collections.defaultdict(list)
    # We also need to ensure that all parent directories exist
    for entry in idx.entries:
        dirname = os.path.dirname(entry.name)
        # add directories up the chain to ensure we keep track of them
        # so that empty directories become subtrees
        key = dirname
        while key not in contents:
            if key == "":
                contents[key] = []
                break
            parent_key = os.path.dirname(key)
            if parent_key == key:
                contents[key] = []
                break
            contents[key] = []
            key = parent_key
        contents[dirname].append(entry)

    # We'll go from the bottom up, creating subtrees
    # sorted by path length descending
    all_dirs = sorted(contents.keys(), key=lambda x: len(x), reverse=True)

    # dict of {directory_path: SHA}
    tree_map = {}

    for d in all_dirs:
        items = []
        for entry in contents[d]:
            if isinstance(entry, GitIndexEntry):
                mode = b"100644"  # simplified: always 100644
                leaf_name = os.path.basename(entry.name)
                sha = entry.sha
                items.append(GitTreeLeaf(mode, leaf_name, sha))
            else:
                # If it's a subtree pointer like (name, sha), handle that
                pass
        # Also, check if we have subtrees
        # For each subdir in `contents` that is a direct child
        child_dirs = [c for c in all_dirs if os.path.dirname(c) == d and c != d]
        for cdir in child_dirs:
            base = os.path.basename(cdir)
            sha = tree_map.get(cdir)
            if sha:
                items.append(GitTreeLeaf(b"040000", base, sha))

        tree_obj = GitTree()
        tree_obj.items = items
        tree_sha = object_write(tree_obj, repo)
        tree_map[d] = tree_sha

    return tree_map[""]  # The root tree SHA


def _gitconfig_user_get(config):
    """Given a config, return 'Name <email>' or None."""
    if "user" in config:
        user_sec = config["user"]
        if "name" in user_sec and "email" in user_sec:
            return f"{user_sec['name']} <{user_sec['email']}>"
    return None


def _gitconfig_user_get():
    """Look up user info from ~/.gitconfig or other locations."""
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    configfiles = [
        os.path.join(xdg_config_home, "git", "config"),
        os.path.expanduser("~/.gitconfig")
    ]
    c = configparser.ConfigParser()
    c.read(configfiles)
    if "user" in c and "name" in c["user"] and "email" in c["user"]:
        return f"{c['user']['name']} <{c['user']['email']}>"
    return "Wyag <wyag@example.com>"  # fallback

