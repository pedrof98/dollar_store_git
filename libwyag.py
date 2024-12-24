import argparse
import collections
import configparser
from datetime import datetime
import grp, pwd
from fnmatch import fnmatch
import hashlib
from math import ceil
import os
import re
import sys
import zlib


#all imports needed above

#For command-line arguments we need a parsing library
argparser = argparse.ArgumentParser(description="The least intuitive content tracker")


# To handle subcommands git add, init, commit we need subparsers
argsubparsers = argparser.add_subparsers(title="Commands", dest="command")
argsubparsers.required = True


# Bridge functions - these take the parsed arguments as unique parameters and process/validate them before exec the commands

def main(argv=sys.argv[1:]):
    args = argparser.parse_args(argv)
    match args.command:
        case "add"          : cmd_add(args)
        case "cat-file"     : cmd_cat_file(args)
        case "check-ignore" : cmd_check_ignore(args)
        case "checkout"     : cmd_checkout(args)
        case "commit"       : cmd_commit(args)
        case "hash-object"  : cmd_hash_object(args)
        case "init"         : cmd_init(args)
        case "log"          : cmd_log(args)
        case "ls-files"     : cmd_ls_files(args)
        case "ls-tree"      : cmd_ls_tree(args)
        case "rev-parse"    : cmd_rev_parse(args)
        case "rm"           : cmd_rm(args)
        case "show-ref"     : cmd_show_ref(args)
        case "status"       : cmd_status(args)
        case "tag"          : cmd_tag(args)
        case _              : print("Bad command")


"""
Repository object:
    A git repository is comprised of:
        - a work tree where the files meant to be in version control live
        - a git directory where Git stores its own data

    
    To create a new repo we need to make a few checks:
        - we must verify that the directory exists, and contains a subdirectory called .git.
        - we read its configuration in .git/config (INI file) and control that "core.repositoryformatversion" is 0.
"""



class GitRepository(object):
    """" A git repository """

    worktree = None
    gitdir = None
    conf = None

    def __init__(self, path, force=False):
        self.worktree = path
        self.gitdir = os.path.join(path, ".git")

        if not (force or os.path.isdir(self.gitdir)):
            raise Exception("Not a Git Repository %s" % path)

        # Read configuration file in .git/config
        self.conf = configparser.ConfigParser()
        cf = repo_file(self, "config")

        if cf and os.path.exists(cf):
            self.conf.read([cf])
        elif not force:
            raise Exception("Configuration file missing")

        if not force:
            vers = int(self.conf.get("core", "repositoryformatversion"))
            if vers != 0:
                raise Exception("Unsupported repositoryformatversion %s" % vers)





# Utility path building function 
#Note *path makes the function variadic, so it can be called with multiple path components as separate arguments like in *args
def repo_path(repo, *path):
    """Compute path under repo's gitdir"""
    return os.path.join(repo.gitdir, *path)


# Utility return or create file function
def repo_file(repo, *path, mkdir=False):
    """Same as repo_path, but creates dirname(*path) if absent.
    For example, repo_file(r, \"refs\", \"remotes\", \"origin\", \"HEAD\") will create .git/refs/remotes/origin."""

    if repo_dir(repo, *path[:-1], mkdir=mkdir):
        return repo_path(repo, *path)


# Utility return or create directory function
def repo_dir(repo, *path, mkdir=False):
    """Same as repo_path, but mkdir *path if absent if mkdir"""

    path = repo_path(repo, *path)

    if os.path.exists(path):
        if (os.path.isdir(path)):
            return path
        else:
            raise Exception("Not a directory %s" % path)


    if mkdir:
        os.makedirs(path)
        return path
    else:
        return None


"""Note on syntax for these utility functions:
    Since *path makes the functions variadic, the mkdir argument must be passed explicitly by name.
    For example, repo_file(repo, "objects", mkdir=True)

"""

"""
To create a new repo we start with a directory, created if it doesn't already exist, and then create the git directory inside.
That git directory is called .git and it is hidden on Unix systems.

"""

def repo_create(path):
    """Create a new repo at path"""
    repo = GitRepository(path, True)

    #First, let's make sure the path either doesn't exist or is an empty dir

    if os.path.exists(repo.worktree):
        if not os.path.isdir(repo.worktree):
            raise Exception("%s is not a directory!" % path)
        if os.path.exists(repo.gitdir) and os.listdir(repo.gitdir):
            raise Exception("%s is not empty!" % path)
    else:
        os.makedirs(repo.worktree)

    assert repo_dir(repo, "branches", mkdir=True)
    assert repo_dir(repo, "objects", mkdir=True)
    assert repo_dir(repo, "refs", "tags", mkdir=True)
    assert repo_dir(repo, "refs", "heads", mkdir=True)

    # .git/description
    with open(repo_file(repo, "description"), "w") as f:
        f.write("Unnamed repository; edit this file 'description' to name the repository.\n")


    # .git/HEAD
    with open(repo_file(repo, "HEAD"), "w") as f:
        f.write("ref: refs/heads/master\n")

    with open(repo_file(repo, "config"), "w") as f:
        config = repo_default_config()
        config.write(f)


    return repo





"""
Onto the configuration file:
    This is similar to a INI file with a single section ([core]) and three fields:
    
    - repositoryformatversion = 0: the version of the gitdir format. 
    - filemode = false: disable tracking of file modes (permissions) changes in the work tree
    - bare = false: indicates that this repo has a worktree.

"""


def repo_default_config():
    ret = configparser.ConfigParser()

    ret.add_section("core")
    ret.set("core", "repositoryformatversion", "0")
    ret.set("core", "filemode", "false")
    ret.set("core", "bare", "false")

    return ret


# The init command
# We need to create an argparse subparser to handle the command's argument

argsp = argsubparsers.add_parser("init", help="Initialize a new, empty repository")


"""
In the case of init, there's a single, optional positional argument:
    the path where to init the repo.
    This path defaults to ".", the current directory
"""

argsp.add_argument("path",
        metavar="directory",
        nargs="?",
        default=".",
        help="Where to create the repository.")

# Next we need a "bridge" function to read argument values from the object returned by argparse and call the actual function

def cmd_init(args):
    repo_create(args.path)



# Function to find the root of the current repo

def repo_find(path=".", required=True):
    path = os.path.realpath(path)

    if os.path.isdir(os.path.join(path, ".git")):
        return GitRepository(path)

    #If we haven't returned, recurse in parent, if w
    parent = os.path.realpath(os.path.join(path, ".."))

    if parent == path:
        #Bottom case
        #os.path.join("/", "..") == "/":
        #If parent==path, then path is root
        if required:
            raise Exception("No git directory")
        else:
            return None

    # Recursive case
    return repo_find(parent, required)



"""
Objects in Git: Common commands first
    hash-object: converts an existing file into a git object
    cat-file: prints an existing git object to the standard output

Git filenames are not arbitrary.
A filename stored in git is stored with a name which is mathematically derived from its contents.
A single byte change in a file will change its internal name.
Paths are detemrined by the contents of the files.

Commits, tags, blobs, and trees are objects as well, along with most things stored in Git, except for a few exceptions.

The path where an object is stored is computed by calculating the SHA-1 of its contents.
"""


