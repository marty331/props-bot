#!/usr/bin/env python3.6
# -*- coding: utf-8 -*-

import os
import re
import pwd
import sys

from doit import get_var
from ruamel import yaml

from props.config import CFG
from props.utils.shell import call
from props.utils.timestamp import utcnow, datetime2int

LOG_LEVELS = [
    'DEBUG',
    'INFO',
    'WARNING',
    'ERROR',
    'CRITICAL',
]

DOIT_CONFIG = {
    'default_tasks': ['pull', 'deploy', 'rmimages', 'rmvolumes', 'count'],
    'verbosity': 2,
}

class UnknownPkgmgrError(Exception):
    def __init__(self):
        super(UnknownPkgmgrError, self).__init__('unknown pkgmgr!')

def get_bot_envs():
    return [
        f'BOT_UID={BOT_UID}',
        f'BOT_GID={BOT_GID}',
        f'BOT_USER={BOT_USER}',
        f'BOT_APP_PORT={BOT_APP_PORT}',
        f'BOT_APP_TIMEOUT={BOT_APP_TIMEOUT}',
        f'BOT_APP_WORKERS={BOT_APP_WORKERS}',
        f'BOT_APP_MODULE={BOT_APP_MODULE}',
    ]

def get_env_vars(regex=None):
    return [key+'='+value for key, value in os.environ.items() if regex == None or regex.search(key)]

def check_hash(program):
    from subprocess import check_call, CalledProcessError, PIPE
    try:
        check_call(f'hash {program}', shell=True, stdout=PIPE, stderr=PIPE)
        return True
    except CalledProcessError:
        return False

def get_pkgmgr():
    if check_hash('dpkg'):
        return 'deb'
    elif check_hash('rpm'):
        return 'rpm'
    elif check_hash('brew'):
        return 'brew'
    raise UnknownPkgmgrError

def task_count():
    '''
    use the cloc utility to count lines of code
    '''
    excludes = [
        'dist',
        'venv',
        '__pycache__',
        'auto_cert_cli.egg-info',
    ]
    excludes = '--exclude-dir=' + ','.join(excludes)
    scandir = os.path.dirname(__file__)
    return {
        'actions': [
            f'cloc {excludes} {scandir}',
        ],
        'uptodate': [
            lambda: not check_hash('cloc'),
        ],
    }

def task_checkreqs():
    '''
    check for required software
    '''
    DEBS = [
        'docker-ce',
    ]
    RPMS = [
        'docker-ce',
    ]
    return {
        'deb': {
            'actions': ['dpkg -s ' + deb for deb in DEBS],
        },
        'rpm': {
            'actions': ['rpm -q ' + rpm for rpm in RPMS],
        },
        'brew': {
            'actions': ['true'],
        }
    }[get_pkgmgr()]

def task_noroot():
    '''
    make sure script isn't run as root
    '''
    then = 'echo "   DO NOT RUN AS ROOT!"; echo; exit 1'
    bash = f'if [[ $(id -u) -eq 0 ]]; then {then}; fi'
    return {
        'actions': [
            f'bash -c \'{bash}\'',
        ],
    }

def task_pull():
    '''
    do a safe git pull
    '''
    submods = call("git submodule status | awk '{print $2}'")[1].split()
    test = '`git diff-index --quiet HEAD --`'
    pull = 'git pull --rebase'
    update = 'git submodule update --remote'
    dirty_pull = f'echo "refusing to \'{pull}\' because the tree is dirty"'
    dirty_update = f'echo "refusing to \'{update}\' because the tree is dirty"'

    yield {
        'name': 'mozilla-it/autocert',
        'actions': [
            f'if {test}; then {pull}; else {dirty_pull}; exit 1; fi',
        ],
    }

    for submod in submods:
        yield {
            'name': submod,
            'actions': [
                f'cd {submod} && if {test}; then {update}; else {dirty_update}; exit 1; fi',
            ],
        }

