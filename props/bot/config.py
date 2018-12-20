#!/usr/bin/env python3.6
# -*- coding: utf-8 -*-

import os
import re
import sh
import pwd
import sys
import time
import logging

from shlex import shlex
from decouple import Csv, AutoConfig, config, UndefinedValueError
import decouple

LOG_LEVELS = [
    'DEBUG',
    'INFO',
    'WARNING',
    'ERROR',
    'CRITICAL',
]

LOG_LEVEL = decouple.config('LOG_LEVEL', logging.WARNING, cast=int)

logging.basicConfig(
    stream=sys.stdout,
    level=LOG_LEVEL,
    format='%(asctime)s %(name)s %(message)s')
logging.Formatter.converter = time.gmtime
log = logging.getLogger(__name__)


class ProjNameSplitError(Exception):
    def __init__(self, basename):
        msg = f'projname split error on "-" with basename={basename}'
        super(ProjNameSplitError, self).__init__(msg)

def git(*args, strip=True, **kwargs):
    try:
        result = str(sh.contrib.git(*args, **kwargs))
        if strip:
            result = result.strip()
        return result
    except sh.ErrorReturnCode as e:
        log.error(e)

class AutoConfigPlus(decouple.AutoConfig):
    def __init__(self, *args, **kwargs):
        super(AutoConfigPlus, self).__init__(*args, **kwargs)

    @property
    def APP_UID(self):
        return os.getuid()

    @property
    def APP_GID(self):
        return pwd.getpwuid(self.APP_UID).pw_gid

    @property
    def APP_USER(self):
        return pwd.getpwuid(self.APP_UID).pw_name

    @property
    def APP_PORT(self):
        return config('APP_PORT', 5000, cast=int)

    @property
    def APP_TIMEOUT(self):
        return config('APP_TIMEOUT', 120, cast=int)

    @property
    def APP_WORKERS(self):
        return config('APP_WORKERS', 2, cast=int)

    @property
    def APP_MODULE(self):
        return config('APP_MODULE', 'main:app')

    @property
    def APP_REPOROOT(self):
        try:
            return config('APP_REPOROOT')
        except UndefinedValueError as uve:
            try:
                return git('rev-parse', '--show-toplevel')
            except:
                raise uve

    @property
    def APP_TAGNAME(self):
        try:
            return config('APP_TAGNAME')
        except UndefinedValueError as uve:
            try:
                return git('describe', '--abbrev=0', '--always')
            except:
                raise uve

    @property
    def APP_VERSION(self):
        try:
            return config('APP_VERSION')
        except UndefinedValueError as uve:
            try:
                return git('describe', '--abbrev=7', '--always')
            except:
                raise uve

    @property
    def APP_BRANCH(self):
        try:
            return config('APP_BRANCH')
        except UndefinedValueError as uve:
            try:
                return git('rev-parse', '--abbrev-ref', 'HEAD')
            except:
                raise uve

    @property
    def APP_REVISION(self):
        try:
            return config('APP_REVISION')
        except UndefinedValueError as uve:
            try:
                return git('rev-parse', 'HEAD')
            except:
                raise uve

    @property
    def APP_REMOTE_ORIGIN_URL(self):
        try:
            return config('APP_REMOTE_ORIGIN_URL')
        except UndefinedValueError as uve:
            try:
                return git('config', '--get', 'remote.origin.url')
            except:
                raise uve

    @property
    def APP_REPONAME(self):
        pattern = '(ssh|https)://([A-Za-z0-9\-_]+@)?github.com/(?P<reponame>[A-Za-z0-9\/\-_]+)(.git)?'
        match = re.search(pattern, self.APP_REMOTE_ORIGIN_URL)
        return match.group('reponame')

    @property
    def APP_PROJNAME(self):
        basename = os.path.basename(self.APP_REPONAME)
        parts = os.path.basename(basename).split('-')
        if len(parts) == 2:
            return parts[0]
        else:
            raise ProjNameSplitError(basename)

    @property
    def APP_PROJPATH(self):
        return os.path.join(self.APP_REPOROOT, self.APP_PROJNAME)

    @property
    def APP_BOTPATH(self):
        return os.path.join(self.APP_PROJPATH, 'bot')

    @property
    def APP_DBPATH(self):
        return os.path.join(self.APP_PROJPATH, 'db')

    @property
    def APP_TESTPATH(self):
        return os.path.join(self.APP_REPOROOT, 'tests')

    @property
    def APP_LS_REMOTE(self):
        url = 'https://github.com/' + self.APP_REPONAME
        result = git('ls-remote', url)
        return {refname: revision for revision, refname in [line.split() for line in result.split('\n')]}

    @property
    def APP_GSM_STATUS(self):
        result = git('submodule', 'status', strip=False)
        pattern = '([ +-])([a-f0-9]{40}) ([A-Za-z0-9\/\-_.]+)( .*)?'
        matches = re.findall(pattern, result)
        states = {
            ' ': True,  # submodule is checked out the correct revision
            '+': False, # submodule is checked out to a different revision
            '-': None,  # submodule is not checked out
        }
        return {repopath: [revision, states[state]] for state, revision, repopath, _ in matches}

    def __getattr__(self, attr):
        log.info(f'attr = {attr}')
        if attr == 'create_doit_tasks': #FIXME: to keep pydoit's hands off
            return lambda: None
        result = self.__call__(attr)
        try:
            return int(result)
        except ValueError as ve:
            return result

CFG = AutoConfigPlus()