# Let's define some abstraction since all the objects have the same storage/retrieval mechanism

class GitObject(object):

    def __init__(self, data=None):
        if data != None:
            self.deserialize(data)
        else:
            self.init()

    def serialize(self, repo):
        """This funciton MUST be implemented byb subclasses.
        It must read the object's contents from self.data, a byte string, and do whatever it takes
        to convert it into a meaninful representation.
        What exactly that means depends on each subclass."""
        raise Exception("Unimplemented!")


    def deserialize(self, data):
        raise Exception("Unimplemented!")

    def init(self):
        pass # do nothing. a reasonable default



# Reading objects

"""
To read an object, we need its SHA-1 hash. We then compute its path from this hash:
    first two characters, then a directory delimiter "/", then the ramining part,
    and look it up inside of the "objects" directory in the gitdir.

    Then we read that file as a binary file and decompress it using zlib.

"""

def object_read(repo, sha):
    """Read object sha from Git repository repo.
    Return a GitObject whose exact type depends on the object"""

    path = repo_file(repo, "objects", sha[0:2], sha[2:])

    if not os.path.isfile(path):
        return None

    with open (path, "rb") as f:
        raw = zlib.decompress(f.read())

        # Read object type
        x = raw.find(b'')
        fmt = raw[0:x]

        # Read and validate object size
        y = raw.find(b'\x00', x)
        size = int(raw[x:y].decode("ascii"))
        if size != len(raw)-y-1:
            raise Exception("Malformed object {0}: bad length".format(sha))

        #Pick constructor
        match fmt:
            case b'commit'  : c=GitCommit
            case b'tree'    : c=GitTree
            case b'tag'     : c=GitTag
            case b'blob'    : c=GitBlob
            case _:
                raise Exception("Unknown type {0} for object {1}".format(fmt.decode("ascii"), sha))

        #Call constructir and return object
        return c(raw[y+1:])



# Writing objects

"""
Writing an object is reading it in reverse: we compute the hash, insert the header, zlib-compress everything
and write the result in the correct location.

"""

def object_write(obj, repo=None):
    # Serialize object data
    data = obj.serialize()
    # Add header
    result = obj.fmt +b' ' + str(len(data)).encode() + b'\x00' + data
    # Compute hash
    sha = hashlib.sha1(result).hexdigest()

    if repo:
        # Compute path
        path=repo_file(repo, "objects", sha[0:2], sha[2:], mkdir=True)

        if not os.path.exists(path):
            with open(path, 'wb') as f:
                #Compress and write
                f.write(zlib.compress(result))
    return sha



# Let's get into blobs

"""
Blobs are the simplest of the four types of objects (blob, commit, tag, tree), because they have no actual format.

Blobs are user data:
    the content of every file you put in git (main.c, logo.png, RADME.md) is stored as a blob.
    That makes them easy to manipulate, because they have no actual syntax or contraints beyond the basic object storage mechanism.

Creating a GitBlob class is thus trivial, the serialize and deserialize functions just have to store and return their input unmodified
"""

class GitBlob(GitObject):
    fmt=b'blob'

    def serialize(self):
        return self.blobdata

    def deserialize(self, data):
        self.blobdata = data


"""
Let's now create the cat-file command to simply print the raw contents of an object to stdout.
(uncompressed without the git header)
"""

# Here is the subparser

argsp = argsubparsers.add_parser("cat-file", help="Provide content of repository objects")

argsp.add_argument("type",
                    metavar="type",
                    choices=["blob", "commit", "tag", "tree"],
                    help="Specify the type")

argsp.add_argument("object", metavar="object", help="The object to display")


def cmd_cat_file(args):
    repo = repo_find()
    cat_file(repo, args.object, fmt=args.type.encode())

def cat_file(repo, obj, fmt=None):
    obj = object_read(repo, object_find(repo, obj, fmt=fmt))
    sys.stdout.buffer.write(obj.serialize())


def object_find(repo, name, fmt=None, follow=True):
    sha = object_resolve(repo, name)

    if not sha:
        raise Exception("No such reference {0}.".format(name))

    if len(sha) > 1:
        raise Exception("Ambiguous reference {0}: Candidates are:\n - {1}.".format(name, "\n - ".join(sha)))

    sha = sha[0]

    if not fmt:
        return sha

    while True:
        obj = object_read(repo, sha)
        # This is not optimized for performance
        if obj.fmt == fmt:
            return sha

        if not follow:
            return None

        # Follow tags
        if obj.fmt == b'tag':
            sha = obj.kvlm[b'object'].decode("ascii")
        elif obj.fmt == b'commit' and fmt == b'tree':
            sha = obj.kvlm[b'tree'].decode("ascii")
        else:
            return None



# Hash-object command

argsp = argsubparsers.add_parser(
        "hash-object",
        help="Compute object ID and optionally creates a blob from a file")

argsp.add_argument("-t",
                    metavar="type",
                    dest="type",
                    choices=["blob", "commit", "tag", "tree"],
                    default="blob",
                    help="Specify the type")

argsp.add_argument("-w",
                    dest="write",
                    action="store_true",
                    help="Actually write the object into the database")

argsp.add_argument("path", help="Read object from <file>")


def cmd_hash_object(args):
    if args.write:
        repo = repo_find()
    else:
        repo = None

    with open(args.path, "rb") as fd:
        sha = object_hash(fd, args.type.encode(), repo)
        print(sha)



def object_hash(fd, fmt, repo=None):
    """Hash object, writing it to repo if provided"""
    data = fd.read()

    #Choose contructor according to fmt argument
    match fmt:
        case b'commit'  : obj=GitCommit(data)
        case b'tree'    : obj=GitTree(data)
        case b'tag'     : obj=GitTag(data)
        case b'blob'    : obj=GitBlob(data)
        case _:
            raise Exception("Unknown type %s!" % fmt)

    return object_write(obj, repo)



# Parsing commits

"""
We start by writing a simple parser for the format.
kvlm means key-value list with message and will be used to parse the commit
"""

def kvlm_parse(raw, start=0, dct=None):
    if not dct:
        dct = collections.OrderedDict()
        # You cannot declare the argument as dct=OrderedDict() ot all calls to the function will endlessly grow the same dict

    # This function is recursive: it reads a key/value pair, then calls
    # itself back with the new position. So we first need to know where we are: at a keyword, or already in the messageQ

    # We search for the next space and the next newline
    spc = raw.find(b' ', start)
    nl = raw.find(b'\n', start)

    """
    If space appears before newline, we have a keyword.
    Otherwise, it's the final message, which we just read to the end of the file.

    Base case
    ===========
    If newline appears first (or there's no space at all, in which case "find" returns -1, we assume a blank line.
    A blank line means the remainder of the data is the message.
    We store it in the dictionary, with None as the key, and return.
    """
    if (spc < 0) or (nl > spc):
        assert nl == start
        dct[None] = raw[start+1:]
        return dct

    # Recursive case: we read a key-value pair and recurse for the next
    key = raw[start:spc]

    # Find the end of the value. Continuation lines begin with a space, so we loop until we find a "\n" not followed by a space.
    end = start
    while True:
        end = raw.find(b'\n', end+1)
        if raw[end+1] != ord(' '): break

    # Grab the vlue and drop the leading space on continuation lines
    value = raw[spc+1:end].replace(b'\n ', b'\n')

    # Don't overwrite existing data contents
    if key in dct:
        if type(dct[key]) == list:
            dct[key].append(value)
        else:
            dct[key] = [ dct[key], value ]
    else:
        dct[key]=value

    return kvlm_parse(raw, start=end+1, dct=dct)




