import os
import zlib
import hashlib
import collections
import re
from math import ceil

from .repository import repo_find, GitRepository

##################################################
# GIT OBJECTS
##################################################

class GitObject:
    """Base class for Git objects: commit, tree, tag, blob."""
    fmt = None

    def __init__(self, data=None):
        if data is not None:
            self.deserialize(data)
        else:
            self.init()

    def init(self):
        """Subclasses can override if they need custom initialization."""
        pass

    def serialize(self):
        raise NotImplementedError("Subclasses must implement serialize().")

    def deserialize(self, data):
        raise NotImplementedError("Subclasses must implement deserialize().")


class GitBlob(GitObject):
    """A Git Blob object (stores file contents)."""
    fmt = b'blob'

    def serialize(self):
        return self.blobdata

    def deserialize(self, data):
        self.blobdata = data


class GitTreeLeaf:
    """A single entry in a tree object."""
    def __init__(self, mode, path, sha):
        self.mode = mode      # e.g. b'100644', b'040000', ...
        self.path = path      # file or directory name
        self.sha = sha        # the object’s SHA-1 hex string


class GitTree(GitObject):
    """A Git Tree object (directory listing)."""
    fmt = b'tree'

    def init(self):
        self.items = []

    def deserialize(self, data):
        self.items = tree_parse(data)

    def serialize(self):
        return tree_serialize(self)


class GitCommit(GitObject):
    """A Git Commit object."""
    fmt = b'commit'

    def init(self):
        self.kvlm = {}

    def deserialize(self, data):
        self.kvlm = kvlm_parse(data)

    def serialize(self):
        return kvlm_serialize(self.kvlm)


class GitTag(GitCommit):
    """A Git Tag object—same structure as a commit, but 'fmt = tag'."""
    fmt = b'tag'


##################################################
# OBJECT STORE: READ/WRITE/RESOLVE
##################################################

def object_read(repo, sha):
    """Read object from .git/objects/xx/xxxxxxxx...; return a GitObject."""
    path = repo.repo_file("objects", sha[0:2], sha[2:])
    if not os.path.isfile(path):
        return None

    with open(path, "rb") as f:
        raw = zlib.decompress(f.read())

    # raw = b"blob 14\0<file-contents>" or b"commit 177\0..."
    space = raw.find(b' ')
    obj_type = raw[:space]  # e.g. b'blob'
    null = raw.find(b'\x00', space)
    size = int(raw[space+1:null].decode("ascii"))
    content = raw[null+1:]

    if size != len(content):
        raise Exception(f"Malformed object {sha}: bad length (expected {size}, got {len(content)})")

    # Determine object type
    if obj_type == b'commit':
        c = GitCommit
    elif obj_type == b'tree':
        c = GitTree
    elif obj_type == b'tag':
        c = GitTag
    elif obj_type == b'blob':
        c = GitBlob
    else:
        raise Exception(f"Unknown type {obj_type.decode('ascii')} for object {sha}")

    return c(content)


def object_write(obj, repo=None):
    """Serialize and write object to repo, return the object's SHA-1."""
    data = obj.serialize()
    # e.g. b'blob 14\0file content'
    full = obj.fmt + b' ' + str(len(data)).encode() + b'\x00' + data
    sha = hashlib.sha1(full).hexdigest()

    if repo:
        path = repo.repo_file("objects", sha[0:2], sha[2:], mkdir=True)
        if not os.path.exists(path):
            with open(path, "wb") as f:
                f.write(zlib.compress(full))

    return sha


def object_resolve(repo, name):
    """
    Resolve a partial name (HEAD, short hash, tag, branch, etc.)
    into a *list* of possible SHA-1 values.
    """
    candidates = []
    name = name.strip()

    if name == "HEAD":
        from .refs import ref_resolve
        head_sha = ref_resolve(repo, "HEAD")
        if head_sha:
            return [head_sha]
        else:
            return []

    # Is it a full or partial hex?
    # e.g. 366e10f or f42a1b4...
    # Regex to match 4 to 40 hex characters
    hash_re = re.compile(r"^[0-9A-Fa-f]{4,40}$")
    if hash_re.match(name):
        name = name.lower()
        # Try to find an object in objects dir with this prefix
        # first two digits => subfolder
        subdir = name[:2]
        rest = name[2:]
        obj_dir = repo.repo_dir("objects", subdir)
        if obj_dir:
            for filename in os.listdir(obj_dir):
                if filename.startswith(rest):
                    candidates.append(subdir + filename)

    # If it exactly matches a tag or branch
    from .refs import ref_resolve
    tag_sha = ref_resolve(repo, "refs/tags/" + name)
    if tag_sha:
        candidates.append(tag_sha)
    branch_sha = ref_resolve(repo, "refs/heads/" + name)
    if branch_sha:
        candidates.append(branch_sha)

    return list(set(candidates))  # remove duplicates, if any