def task_test():
    '''
    setup venv and run pytest
    '''
    PYTHONPATH = 'PYTHONPATH=.:autocert:autocert/api:$PYTHONPATH'
    return {
        'task_dep': [
            'noroot',
            #'config',
        ],
        'actions': [
            'virtualenv --python=$(which python3) venv',
            'venv/bin/pip3 install --upgrade pip',
            f'venv/bin/pip3 install -r {CFG.APP_REPOROOT}/requirements.txt',
            f'venv/bin/pip3 install -r {CFG.APP_TESTPATH}/requirements.txt',
            f'{PYTHONPATH} venv/bin/python3 -m pytest -s -vv tests/api',
        ],
    }

def task_version():
    '''
    write git describe to VERSION file
    '''
    return {
        'actions': [
            f'echo {CFG.APP_VERSION} > {CFG.APP_PROJPATH}/VERSION',
        ],
    }

def task_tls():
    '''
    create server key, csr and crt files
    '''
    name = 'server'
    tls = f'/data/{CFG.APP_PROJNAME}/tls'
    env = 'PASS=TEST'
    envp = 'env:PASS'
    targets = [
        f'{tls}/{name}.key',
        f'{tls}/{name}.crt',
    ]
    subject = '/C=US/ST=Oregon/L=Portland/O=Autocert Server/OU=Server/CN=0.0.0.0'
    def uptodate():
        return all([os.path.isfile(t) for t in targets])
    return {
        'actions': [
            f'mkdir -p {tls}',
            f'{env} openssl genrsa -aes256 -passout {envp} -out {tls}/{name}.key 2048',
            f'{env} openssl req -new -passin {envp} -subj "{subject}" -key {tls}/{name}.key -out {tls}/{name}.csr',
            f'{env} openssl x509 -req -days 365 -in {tls}/{name}.csr -signkey {tls}/{name}.key -passin {envp} -out {tls}/{name}.crt',
            f'{env} openssl rsa -passin {envp} -in {tls}/{name}.key -out {tls}/{name}.key',
        ],
        'targets': targets,
        'uptodate': [uptodate],
    }

def task_build():
    '''
    build flask|quart app
    '''

def task_deploy():
    '''
    deloy flask app via docker-compose
    '''
    return {
        'task_dep': [
            'noroot',
            'checkreqs',
            'version',
            'test',
            #'config',
            #'environment',
            #'savelogs',
        ],
        'actions': [
            f'cd {CFG.APP_PROJPATH} && docker-compose build',
            f'cd {CFG.APP_PROJPATH} && docker-compose up --remove-orphans -d',
        ],
    }

def task_rmimages():
    '''
    remove dangling docker images
    '''
    query = '`docker images -q -f dangling=true`'
    return {
        'actions': [
            f'docker rmi {query}',
        ],
        'uptodate': [
            f'[ -z "{query}" ] && exit 0 || exit 1',
        ],
    }

def task_rmvolumes():
    '''
    remove dangling docker volumes
    '''
    query = '`docker volume ls -q -f dangling=true`'
    return {
        'actions': [
            f'docker volume rm {query}',
        ],
        'uptodate': [
            f'[ -z "{query}" ] && exit 0 || exit 1',
        ],
    }

def task_logs():
    '''
    simple wrapper that calls 'docker-compose logs'
    '''
    return {
        'actions': [
            f'cd {CFG.APP_PROJPATH} && docker-compose logs',
        ],
    }

#def task_config():
#    '''
#    write config.yml -> .config.yml
#    '''
#    log_level = 'WARNING'
#    filename = PROJDIR + '/LOG_LEVEL'
#    if os.path.isfile(filename):
#        log_level = open(filename).read().strip()
#    log_level = get_var('LOG_LEVEL', log_level)
#    if log_level not in LOG_LEVELS:
#        raise UnknownLogLevelError(log_level)
#    punch = f'''
#    logging:
#        loggers:
#            api:
#                level: {log_level}
#        handlers:
#            console:
#                level: {log_level}
#    '''
#    return {
#        'actions': [
#            f'echo "cp {CONFIG_YML}\n-> {DOT_CONFIG_YML}"',
#            f'echo "setting LOG_LEVEL={log_level}"',
#            f'cp {CONFIG_YML} {DOT_CONFIG_YML}',
#            lambda: _update_config(DOT_CONFIG_YML, yaml.safe_load(punch)),
#        ]
#    }