def kvlm_serialize(kvlm):
    ret = b''

    # Output fields
    for k in kvlm.keys():
        # skip the message itself
        if k == None: continue
        val = kvlm[k]
        # normalize to a list
        if type(val) != list:
            val = [ val ]

        for v in val:
            ret += k + b' ' + (v.replace(b'\n', b'\n ')) + b'\n'

    # Append message
    ret += b'\n' + kvlm[None] + b'\n'

    return ret


# The commit object

class GitCommit(GitObject):
    fmt=b'commit'

    def deserialize(self, data):
        self.kvlm = kvlm_parse(data)

    def serialize(self):
        return kvlm_serialize(self.kvlm)

    def init(self):
        self.kvlm = dict()


# The log command -- simplified

argsp = argsubparsers.add_parser("log", help="Display history of a given commit")
argsp.add_argument("commit", default="HEAD", nargs="?", help="Commit to start at.")


def cmd_log(args):
    repo = repo_find()

    print("diagraph wyaglog{")
    print(" node[shape=rect]")
    log_graphviz(repo, object_find(repo, args.commit), set())
    print("}")


def log_graphviz(repo, sha, seen):

    if sha in seen:
        return
    seen.add(sha)

    commit = object_read(repo, sha)
    short_hash = sha[0:8]
    message = commit.kvlm[None].decode("utf-8").strip()
    message = message.replace("\\", "\\\\")
    message = message.replace("\"", "\\\"")

    if "\n" in message: # Keep only the first line
        message = message[:message.index("\n")]

    print(" c_{0} [label=\"{1}: {2}\"]".format(sha, sha[0:7], message))
    assert commit.fmt==b'commit'

    if not b'parent' in commit.kvlm.keys():
        # Base case: the initial commit
        return

    parents = commit.kvlm[b'parent']

    if type(parents) != list:
        parents = [ parents ]

    for p in parents:
        p = p.decode("ascii")
        print (" c_{0} -> c_{1};".format(sha, p))
        log_graphviz(repo, p, seen)



# Reading commit data


class GitTreeLeaf(object):
    def __init__(self, mode, path, sha):
        self.mode = mode
        self.path = path
        self.sha = sha



"""
Because a tree object is the repetition of the same fundamental data structure,
we write the parser in two functions. 

First, a parser to extract a single record, which returns parsed data and the position it reached in input data.

And then, the "real" parser which just calls the previous one in a loop, until input data is exhausted.

"""

def tree_parse_one(raw, start=0):
    #Find the space terminator of the mode
    x = raw.find(b' ', start)
    assert x-start == 5 or x-start==6

    # Read the mode
    mode = raw[start:x]
    if len(mode) == 5:
        # Normalize to six bytes
        mode = b" " + mode

    # Find the Null terminator of the path
    y = raw.find(b'\x00', x)
    # and read the path
    path = raw[x+1:y]

    # Read the SHA
    raw_sha = int.from_bytes(raw[y+1:y+21], "big")
    # and convert it into a hex string, padded to 40 chars
    # with zeros if needed (in padding)
    sha = format(raw_sha, "040x")
    return y+21, GitTreeLeaf(mode, path.decode("utf8"), sha)




def tree_parse(raw):
    pos = 0
    max = len(raw)
    ret = list()
    while pos < max:
        pos, data = tree_parse_one(raw, pos)
        ret.append(data)

    return ret



"""
Next we need an ordering function to ensure that when we add or modify entries, they are sorted.
This is to respect git's identity rules, which states that no two equivalent objects can have a different hash,
but differently sorted trees with the same contents would be equivalent (describing the same directory structure), 
and still numerically distinct (different SHA-1 identifiers).

"""

def tree_leaf_sort_key(leaf):
    if leaf.mode.startswith(b"10"):
        return leaf.path
    else: 
        return leaf.path + "/"

# Next is the serializer that sorts the items using the newly created function as a transformer

def tree_serialize(obj):
    obj.items.sort(key=tree_leaf_sort_key)
    ret = b''
    for i in obj.items:
        ret += i.mode
        ret += b' '
        ret += i.path.encode("utf8")
        ret += b'\x00'
        sha = int(i.sha, 16)
        ret += sha.to_bytes(20, byteorder="big")
    return ret

# Now lets combine both these functions into the GitTree class

class GitTree(GitObject):
    fmt=b'tree'

    def deserialize(self, data):
        self.items = tree_parse(data)

    def serialize(self):
        return tree_serialize(self)

    def init(self):
        self.items = list()




# Now onto the ls-tree command.
# This command simply prints the contents of a tree, recursively with the -r flag

argsp = argsubparsers.add_parser("ls-tree", help="Pretty-print a tree object")
argsp.add_argument("-r", dest="recursive", action="store_true", help="Recurse into subtrees")

argsp.add_argument("tree", help="A tree-ish object")

def cmd_ls_tree(args):
    repo = repo_find()
    ls_tree(repo, args.tree, args.recursive)


def ls_tree(repo, ref, recursive=None, prefix=""):
    sha = object_find(repo, ref, fmt=b"tree")
    obj = object_read(repo, sha)
    for item in obj.items:
        if len(item.mode) == 5:
            type = item.mode[0:1]
        else:
            type = item.mode[0:2]


        match type: # Determine the type
            case b'04': type = "tree"
            case b'10': type = "blob" # A regular file
            case b'12': type = "blob" # A symlink. blob contents is link target
            case b'16': type = "commit" # a submodule
            case _:
                raise Exception("Weird tree leaf mode {}".format(item.mode))

        if not (recursive and type=='tree'): # This is a leaf
            print("{0} {1} {2}\t{3}".format(
                "0" * (6 - len(item.mode)) + item.mode.decode("ascii"),
                # Git's ls-tree displays the type
                # of the object pointed to. Lets do that as well
                type,
                item.sha,
                os.path.join(prefix, item.path)))
        else: # This is a branch, recurse
            ls_tree(repo, item.sha, recursive, os.path.join(prefix, item.path))



# The checkout command

"""
This command simply instantiates a commit in the worktree.
We are going to take in two arguments:
    - a commit
    - a directory

After this, the command will then instantiate the tree in the directory, if and only if the directory is empty.
Git is full of safeguards to avoid deleting data, whoch would be too complicated and unsafe to try and reproduce in wyag.
Since the point of this project is to demonstrate git, not to produce a working implementation, the limitation is acceptable,
for now.
"""