def object_find(repo, name, fmt=None, follow=True):
    """
    Find and return the SHA-1 of an object in repo.
    If fmt is given, the object must match that type,
    or we follow tags if follow=True, etc.
    """
    shalist = object_resolve(repo, name)
    if not shalist:
        raise Exception(f"No such reference {name}.")

    if len(shalist) > 1:
        raise Exception(f"Ambiguous reference {name}: Candidates are:\n - " + "\n - ".join(shalist))

    sha = shalist[0]

    if not fmt:
        return sha

    while True:
        obj = object_read(repo, sha)
        if obj.fmt == fmt:
            return sha
        if not follow:
            return None
        if obj.fmt == b'tag':
            # A tag points to something else
            kvlm = obj.kvlm  # the commit-style dict
            # A tag object has an `object` field pointing to the actual object
            sha = kvlm[b'object'].decode("ascii")
        elif obj.fmt == b'commit' and fmt == b'tree':
            # A commit references a tree
            sha = obj.kvlm[b'tree'].decode("ascii")
        else:
            return None


##################################################
# COMMIT/TAG/TREE PARSING & SERIALIZING
##################################################

def kvlm_parse(raw, start=0, dct=None):
    """Parse Commit or Tag data into a key-value list plus message (kvlm)."""
    if dct is None:
        dct = collections.OrderedDict()

    # Search for space and newline
    spc = raw.find(b' ', start)
    nl = raw.find(b'\n', start)

    # Base case: if newline comes first (or no spaces found)
    # we assume this to be message
    if (spc < 0) or (nl < spc):
        # A blank line. The rest is the message
        dct[None] = raw[start+1:]
        return dct

    # Read a key
    key = raw[start:spc]

    # Find the end of value
    end = start
    while True:
        end = raw.find(b'\n', end+1)
        # If next line doesn't start with a space, we found the end
        if raw[end+1] != ord(' '):
            break

    # Value is all lines, minus leading space on continuation
    value = raw[spc+1:end].replace(b'\n ', b'\n')

    # Save in dict
    if key in dct:
        if isinstance(dct[key], list):
            dct[key].append(value)
        else:
            dct[key] = [dct[key], value]
    else:
        dct[key] = value

    return kvlm_parse(raw, start=end+1, dct=dct)


def kvlm_serialize(kvlm):
    """Serialize a commit-like key-value list plus message."""
    ret = b''
    for k in kvlm.keys():
        if k is None:
            continue
        val = kvlm[k]
        if not isinstance(val, list):
            val = [val]
        for v in val:
            ret += k + b' ' + v.replace(b'\n', b'\n ') + b'\n'
    # Append message
    ret += b'\n'
    if kvlm.get(None):
        ret += kvlm[None]
    return ret


def tree_parse_one(raw, start=0):
    """
    Parse one "tree leaf" from raw data, returning:
      new_position, GitTreeLeaf(mode, path, sha)
    """
    # Find the space after mode
    x = raw.find(b' ', start)
    mode = raw[start:x]
    if len(mode) == 5:  # e.g. b'100644'
        # might be normal
        pass

    # Find the null terminator after path
    y = raw.find(b'\x00', x)
    path = raw[x+1:y]

    # Next 20 bytes are the SHA
    sha_raw = raw[y+1:y+21]
    sha_int = int.from_bytes(sha_raw, "big")
    sha = f"{sha_int:040x}"

    return y+21, GitTreeLeaf(mode, path.decode("utf-8"), sha)


def tree_parse(raw):
    """Parse a tree raw data into a list of GitTreeLeaf objects."""
    pos = 0
    maxlen = len(raw)
    items = []
    while pos < maxlen:
        pos, leaf = tree_parse_one(raw, pos)
        items.append(leaf)
    return items


def tree_serialize(tree_obj):
    """Serialize a GitTree object's items into raw bytes."""
    # Sort by path, but place directories (mode '040000') before files
    # (mimicking Git’s sorting). This is simplistic: real Git has more rules.
    def sort_key(leaf):
        if leaf.mode.startswith(b'04'):
            return leaf.path + '/'
        return leaf.path

    tree_obj.items.sort(key=sort_key)

    ret = b''
    for leaf in tree_obj.items:
        ret += leaf.mode
        ret += b' '
        ret += leaf.path.encode("utf-8")
        ret += b'\x00'
        sha_int = int(leaf.sha, 16)
        ret += sha_int.to_bytes(20, "big")
    return ret

