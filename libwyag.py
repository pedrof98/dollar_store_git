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
        case "ls-tree"     : cmd_ls_tree(args)
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


