# As usual, we will need a subparser for the command

argsp = argsubparsers.add_parser("checkout", help="Checkout a commit inside of a directory")

argsp.add_argument("commit", help="The commit or tree to checkout")

argsp.add_argument("path", help="The EMPTY directory to checkout on")

# Now let's write the wrapper function for the command

def cmd_checkout(args):
    repo = repo_find()

    obj = object_read(repo, object_find(repo, args.commit))

    # If the object is a commit, we grab its tree
    if obj.fmt == b'commit':
        obj = object_read(repo, obj.kvlm[b'tree'].decode("ascii"))

    # Verify that path is an empty directory
    if os.path.exists(args.path):
        if not os.path.isdir(args.path):
            raise Exception("Not a directory {0}!".format(args.path))
        if os.listdir(args.path):
            raise Exception("Not empty {0}!".format(args.path))
    else:
        os.makedirs(args.path)

    tree_checkout(repo, obj, os.path.realpath(args.path))


# Now the function that does the actual checkout

def tree_checkout(repo, tree, path):
    for item in tree.items:
        obj = object_read(repo, item.sha)
        dest = os.path.join(path, item.path)

        if obj.fmt == b'tree':
            os.mkdir(dest)
            tree_checkout(repo, obj, dest)
        elif obj.fmt == b'blob':
            # @TODO Support symlinks (identified by mode 12)
            with open(dest, 'wb') as f:
                f.write(obj.blobdata)








"""
Git refs:
    they are inside the subdirectories of .git/refs, and are text files containing a
    hexadecimal representation of an object's hash, encoded in ASCII


To work with refs, we will need a simple recursive solver that will take a ref name as input, 
follow eventual recursive references and return a SHA-1 identifier
"""

def ref_resolve(repo, ref):
    path = repo_file(repo, ref)

    if not os.path.isfile(path):
        return None

    with open(path, 'r') as fp:
        data = fp.read()[:-1]
        # Drop final \n
    if data.startswith("ref: "):
        return ref_resolve(repo, data[5:])
    else:
        return data



# The following are two funtions to implement the show-refs command

def ref_list(repo, path=None):
    if not path:
        path = repo_dir(repo, "refs")
    ret = collections.OrderedDict()

    for f in sorted(os.listdir(path)):
        can = os.path.join(path, f)
        if os.path.isdir(can):
            ret[f] = ref_list(repo, can)
        else:
            ret[f] = ref_resolve(repo, can)

    return ret

# Next is the subparser, bridge and a recursive worker function to implement this command

argsp = argsubparsers.add_parser("show-ref", help="List references")

def cmd_show_ref(args):
    repo = repo_find()
    refs = ref_list(repo)
    show_ref(repo, refs, prefix="refs")


def show_ref(repo, refs, with_hash=True, prefix=""):
    for k, v in refs.items():
        if type(v) == str:
            print ("{0}{1}{2}".format(
                v + " " if with_hash else "",
                prefix + "/" if prefix else "",
                k))
        else:
            show_ref(repo, v, with_hash=with_hash, prefix="{0}{1}{2}".format(prefix, "/" if prefix else "". k))



"""
The most simple use of refs is tags.
A tag is a user-defined name for an object, often a commit.

A very common use of tags is to identify software releases:
    After merging the last commit of a program version you tag it to identify it useing a command like so:
    " git tag v12.1.1 "commit hash" "

Tagging is like aliasing, in the way that you can now have two ways to refer to the commit, using the tag and its hash.

So, to view the commit you can use both:
    git checkout "commit hash"
    and
    git checkout v12.1.1


For a little mor einsight, remember that tags come in two flavors:
    lightweight tags
    tags objects

Lightweight tags - regular refs to a commit, a tree or a blob.

Tag objects - regular refs pointing to an object of type tag:
    Unlike lightweight tags, tag objects have an author, a date, an optional PGP signature and an optional annotation.
    Their format is the same as a commit object.
"""
# Reusing GitCommit and just chanigng the fmt field:
class GitTag(GitCommit):
    fmt = b'tag'
#now we also support tags


# The tag command

argsp = argsubparsers.add_parser("tag", help="List and create tags")

argsp.add_argument("-a",
                    action="store_true",
                    dest="create_tagobject",
                    help="Wether to create a tag object")

argsp.add_argument("name", nargs="?", help="The new tag's name")

argsp.add_argument("object",
                    default="HEAD",
                    nargs="?",
                    help="The object the new tag will point to")


def cmd_tag(args):
    repo = repo_find()

    if args.name:
        tag_create(repo,
                    args.name,
                    args.object,
                    type="object" if args.create_tag_objet else "ref")

    else:
        refs = ref_list(repo)
        show_ref(repo, refs["tags"], with_hash=False)


def tag_create(repo, name, ref, create_tag_object=False):
    # get the GitObject from the object referene
    sha = object_find(repo, ref)

    if create_tag_object:
        # create tag object (commit)
        tag = GitTag(repo)
        tag.kvlm = collections.OrderedDict()
        tag.kvlm[b'object'] = sha.encode()
        tag.kvlm[b'type'] = b'commit'
        tag.kvlm[b'tag'] = name.encode()
        tag.kvlm[b'tagger'] = b'Wyag <joggabigga@yommomma.com>'
        tag.kvlm[None] = b"A tag generated by wyag, which won't let you customize the message!"
        tag_sha = object_write(tag)
        # create reference
        ref_create(repo, "tags/" + name, tag_sha)
    else:
        # create lightweight tag (ref)
        ref_create(repo, "tags/" + name, sha)


def ref_create(repo, ref_name, sha):
    with open(repo_file(repo, "refs/" + ref_name), 'w') as fp:
        fp.write(sha + "\n")



#Branches

"""
Simply put:
    A branch is a reference to a commit.

In this regard, a branch is comparatively the same thing as a tag. As in, tags are refs that live in .git/refs/tags,
branches are refs that live in .git/refs/heads.

Branches are references to a cmmit, tags can refer to any object

The branch ref is updated at each commit. This means that whenever you commit, Git does this:
    A new commit object is created, with the current branch's (commit) ID as its parent;
    The commit object is hashed and stored:
    The branch ref is updated to refer to the new commit's hash.


Note: Detached HEAD:
    When you checkout a random commit, git will warn you it's in "detached HEAD state".
    This means you're not on any branch anymore.
    In this case, .git/HEAD is a direct reference: it contains a SHA-1
"""


# Resolving objects: in case object_find, finds objects with short hashes, these will be resolved to safely return a result 
# Error is raised if we find more than one correspondence to the short hash

