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
        case "ls-trees"     : cmd_ls_trees(args)
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
        math fmt:
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