#def task_example():
#    '''
#    cp|strip config.yml -> config.yml.example
#    '''
#    apikey = '82_CHAR_APIKEY'
#    punch = f'''
#    authorities:
#        digicert:
#            apikey: {apikey}
#    destinations:
#        zeus:
#            apikey: {apikey}
#    '''
#    return {
#        'actions': [
#            f'cp {CONFIG_YML}.example {CONFIG_YML}.bak',
#            f'cp {CONFIG_YML} {CONFIG_YML}.example',
#            lambda: _update_config(CONFIG_YML+'.example', yaml.safe_load(punch)),
#        ],
#    }

def task_rmcache():
    '''
    recursively delete python cache files
    '''
    return dict(
        actions=[
            'find cli/ -depth -name __pycache__ -type d -exec rm -r "{}" \;',
            'find cli/ -depth -name "*.pyc" -type f -exec rm -r "{}" \;',
            'find api/ -depth -name __pycache__ -type d -exec rm -r "{}" \;',
            'find api/ -depth -name "*.pyc" -type f -exec rm -r "{}" \;',
            'find tests/ -depth -name __pycache__ -type d -exec rm -r "{}" \;',
            'find tests/ -depth -name "*.pyc" -type f -exec rm -r "{}" \;',
        ]
    )

def task_tidy():
    '''
    delete cached files
    '''
    TIDY_FILES = [
        '.doit.db/',
        'venv/',
        '{CFG.APP_PROJPATH}/VERSION',
    ]
    return {
        'actions': [
            'rm -rf ' + ' '.join(TIDY_FILES),
            'find . | grep -E "(__pycache__|\.pyc$)" | xargs rm -rf',
        ],
    }

def task_nuke():
    '''
    git clean and reset
    '''
    return {
        'task_dep': ['tidy'],
        'actions': [
            'docker-compose kill',
            'docker-compose rm -f',
            'git clean -fd',
            'git reset --hard HEAD',
        ],
    }

def task_setup():
    '''
    setup venv
    '''
    return {
        'actions': [
            'rm -rf auto_cert_cli.egg-info/ venv/ dist/ __pycache__/',
            'virtualenv --python=python3 venv',
            'venv/bin/pip3 install --upgrade pip',
            'venv/bin/pip3 install -r cli/requirements.txt',
            'venv/bin/python3 ./setup.py install',
            f'unzip -l venv/lib/python3.5/site-packages/auto_cert_cli-{CFG.APP_VERSION}-py3.5.egg',
        ],
    }

def task_prune():
    '''
    prune stopped containers
    '''
    return {
        'actions': ['docker rm `docker ps -q -f "status=exited"`'],
        'uptodate': ['[ -n "`docker ps -q -f status=exited`" ] && exit 1 || exit 0']
    }

def task_zeus():
    '''
    launch zeus containers
    '''
    image = 'zeus17.3'
    for num in (1, 2):
        container = f'{image}_test{num}'
        yield {
            'task_dep': ['prune'],
            'name': container,
            'actions': [f'docker run -d -p 909{num}:9090 --name {container} {image}'],
            'uptodate': [f'[ -n "`docker ps -q -f name={container}`" ] && exit 0 || exit 1']
        }

def task_stop():
    '''
    stop running autocert containers
    '''
    def check_docker_ps():
        cmd = 'docker ps --format "{{.Names}}" | grep ' + CFG.APP_PROJNAME + ' | { grep -v grep || true; }'
        out = call(cmd, throw=True)[1]
        return out.split('\n') if out else []
    containers = ' '.join(check_docker_ps())
    return {
        'actions': [
            f'docker rm -f {containers}',
        ],
        'uptodate': [
            lambda: len(check_docker_ps()) == 0,
        ],
    }

if __name__ == '__main__':
    print('should be run with doit installed')
    import doit
    doit.run(globals())