def object_resolve(repo, name):
    """ Resolve name to an object hash in repo:

    This function will be aware of:
    - The HEAD literal
        - short and long hashes
        - tags
        - branches
        - remote branches
    """
    candidates = list()
    hashRE = re.compiler(r"^[0-0A-Fa-f]{4,40}$")

    # Empty string? abort
    if not name.strip():
        return None

    # Head is nonambiguous
    if name == "HEAD":
        return [ ref_resolve(repo, "HEAD") ]

    # If it's a hex string, try for a hash.
    if hashRE.match(name):
        name = name.lower()
        prefix = name[0:2]
        path = repo_dir(repo, "objects", prefix, mkdir=False)
        if path:
            rem = name[2:]
            for f in os.listdir(path):
                if f.startswith(rem):
                    candidates.append(prefix + f)

    # Try for references
    as_tag = ref_resolve(repo, "refs/tags/" + name)
    if as_tag: # was a tag found?
        candidates.append(as_tag)


    as_branch = ref_resolve(repo, "refs/heads/" + name)
    if as_branch: # was a branch found?
        candidates.append(as_branch)

    return candidates


"""
Now we need to follow the object we foind to an object of the required type, if a type argument was provided.
Since we only handle trivial cases, the process is as follows:
    - if we have a tag and fmt is anything else, we follow the tag
    - if we have a commit and fmt is tree, we return this commit's tree object
    - in all other situations, we bail out: no other situation makes sense

    Please check the previously defined function object_find (way above)
"""

# The rev-parse command

#parser
argsp = argsubparsers.add_parser("rev-parse", help="Parse revision (or other objects) identifiers")

argsp.add_argument("--wyag-type",
                    metavar="type",
                    dest="type",
                    choices=["blob", "commit", "tag", "tree"],
                    default=None,
                    help="Specify the expected type")

argsp.add_argument("name", help="The name to parse")

#Bridge

def cmd_rev_parse(args):
    if args.type:
        fmt = args.type.encode()
    else:
        fmt = None

    repo = repo_find()

    print (object_find(repo, args.name, fmt, follow=True))



"""
The index file

To commit in git, we first "stage" some changes using git add and git rm, and only then do we commit those changes.
This intermediate stage between the last and the next commit is called the staging area.

To represent the staging area Git uses a mechanism called the index file.

After a commit, the index file is a sort of copy of that commit:
    it holds the same path/blob association as the corresponding tree.
    It also holds extra info about files in the worktree, like their creation/modification time,
    so git status doesn't often need to actually compare files:
        It just checks their modification time is the same as the one stored in the index file,
        and only if it isn't does it perform an actual comparison.

You can thus consider the index file as a three-way association list:
    not only paths with blobs, but also paths with actual filesystem entries.

Another important characteristic of the index file is that unlike a tree,
it can represent inconsistent states, like a merge conflict,
whereas a tree is always a complete, unambiguous representation.

When we commit, git turns the index file into a new tree object.

Summarising:
    - When the repository is "clean", the index file holds the exact same contents as the HEAD commit,
    plus metadata about the corresponidng filesystem entries.

    - When we use git add or git rm, the index file is modified accordingly.
    - When we use git commit for those changes, a new tree is produced from the index file,
    a new commit object is generated with that tree, branches are updated and we are done.

Index file = Staging area

Index file is made of three parts:
    - A header with the format version number and the number of entries the index holds;
    - a series of entries, sorted, each representing a file; padded to multiples of 8 bytes;
    - a series of optional extensions, which we'll ignore

"""

class GitIndexEntry(object):
    def __init__(self, ctime=None, mtime=None, dev=None, ino=None,
            mode_type=None, mode_perms=None, uid=None, gid=None,
            fsize=None, sha=None, flag_assume_valid=None,
            flag_stage=None, name=None):
        # The last time a file's metadata changed
        self.ctime = ctime
        # The last time a file's data changed
        self.mtime = mtime
        # The ID of device containing this file
        self.dev = dev
        # The file's inode number
        self.ino = ino
        # The object type, either b1000 (regular), b1010(symlink), or b1110(gitlink)
        self.mode_type = mode_type
        # The object permissions, an int
        self.mode_perms = mode_perms
        # User ID of owner
        self.uid = uid
        # Group ID of owner
        self.gid = gid
        # Size of this object, in bytes
        self.fsize = fsize
        # The object's SHA
        self.sha = sha
        self.flag_assume_valid = flag_assume_valid
        self.flag_stage = flag_stage
        # Name of the object (full path this time!)
        self.name = name




class GitIndex(object):
    version = None
    entries = []
    # ext = None
    # sha = None

    def __init__(self, version=2, entries=None):
        if not entries:
            entries = list()

        self.version = version
        self.entries = entries




# Now we need a parser to read index files into the entries objects.
# After reading the 12-bytes header, we parse entries in the order they appear
# An entry begins with a set of fixed-length data, followed by a variable length name

def index_read(repo):
    index_file = repo_file(repo, "index")

    # New repositories have no index
    if not os.path.exists(index_file):
        return GitIndex()

    with open(index_file, 'rb') as f:
        raw = f.read()

    header = raw[:12]
    signature = header[:4]
    assert signature == b"DIRC" # stands for DirCache
    version = int.from_bytes(header[4:8], "big")
    assert version == 2, "wyag only supports index file version 2"
    count = int.from_bytes(header[8:12], "big")

    entries = list()

    content = raw[12:]
    idx = 0
    for i in range(0, count):
        # read creation time, as a unix timestamp
        ctime_s = int.from_bytes(content[idx: idx+4], "big")
        # read creation time, as nanoseconds after that timestamp for extra precision
        ctime_ns = int.from_bytes(content[idx+4: idx+8], "big")
        # same for modification time: first seconds from epoch
        mtime_s = int.from_bytes(content[idx+8: idx+12], "big")
        # extra nanoseconds
        mtime_ns = int.from_bytes(content[idx+12: idx+16], "big")
        # device ID
        dev = int.from_bytes(content[idx+16: idx+20], "big")
        # Inode
        ino = int.from_bytes(content[idx+20: idx+24], "big")
        # Ignored
        unused = int.from_bytes(content[idx+24: idx+26], "big")
        assert 0 == unused
        mode = int.from_bytes(content[idx+26: idx+28], "big")
        mode_type = mode >> 12
        assert mode_type in [0b1000, 0b1010, 0b1110]
        mode_perms = mode & 0b0000000111111111
        # User ID
        uid = int.from_bytes(content[idx+28: idx+32], "big")
        # Group ID
        gid = int.from_bytes(content[idx+32: idx+36], "big")
        # Size
        fsize = int.from_bytes(content[idx+36: idx+40], "big")
        # SHA (object ID) We'll store it as a lowercase hex string
        sha = format(int.from_bytes(content[idx+40: idx+60], "big"), "040x")
        # Flags we're going to ignore
        flags = int.from_bytes(content[idx+60: idx+62], "big")
        # Parse flags
        flag_assume_valid = (flags & 0b1000000000000000) != 0
        flag_extended = (flags & 0b0100000000000000) != 0
        assert not flag_extended
        flag_stage = flags & 0b0011000000000000
        # Length of the name.  This is stored on 12 bits, some max
        # value is 0xFFF, 4095.  Since names can occasionally go
        # beyond that length, git treats 0xFFF as meaning at least
        # 0xFFF, and looks for the final 0x00 to find the end of the
        # name --- at a small, and probably very rare, performance
        # cost.
        name_length = flags & 0b0000111111111111
       
       # We have read 62 bytes so far
        idx += 62

        if name_length < 0xFFF:
            assert content[idx + name_length] == 0x00
            raw_name = content[idx:idx+name_length]
            idx += name_length + 1
        else:
            print("Notice: Name is 0x{:X} bytes long".format(name_length))
            # this was not tested enough, be careful with name length
            null_idx = content.find(b'\x00', idx + 0xFFF)
            raw_name = content[idx: null_idx]
            idx = null_idx + 1

        # Parse the name as utf8
        name = raw_name.decode("utf8")

        # Data is pade on multiples of 8 bytes for pointer alignment, 
        # so we skip as many bytes as we need for the next read to start at correct position

        idx = 8 * ceil(idx / 8)

        # Add the entry to our list
        entries.append(GitIndexEntry(ctime=(ctime_s, ctime_ns),
                                    mtime=(mtime_s, mtime_ns),
                                    dev=dev,
                                    ino=ino,
                                    mode_type=mode_type,
                                    mode_perms=mode_perms,
                                    uid=uid,
                                    gid=gid,
                                    fsize=fsize,
                                    sha=sha,
                                    flag_assume_valid=flag_assume_valid,
                                    flag_stage=flag_stage,
                                    name=name))

        return GitIndex(version=version, entries=entries)



