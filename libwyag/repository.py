# libwyag/repository.py
import configparser
import os

class GitRepository:
    """A Git repository."""
    def __init__(self, path, force=False):
        self.worktree = path
        self.gitdir = os.path.join(path, ".git")
        self.conf = configparser.ConfigParser()

        if not (force or os.path.isdir(self.gitdir)):
            raise Exception(f"Not a Git Repository {path}")

        cf = self.repo_file("config")
        if cf and os.path.exists(cf):
            self.conf.read([cf])
        elif not force:
            raise Exception("Configuration file missing")

        if not force:
            vers = int(self.conf.get("core", "repositoryformatversion"))
            if vers != 0:
                raise Exception(f"Unsupported repositoryformatversion {vers}")

    def repo_path(self, *path):
        """Compute path under repo's gitdir."""
        return os.path.join(self.gitdir, *path)

    def repo_file(self, *path, mkdir=False):
        if self.repo_dir(*path[:-1], mkdir=mkdir):
            return self.repo_path(*path)
        return None

    def repo_dir(self, *path, mkdir=False):
        path = self.repo_path(*path)
        if os.path.exists(path):
            if os.path.isdir(path):
                return path
            else:
                raise Exception(f"Not a directory {path}")
        if mkdir:
            os.makedirs(path)
            return path
        return None


def repo_create(path):
    """Create a new repository at path."""
    from .repository import GitRepository  # or a relative import
    repo = GitRepository(path, force=True)

    if os.path.exists(repo.worktree):
        if not os.path.isdir(repo.worktree):
            raise Exception(f"{path} is not a directory!")
        if os.path.exists(repo.gitdir) and os.listdir(repo.gitdir):
            raise Exception(f"{repo.gitdir} is not empty!")
    else:
        os.makedirs(repo.worktree)

    # Create subdirs
    repo.repo_dir("branches", mkdir=True)
    repo.repo_dir("objects", mkdir=True)
    repo.repo_dir("refs", "tags", mkdir=True)
    repo.repo_dir("refs", "heads", mkdir=True)

    # .git/description
    with open(repo.repo_file("description"), "w") as f:
        f.write("Unnamed repository; edit this file 'description' to name the repository.\n")

    # .git/HEAD
    with open(repo.repo_file("HEAD"), "w") as f:
        f.write("ref: refs/heads/master\n")

    # .git/config
    with open(repo.repo_file("config"), "w") as f:
        config = repo_default_config()
        config.write(f)

    return repo


def repo_default_config():
    c = configparser.ConfigParser()
    c.add_section("core")
    c.set("core", "repositoryformatversion", "0")
    c.set("core", "filemode", "false")
    c.set("core", "bare", "false")
    return c


def repo_find(path=".", required=True):
    """Find a repo, searching up the directory hierarchy until .git is found."""
    path = os.path.realpath(path)
    if os.path.isdir(os.path.join(path, ".git")):
        return GitRepository(path)

    parent = os.path.realpath(os.path.join(path, ".."))
    if parent == path:
        # If parent==path, then path is root
        if required:
            raise Exception("No git directory.")
        else:
            return None

    return repo_find(parent, required)

