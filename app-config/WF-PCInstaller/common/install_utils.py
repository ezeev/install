from __future__ import print_function

import sys
import os
import subprocess
import random
import socket
import string
import re
# python 2/3 compatibility
try:
    from urllib.parse import urlparse as url_p
except ImportError:
    from urlparse import urlparse as url_p


# colors for the print message
BLACK = 0
RED = 1
GREEN = 2
YELLOW = 3
BLUE = 4
MAGENTA = 5
CYAN = 6

# http response header
NOT_AUTH = 401
NOT_FOUND = 404
HTTP_OK = 200
INVALID_URL = -1


# input/output utils
def cprint(*args, **kwargs):
    """
    future print method for compatibility between python 2/3
    """
    print(*args, **kwargs)


def eprint(*args, **kwargs):
    """
    error print method for compatibility between python 2/3
    """
    print(*args, file=sys.stderr, **kwargs)


def cinput(*args, **kwargs):
    """
    to make input compatible for python2 and 3
    """
    cm = sys.modules[__name__]

    try:
        cm.input = raw_input
    except NameError:
        pass

    try:
        res = input(*args, **kwargs)
    except EOFError:
        res = ''

    return res


def ask(question, default='yes'):
    """
    Ask a yes/no question via input() and return their answer.

    source: http://stackoverflow.com/questions/3041986/python-command-line-yes-no-input
    "question" is a string that is presented to the user.
    "default" is the presumed answer if the user just hits <Enter>.
    It must be "yes" (the default), "no" or None (meaning
        an answer is required of the user).

    The "answer" return value is True for "yes" or False for "no".
    """

    valid = {
        'yes': True, 'y': True, 'ye': True,
        'no': False, 'n': False}

    if default is None:
        prompt = ' [y/n] '
    elif default == 'yes':
        prompt = ' [Y/n] '
    elif default == 'no':
        prompt = ' [y/N] '
    else:
        raise ValueError('Invalid default answer: "%s"' % default)

    while True:
        sys.stdout.write(question + prompt)
        choice = cinput().lower().strip()

        if default is not None and choice == '':
            return valid[default]
        elif choice in valid:
            return valid[choice]
        else:
            sys.stdout.write(
                'Please respond with "yes" or "no" '
                '(or "y" or "n").\n')


def get_input(prompt, default=None):
    """
    Get user's input, only checking for non-empty response.
    """
    user_input = ''
    if default is not None:
        prompt = (
            '{prompt} (default: {})').format(default, prompt=prompt)

    while user_input == '':
        user_input = cinput(prompt + '\n').strip()

        if user_input == '':
            if default is not None:
                user_input = default
            else:
                cprint('The value cannot be blank.')

    return user_input


def prompt_and_check_input(
        prompt, check_func, usage, usage_fmt=False, default=None):
    """
    prompt until valid input

    prompt: question to be asked
    check_func: a function that checks the validity of the response
    usage: description of valid input
    default: default argument for the prompt to take
    """
    first_prompt = True

    while first_prompt or not check_func(res):
        if first_prompt:
            first_prompt = False
        else:
            if usage_fmt:
                eprint(usage(res))
            else:
                eprint(usage)

        res = get_input(prompt, default)

    return res


def string_to_num(s):
    try:
        num = int(s)
    except ValueError:
        return None
    return num


# helper functions converted from one line script utils to python callable
def print_warn(msg):
    call_command('tput setaf 3')  # 3 = yellow
    sys.stdout.write('[ WARNING ]\n')
    call_command('tput sgr0')
    sys.stderr.write(msg + '\n')


def print_reminder(msg):
    call_command('tput setaf 5')  # 5 = magenta
    sys.stderr.write(msg + '\n')
    call_command('tput sgr0')


def print_color_msg(msg, color):
    call_command('tput setaf {}'.format(color))
    sys.stderr.write(msg + '\n')
    call_command('tput sgr0')


def print_failure():
    call_command('tput setaf 1')  # 1 = red
    print_right('[ FAILED ]')
    call_command('tput sgr0')


def print_success():
    call_command('tput setaf 2')  # 2 = green
    print_right('[ OK ]')
    call_command('tput sgr0')


def print_step(msg):
    call_command('tput setaf 6')
    sys.stdout.write(msg + '\n')
    call_command('tput sgr0')


def print_right(msg):
    call_command('tput cuu1')
    call_command('tput cuf $(tput cols)')
    call_command('tput cub %d' % len(msg))
    sys.stdout.write(msg + '\n')