# Onto the ls-files command

"""
The ls-files displays the names of files in the staging area.
Usually it has a lot of subcommands/options, but we will just add --verbose (not in Git)
"""

argsp = argsubparsers.add_parser("ls-files", help="List all the stage files")
argsp.add_argument("--verbose", action="store_true", help="Show everything")

def cmd_ls_files(args):
    repo = repo_find()
    index = index_read(repo)
    if args.verbose:
        print("Index file format v{}, containing {} entries".format(index.version, len(index.entries)))


    for e in index.entries:
        print(e.name)
        if args.verbose:
            print(" {} with perms: {:o}".format(
                { 0b1000: "regular file",
                  0b1010: "symlink",
                  0b1110: "git link"}[e.mode_type],
                e.mode_perms))
            print(" on blob: {}".format(e.sha))
            print(" created: {}.{}, modified: {}.{}".format(
                datetime.formtimestamp(e.ctime[0]),
                e.ctime[1],
                datetime.fromtimestamp(e.mtime[0]),
                e.mtime[1]))
            print(" device: {}, inode: {}".format(e.dev, e.ino))
            print(" user: {} ({}) group: {} ({})".format(
                pwd.getpwuid(e.uid).pw_name,
                e.uid,
                grp.getgrgid(e.gid).gr_name,
                e.gid))
            print(" flags: stage={} assume_valid={}".format(
                e.flag_stage,
                e.flag_assume_valid))



"""
If we want to implement the status command, we first need the ignore command,
to ignore rules that are stored in the various .gitignore files.
So we will need to add some rudimentary support for ignore files in wyag.

We will expose this support as the check-ignore command, 
which takes a list of paths and outputs back those paths that should be ignored
"""

# command parser

argsp = argsubparsers.add_parser("check-ignore", help="Check path(s) against ignore rules")
argsp.add_argument("path", nargs="+", help="Paths to check")

def cmd_check_ignore(args):
    repo = repo_find()
    rules = gitignore_read(repo)
    for path in args.path:
        if check_ignore(rules, path):
            print(path)


"""
 now we need a reader for rules in ignore files, gitignore_read()
 The syntax of those rules is simple: 

     each line in an ignore file is an exclusion patter
     files that match this pattern are ignored by status, add -A and so on

There are 3 special cases:
    - lines that begin with "!" negate the pattern
    - lines that begin with "#" are comments, and are skipped
    - a backlash "\" at the beginning treats ! and # as literal charachters


"""

def gitignore_parse1(raw):
    raw = raw.strip() # remove leading/trailing spaces

    if not raw or raw[0] == '#':
        return None
    elif raw[0] == "!":
        return (raw[1:], False)
    elif raw[0] == "\\":
        return (raw[1:], True)
    else:
        return (raw, True)


def gitignore_parse(lines):
    ret = list()

    for line in lines:
        parsed = gitignore_parse1(line)
        if parsed:
            ret.append(parsed)

    return ret



#Now we need to collect the various ignore files

class GitIgnore(object):
    absolute = None
    scoped = None

    def __init__(self, absolute, scoped):
        self.absolute = absolute
        self.scoped = scoped



def gitignore_read(repo):
    ret = GitIgnore(absolute=list(), scoped=dict())

    # Read local config in .git/info/exclude
    repo_file = os.path.join(repo.gitdir, "info/exclude")
    if os.path.exists(repo_file):
        with open(repo_file, "r") as f:
            ret.absolute.append(gitignore_parse(f.readlines()))

    # Global configuration
    if "XDG_CONFIG_HOME" in os.environ:
        config_home = os.environ["XDG_CONFIG_HOME"]
    else:
        config_home = os.path.expanduser("~/.config")
    global_file = os.path.join(config_home, "git/ignore")

    if os.path.exists(global_file):
        with open(global_file, "r") as f:
            ret.absolute.append(gitignore_parse(f.readlines()))


    # .gitignore files in the index
    index = index_read(repo)

    for entry in index.entries:
        if entry.name == ".gitignore" or entry.name.endswith("/.gitignore"):
            dir_name = os.path.dirname(entry.name)
            contents = object_read(repo, entry.sha)
            lines = contents.blobdata.decode("utf8").splitlines()
            ret.scoped[dir_name] = gitignore_parse(lines)
    return ret


"""
Now we need a function that ties everything together and matches a path, relative to the root of a worktree, against a set of rules.

This is how the function will work:
    - It will first try to match this path against the scoped rules
    It will do this from the deepest parent of the path to the farthest.
    
    - If nothing matches, it will continue with the absolute rules

We will write 3 small support functions:
    - One to match a path against a set of rules, and return the result of the last matching rule

    - Another to match against the dictionary of scoped rules.

    - And another to match against the list of absolute rules
"""

def check_ignore1(rules, path):
    result = None
    for (pattern, value) in rules:
        if fnmatch(path, pattern):
            result = value
    return result


def check_ignore_scoped(rules, path):
    parent = os.path.dirname(path)
    while True:
        if parent in rules:
            result = check_ignore1(rules[parent], path)
            if result != None:
                return result
        if parent == "":
            break
        parent = os.path.dirname(parent)
    return None


def check_ignore_absolute(rules, path):
    parent = os.path.dirname(path)
    for ruleset in rules:
        result = check_ignore1(ruleset, path)
        if result != None:
            return result
    return False # reasonable default?

# Now the function to bind them all (one ring to rule them all)

