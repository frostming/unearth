from unearth.vcs.base import vcs_support
from unearth.vcs.bazaar import Bazaar
from unearth.vcs.git import Git
from unearth.vcs.hg import Mercurial
from unearth.vcs.svn import Subversion

__all__ = ["Bazaar", "Git", "Mercurial", "Subversion", "vcs_support"]
