import os
from math import ceil
import stat
from datetime import datetime

from .repository import repo_find, GitRepository

##################################################
# GIT INDEX STRUCTURES
##################################################

class GitIndexEntry:
    """
    Represents one entry in the Git index (staging area).
    Contains metadata (ctime, mtime, etc.) and a reference to a blob’s SHA.
    """
    def __init__(self,
                 ctime=None, mtime=None,
                 dev=None, ino=None,
                 mode_type=None, mode_perms=None,
                 uid=None, gid=None,
                 fsize=None, sha=None,
                 flag_assume_valid=False,
                 flag_stage=0,
                 name=""):
        self.ctime = ctime
        self.mtime = mtime
        self.dev = dev
        self.ino = ino
        self.mode_type = mode_type
        self.mode_perms = mode_perms
        self.uid = uid
        self.gid = gid
        self.fsize = fsize
        self.sha = sha
        self.flag_assume_valid = flag_assume_valid
        self.flag_stage = flag_stage
        self.name = name


class GitIndex:
    def __init__(self, version=2, entries=None):
        self.version = version
        self.entries = entries if entries else []


##################################################
# READ / WRITE INDEX
##################################################

def index_read(repo):
    """Read and parse the Git index file."""
    index_file = repo.repo_file("index")
    if not index_file or not os.path.exists(index_file):
        return GitIndex()

    with open(index_file, "rb") as f:
        raw = f.read()

    # header
    signature = raw[0:4]
    if signature != b"DIRC":
        raise Exception("Invalid index signature")
    version = int.from_bytes(raw[4:8], "big")
    if version != 2:
        raise Exception("Only index version 2 is supported.")
    num_entries = int.from_bytes(raw[8:12], "big")

    idx = 12
    entries = []

    for _ in range(num_entries):
        ctime_s = int.from_bytes(raw[idx: idx+4], "big")
        ctime_ns = int.from_bytes(raw[idx+4: idx+8], "big")
        mtime_s = int.from_bytes(raw[idx+8: idx+12], "big")
        mtime_ns = int.from_bytes(raw[idx+12: idx+16], "big")
        dev = int.from_bytes(raw[idx+16: idx+20], "big")
        ino = int.from_bytes(raw[idx+20: idx+24], "big")
        mode = int.from_bytes(raw[idx+24: idx+28], "big")
        uid = int.from_bytes(raw[idx+28: idx+32], "big")
        gid = int.from_bytes(raw[idx+32: idx+36], "big")
        fsize = int.from_bytes(raw[idx+36: idx+40], "big")

        # next 20 bytes => SHA
        sha_val = int.from_bytes(raw[idx+40: idx+60], "big")
        sha = f"{sha_val:040x}"

        flags = int.from_bytes(raw[idx+60: idx+62], "big")
        flag_assume_valid = bool(flags & (0x1 << 15))
        flag_extended = bool(flags & (0x1 << 14))
        flag_stage = (flags >> 12) & 0x3
        name_len = flags & 0xfff

        idx += 62

        if name_len < 0xfff:
            name_bytes = raw[idx: idx + name_len]
            idx += name_len
            idx += 1  # null terminator
        else:
            # If name_len == 0xfff, we keep reading until null terminator
            null_idx = raw.find(b'\x00', idx)
            name_bytes = raw[idx:null_idx]
            idx = null_idx + 1

        name = name_bytes.decode("utf-8")

        # Align to multiple of 8
        idx = 8 * ceil(idx / 8)

        mode_type = (mode >> 12) & 0xF
        mode_perms = mode & 0xFFF

        entry = GitIndexEntry(
            ctime=(ctime_s, ctime_ns),
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
            name=name
        )
        entries.append(entry)

    return GitIndex(version=version, entries=entries)


def index_write(repo, index):
    """Write the in-memory index back to .git/index."""
    import struct

    # Header: 12 bytes
    #  - signature (4 bytes): "DIRC"
    #  - version (4 bytes)
    #  - num_entries (4 bytes)
    header = b"DIRC"
    header += (index.version).to_bytes(4, "big")
    header += (len(index.entries)).to_bytes(4, "big")

    body = bytearray()

    for e in index.entries:
        ctime_s, ctime_ns = e.ctime
        mtime_s, mtime_ns = e.mtime

        body += ctime_s.to_bytes(4, "big")
        body += ctime_ns.to_bytes(4, "big")
        body += mtime_s.to_bytes(4, "big")
        body += mtime_ns.to_bytes(4, "big")
        body += e.dev.to_bytes(4, "big")
        body += e.ino.to_bytes(4, "big")

        mode = ((e.mode_type & 0xF) << 12) | (e.mode_perms & 0xFFF)
        body += mode.to_bytes(4, "big")

        body += e.uid.to_bytes(4, "big")
        body += e.gid.to_bytes(4, "big")
        body += e.fsize.to_bytes(4, "big")
        body += int(e.sha, 16).to_bytes(20, "big")

        flags = 0
        if e.flag_assume_valid:
            flags |= (0x1 << 15)
        # ignoring extended bits
        # stage is bits 12-13
        flags |= (e.flag_stage & 0x3) << 12

        name_bytes = e.name.encode("utf-8")
        nlen = len(name_bytes)
        if nlen > 0xfff:
            nlen = 0xfff
        flags |= nlen

        body += flags.to_bytes(2, "big")
        body += name_bytes
        body += b'\x00'

        # Pad to multiple of 8
        while len(body) % 8 != 0:
            body += b'\x00'

    # Real Git appends a trailing SHA-1 over all the data for integrity, but
    # we skip that for simplicity.

    with open(repo.repo_file("index"), "wb") as f:
        f.write(header)
        f.write(body)