def check_ignore(rules, path):
    if os.path.isabs(path):
        raise Exception("This function requires path to be relative to the repository's root")
    
    result = check_ignore_scoped(rules.scoped, path)
    if result != None:
        return result

    return check_ignore_absolute(rules.absolute, path)


# This is not a perfect re-implementation of the ignore mechanism in git but it will suffice


# Onto the status command

"""
Status is more complex than ls-files.

Status needs to compare the index with both HEAD and the actual filesystem.

When we call git status we are shown which files were added, removed, or modified since the last commit,
and which of these changes are actually staged, and make it to the next commit.

So, status compares the HEAD with the staging area, and the staging area with the worktree.


We will implement status in three parts:
    - first the active branch or "detached HEAD"
    - then the difference between the index and the worktree
    - then the difference between HEAD and the index ("Changes to be committed" and "Untracked files")

"""

argsp = argsubparsers.add_parser("status", help="Show the working tree status")

def cmd_status(_):
    repo = repo_find()
    index = index_read(repo)

    cmd_status_branch(repo)
    cmd_status_head_index(repo, index)
    print()
    cmd_status_index_worktree(repo, index)


# function to find the active branch

def branch_get_active(repo):
    with open(repo_file(repo, "HEAD"), "r") as f:
        head = f.read()

    if head.startswith("ref: refs/heads/"):
        return(head[16:-1])
    else:
        return False

# Function to print the name of the active branch

def cmd_status_branch(repo):
    branch = branch_get_active(repo)
    if branch:
        print("On branch {}".format(branch))
    else:
        print("Head detached at {}".format (object_find(repo, "HEAD")))



#Finding changes between HEAD and index

# First a function to convert a tree to a flat dict

# it will be a recursive function, since trees are recursive

def tree_to_dict(repo, ref, prefix=""):
    ret = dict()
    tree_sha = object_find(repo, ref, fmt=b"tree")
    tree = object_read(repo, tree_sha)

    for leaf in tree.items:
        full_path = os.path.join(prefix, leaf.path)

        is_subtree = leaf.mode.startswith(b'04')

        if is_subtree:
            ret.update(tree_to_dict(repo, leaf.sha, full_path))
        else:
            ret[full_path] = leaf.sha

    return ret


def cmd_status_head_index(repo, index):
    print("Changes to be committed:")

    head = tree_to_dict(repo, "HEAD")
    for entry in index.entries:
        if entry.name in head:
            if head[entry.name] != entry.sha:
                print(" modified:", entry.name)
            del head[entry.name] # Delete the key
        else:
            print(" added: ", entry.name)

    # Keys still in HEAD are files that we have not met in the index, and thus have been deleted
    for entry in head.keys():
        print(" deleted: ", entry)



# Finding changes between index and worktree

def cmd_status_index_worktree(repo, index):
    print("Changes not staged for commit:")

    ignore = gitignore_read(repo)

    gitdir_prefix = repo.gitdir + os.path.sep

    all_files = list()

    # We begin by walking the filesystem
    for (root, _, files) in os.walk(repo.worktree, True):
        if root==repo.gitdir or root.startswith(gitdir_prefix):
            continue
        for f in files:
            full_path = os.path.join(root, f)
            rel_path = os.path.relpath(full_path, repo.worktree)
            all_files.append(rel_path)

    # Now we traverse the index, and compare real files with cached versions
    for entry in index.entries:
        full_path = os.path.join(repo.worktree, entry.name)

        # That file *name* is in the index

        if not os.path.exists(full_path):
            print(" deleted: ", entry.name)
        else:
            stat = os.stat(full_path)

            # Compare metadata
            ctime_ns = entry.ctime[0] * 10**9 + entry.ctime[1]
            mtime_ns = entry.mtime[0] * 10**9 + entry.mtime[1]
            if (stat.st_ctime_ns != ctime_ns) or (stat.st_mtime_ns != mtime_ns):
                # if different, deep compare
                # @FIXME this will crash on symlinks to dir
                with open(full_path, "rb") as fd:
                    new_sha = object_hash(fd, b"blob", None)
                    # If the hashes are the same, the files are the same
                    same = entry.sha == new_sha

                    if not same:
                        print(" modified:", entry.name)

        if entry.name in all_files:
            all_files.remove(entry.name)

    print()
    print("Untracked files:")

    for f in all_files:
        # @TODO if a full directory is untracked, we should display its name without its contents
        if not check_ignore(ignore, f):
            print(" ", f)


"""
To be able to create commits we now need commands to modify the index.
These commands are add and rm.

The commands need to write the modified index back, since we commit from the index.

We also need the commit function and its associated wyag commit command.
"""

def index_write(repo, index):
    with open(repo_file(repo, "index"), "wb") as f:

        # HEADER

        # Write the magic bytes
        f.write(b"DIRC")
        # Write version number
        f.write(index.version.to_bytes(4, "big"))
        # Write the number of entries
        f.write(len(index.entries).to_bytes(4, "big"))

        # Entries

        idx = 0
        for e in index.entries:
            f.write(e.ctime[0].to_bytes(4, "big"))
            f.write(e.ctime[1].to_bytes(4, "big"))
            f.write(e.mtime[0].to_bytes(4, "big"))
            f.write(e.mtime[1].to_bytes(4, "big"))
            f.write(e.dev.to_bytes(4, "big"))
            f.write(e.ino.to_bytes(4, "big"))

            # Mode
            mode = (e.mode_type << 12) | e.mode_perms
            f.write(mode.to_bytes(4, "big"))

            f.write(e.uid.to_bytes(4, "big"))
            f.write(e.gid.to_bytes(4, "big"))

            f.write(e.fsize.to_bytes(4, "big"))
            # @FIXME convert back to int
            f.write(int(e.sha, 16).to_bytes(20, "big"))

            flag_assume_valid = 0x1 << 15 if e.flag_assume_valid else 0

            name_bytes = e.name.encode("utf8")
            bytes_len = len(name_bytes)
            if bytes_len >= 0xFFF:
                name_length = 0xFFF
            else:
                name_length = bytes_len

            # Write back the name, and a final 0x00
            f.write(name_bytes)
            f.write((0).to_bytes(1, "big"))

            idx += 62 + len(name_bytes) + 1

            # Add padding if necessary
            if idx % 8 != 0:
                pad = 8 - (idx % 8)
                f.write((0).to_bytes(pad, "big"))
                idx += pad



# the rm command
# Unlike git rm, wyag rm removes the file even if it isn't saved. Use with caution

argsp = argsubparsers.add_parser("rm", help="Remove files from the working tree and the index")
argsp.add_argument("path", nargs="+", help="Files to remove")

def cmd_rm(args):
    repo = repo_find()
    rm(repo, args.path)


"""
 The rm function is somewhat long but simple.
 It takes a list of paths, reads that repo index, and removes entries in the index that match this list.

 The optional arguments control wether the function should actually delete the files,
 and whether it should abort if some paths aren't present on the index
"""