def exit_with_message(msg):
    eprint(msg)
    sys.exit(1)


def exit_with_failure(msg):
    print_failure()
    exit_with_message(msg)


# utils using subprocess
def call_command(command):
    """
    Process the given command in a bash shell and return the returncode.

    Warning: Make sure the command is sanitized before
    calling this function to prevent any vulnerability.
    """
    res = subprocess.call(
        command, shell=True,
        executable='/bin/bash')
    return res


def command_exists(command):
    """check if hash can find a path for the command

    From install.sh
    """
    res = call_command(
        'hash {} > /dev/null 2>&1'.format(command))
    if res != 0:
        return False
    else:
        return True


def get_command_output(command):
    try:
        res = subprocess.check_output(
            command, shell=True,
            stderr=subprocess.STDOUT,
            executable='/bin/bash')
    except:
        res = None

    return res


def append_to_log(msg, log):
    res = call_command(
        'echo -e "\n{msg}" >> {log}'.format(
            msg=msg, log=log))
    if res != 0:
        raise Exception('Failed to write to log.')


# utils using os
def check_path_exists(path, expand=False, debug=False):
    if expand:
        path = os.path.expanduser(path)

    if debug:
        eprint('Checking {}'.format(path))

    return os.path.exists(path)


# Other helpers
def write_file(filepath, msg):
    try:
        with open(filepath, 'w') as out:
            out.write(msg)
    except (IOError, OSError) as e:
        raise Exception(
              '{}\n'
              'Cannot open {}.'.format(e, filepath))


def get_http_status(url):
    status_cmd = 'curl --head -s ' + url + ' | head -n 1'
    return get_command_output(status_cmd)


def get_http_return_code(http_res):
    """
    Input:
        http_res string:
            http response header
    Output:
        the appropriate code
    """
    http_status_re = re.match('HTTP/1.1 (\d* [\w ]*)\s', http_res)
    if http_status_re is None:
        return INVALID_URL

    http_code = http_status_re.group(1)

    if('401 Unauthorized' in http_code):
        return NOT_AUTH
    elif('404 Not Found' in http_code):
        return NOT_FOUND
    elif('200 OK' in http_code):
        return HTTP_OK
    else:
        return INVALID_URL


def check_repeat(item, item_list):
    """
    Input:
        item AnyType
        item_list []AnyType
    Output:
        True if item is in list
        False otherwise
    Side-effect:
        Output error message.
    """
    if item in item_list:
        utils.eprint(
            'You have already added this {}'.format(item))
        return True
    return False


def check_url_scheme(url):
    """
    Input:
        url string:
            a url string
    Output:
        True if the url contains scheme
        False otherwise
    """
    parsed = url_p.urlparse(url)
    if not parsed.scheme:
        return False
    return True


def random_string(length):
    """
    generate a random string with length length
    """
    pool = string.ascii_letters + string.digits
    return ''.join(random.choice(pool) for i in range(length))


def check_valid_port(port):
    """
    Input:
        port: string representation of port number

    Output:
        True if port is valid
        False otherwise
    """
    if port is None:
        return False

    try:
        num = int(port)
    except ValueError:
        return False

    if num < 0 or num > 65535:
        return False

    return True


def hostname_resolves(hostname):
    """
    Input:
        hostname string:
            hostname of a server
    Output:
        True if host is resolvable
        False otherwise
    """
    try:
        socket.gethostbyname(hostname)
        return True
    except socket.error:
        return False


def is_valid_ipv4_address(address):
    """
    from stack overflow

    source: http://stackoverflow.com/questions/319279/how-to-validate-ip-address-in-python/4017219#4017219
    """
    try:
        socket.inet_pton(socket.AF_INET, address)
    except AttributeError:  # no inet_pton here, sorry
        try:
            socket.inet_aton(address)
        except socket.error:
            return False
        return address.count('.') == 3
    except socket.error:  # not a valid address
        return False

    return True


if __name__ == '__main__':
    print_warn('This is for testing install_utils.py')

    cinput("testing enter")
    ask('Begin testing')
    print(call_command('ls > /dev/null'))
    print(command_exists('python'))
    print_step('Next step is')
    print_warn('REALLY long text'*10)
    get_input('just checking:', 'default')
    eprint(random_string(64))
    print(check_path_exists('/var/run/mysqld/mysqld.sock'))