def rm(repo, paths, delete=True, skip_missing=False):
    # find and read the index
    index = index_read(repo)

    worktree = repo.worktree + os.sep

    # Make paths absolute
    abspaths = list()
    for path in paths:
        abspath = os.path.abspath(path)
        if abspath.startswith(worktree):
            abspaths.append(abspath)
        else:
            raise Exception("Cannot remove paths outside of worktree: {}".format(paths))

    kept_entries = list()
    remove = list()

    for e in index.entries:
        full_path = os.path.join(repo.worktree, e.name)

        if full_path in abspaths:
            remove.append(full_path)
            abspaths.remove(full_path)
        else:
            kept_entries.append(e) # Preserve entry

    # If abspaths is empty, it means some paths weren't in the index
    if len(abspaths) > 0 and not skip_missing:
        raise Exception("Cannot remove paths not in the index: {}".format(abspaths))

    # Physically delete ptahs from filesystem
    if delete:
        for path in remove:
            os.unlink(path)

    # Update the list of entries in the index, and write it back
    index.entries = kept_entries
    index_write(repo, index)



# The add command

"""
Adding is slightly more complex than removing, but it can be described as a three step operation:
    - begin by removing existing index entry, if there's one, without removing the file itself
    - hash the file into a glob object
    - write the modified index back
"""

argsp = argsubparsers.add_parser("add", help="Add files contents to the index")
argsp.add_argument("path", nargs="+", help="files to add")

def cmd_add(args):
    repo = repo_find()
    add(repo, args.path)


def add(repo, paths, delete=True, skip_missing=False):
    # remove all paths from the index, if they exist
    rm (repo, paths, delete=False, skip_missing=True)

    worktree = repo.worktree + os.sep

    # convert paths to pairs: (absolute, relative_to_worktree)
    # delete them from index if they are present
    clean_paths = list()
    for path in paths:
        abspath = os.path.abspath(path)
        if not (abspath.startswith(worktree) and os.path.isfile(abspath)):
            raise Exception("Not a file, or outside the worktree: {}".format(paths))
        relpath = os.path.relpath(abspath, repo.worktree)
        clean_paths.append((abspath, relpath))

        # Find and read the index.  It was modified by rm.  (This isn't
        # optimal, good enough for wyag!)
        #
        # @FIXME, though: we could just move the index through
        # commands instead of reading and writing it over again.
        index = index_read(repo)

        for (abspath, relpath) in clean_paths:
            with open(abspath, "rb") as fd:
                sha = object_hash(fd, b"blob", repo)

            stat = os.stat(abspath)

            ctime_s = int(stat.st_ctime)
            ctime_ns = stat.st_ctime_ns % 10**9
            mtime_s = int(stat.st_mtime)
            mtime_ns = stat.st_mtime_ns % 10**9

            entry = GitIndexEntry(ctime=(ctime_s, ctime_ns), mtime=(mtime_s, mtime_ns), dev=stat.st_dev, ino=stat.st_ino,
                                    mode_type=0b1000, mode_perms=0o644, uid=stat.st_uid, gid=stat.st_gid,
                                    fsize=stat.st_size, sha=sha, flag_assume_valid=False,
                                    flag_stage=False, name=relpath)
            index.entries.append(entry)

        # Write the index back
        index_write(repo, index)



# the commit command

argsp = argsubparsers.add_parser("commit", help="Record changes to the repository")

argsp.add_argument("-m",
                    metavar="message",
                    dest="message",
                    help="Message to associate with this commit")


def gitconfig_read():
    xdg_config_home = os.environ["XDG_CONFIG_HOME"] if "XDG_CONFIG_HOME" in os.environ else "~/.config"
    configfiles = [
            os.path.expanduser(os.path.join(xdg_config_home, "git/config")),
            os.path.expanduser("~/.gitconfig")
            ]

    config = configparser.ConfigParser()
    config.read(configfiles)
    return config


def gitconfig_user_get(config):
    if "user" in config:
        if "name" in config["user"] and "email" in config["user"]:
            return "{} <{}>".format(config["user"]["name"], config["user"]["email"])
    return None



def tree_from_index(repo, index):
    contents = dict()
    contents[""] = list()

    # enumerate entries, and turn them into a dictionary where keys are directories, and values are lists of directory contents
    for entry in index.entries:
        dirname = os.path.dirname(entry.name)

        # We create all dict entries up to root ("").
        # we need them all, because even if a directory holds no files
        # it will contain at least a tree
        key = dirname
        while key != "":
            if not key in contents:
                contents[key] = list()
            key = os.path.dirname(key)

        # For now simply store the entry in the list
        contents[dirname].append(entry)

    sorted_paths = sorted(contents.keys(), key=len, reverse=True)

    sha = None

    for path in sorted_paths:
        tree = GitTree()

        # Add each entry to the new tree, in turn
        for entry in contents[path]:
            if isinstance(entry, GitIndexEntry): # regular entry (file)
                # transcode the mode: the entry stores it as integers,
                # we need an octal ASCII representation for the tree
                leaf_mode = "{:02o}{:04o}".format(entry.mode_type, entry.mode_perms).encode("ascii")
                leaf = GitTreeLeaf(mode = leaf_mode, path=os.path.basename(entry.name), sha=entry.sha)
            else:
                leaf = GitTreeLeaf(mode = b"040000", path=entry[0], sha=entry[1])

            tree.items.append(leaf)

        # Write the new tree object to the store
        sha = object_write(tree, repo)

        # add the new tree hash to the current dict's parent, as a pair (basename, SHA)
        parent = os.path.dirname(path)
        base = os.path.basename(path)
        contents[parent].append((base, sha))

    return sha


def commit_create(repo, tree, parent, author, timestamp, message):
    commit = GitCommit()
    commit.kvlm[b"tree"] = tree.encode("ascii")
    if parent:
        commit.kvlm[b"parent"] = parent.encode("ascii")

    # format timezone
    offset = int(timestamp.astimezone().utcoffset().total_seconds())
    hours = offset // 3600
    minutes = (offset % 3600) // 60
    tz = "{}{:02}{:02}".format("+" if offset > 0 else "-", hours, minutes)

    author = author + timestamp.strftime(" %s ") + tz

    commit.kvlm[b"author"] = author.encode("utf8")
    commit.kvlm[b"committer"] = author.encode("utf8")
    commit.kvlm[None] = message.encode("utf8")

    return object_write(commit, repo)


def cmd_commit(args):
    repo = repo_find()
    index = index_read(repo)
    # creates trees, grab back SHA for the root tree
    tree = tree_from_index(repo, index)

    # Create the commit object itself
    commit = commit_create(repo,
                            tree,
                            object_find(repo, "HEAD"),
                            gitconfig_user_get(gitconfig_read()),
                            datetime.now(),
                            args.message)

    # Update HEAD so our commit is now the tip of the active branch
    active_branch = branch_get_active(repo)
    if active_branch:
        with open(repo_file(repo, os.path.join("refs/heads", active_branch)), "w") as fd:
            fd.write(commit + "\n")
    else:
        with open(repo_file(repo, "HEAD"), "w") as fd:
            fd.write("\n")






















































































