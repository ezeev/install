#!/usr/bin/env python
"""
The main module file that will be invoked by the one line installer.

check usage in main()
or
python -m python_installer.gather_metrics -h

It first checks the dependency this module needs.
Detects application and calls the appropriate plugin installer.
Catches ctrl+c, which exits the system with return code of 1.
"""
import socket
import sys
from datetime import datetime
import re
import importlib
import json
import collections
import argparse

import common.conf_collectd_plugin as conf
import common.install_utils as utils
import common.config as config

# Python required base version
REQ_VERSION = (2, 7)
# Install state of app
INCOMPLETE = 2
NEW = 1
INSTALLED = 0


def usage():
    """ Deprecated
    deprecated by argparse module
    """
    utils.cprint(
        "Usage: gather_metrics [operating system(DEBIAN|REDHAT)] "
        "[agent(COLLECTD|TELEGRAF)] [APP_DIR] [log file] [-TEST]\n"
        "operating system:\n"
        "    Determines the installer control flow.\n"
        "agent:\n"
        "    Determines the directory path.\n"
        "app_dir:\n"
        "    The location of WF-PCInstaller where setup.py resides.\n"
        "log_file:\n"
        "    Errors will log to this file.\n"
        "-TEST:\n"
        "    Installs all detected applications with default setting.\n"
        "    This is for integeration test.  Default is off.\n")


def check_version():
    """
    check python version
    """
    cur_version = sys.version_info
    utils.print_step('  Checking python version')
    if cur_version < REQ_VERSION:
        sys.stderr.write(
            'Your Python interpreter is older '
            'than what we have tested, we suggest upgrading '
            'to a newer 2.7 version before continuing.\n')
        sys.exit()
    utils.print_success()


def port_scan(host, port):
    """ Deprecated
    Using ipv4, TCP connection to test whether a port is
    being used.
    """
    # AF_INET specifies ipv4, SOCK_STREAM for TCP
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    try:
        sock.connect((host, port))
    except socket.error:
        return False
    except KeyboardInterrupt:
        utils.cprint('Scanning interrupted')
        sys.exit()
    except socket.gaierror:
        utils.cprint('Hostname could not be resolved')
        sys.exit()
    else:
        return port
    finally:
        sock.close()


def check_app(output, app_dict):
    """
    Input:
        output string:
            the result of ps -ef
        app_dict {}:
            the dictionary that hold's the app's information.
            This is reading from support_plugins.json

    Output:
        return true if the app is running

    Description:
        checks if the keyword from support_plugins can be matched
        in ps -ef output.
        if not, check if the command matches

        Note: lax search, but user has potentially more options
        to pick installers

    """
    app_search = app_dict['app_search']
    app_cmds = app_dict['command'].split('|')

    # lax app search
    app_re = re.compile(
        r'({app_search})'.format(
            app_search=app_search))
    # prevent self detection
    script_re = re.compile(
        r'root(.*)bash -c #!/bin/bash(.*)Install Wavefront Proxy and '
        'configures(.*)function logo')

    app_found = False
    for line in output.decode().split('\n'):
        self_res = script_re.match(line)

        if self_res is None:
            app_found = app_re.search(line)
            if app_found is not None:
                if config.DEBUG:
                    utils.eprint(line)
                return True
        else:
            if config.DEBUG:
                utils.eprint(
                    'Detected self with match:\n{}'.format(
                        self_res.group()))

    # check command if app is not found running
    if app_found is None:
        for cmd in app_cmds:
            if config.DEBUG:
                utils.eprint('Command: {}'.format(cmd))
            if cmd == "None":
                return False
            elif utils.command_exists(cmd):
                return True

    return False


def detect_used_ports():
    """ Deprecated
    Scan through localhost 0-1024 ports
    """
    MAX_PORT = 1025
    DEFAULT_HOST = '127.0.0.1'
    open_ports = []
    socket.setdefaulttimeout(1)
    for port in range(0, MAX_PORT):
        res = port_scan(DEFAULT_HOST, port)
        if res:
            open_ports.append(port)
        # debugging purpose to see if program is running
        if port % 5000 == 0 and port != 0:
            sys.stderr.write('.')
    return open_ports


def detect_applications():
    """
    Detect applications and provide the appropriate plugin information

    Description:
        This function uses unix command ps -ef and check whether
        the supported application is found.
        Check current plugin support in support_plugin.json

    Input:
        None
    Output:
        support_list []:
            the list of supported plugins that were detected
        support_dict {}
            the dictionary associated with each supported plugin
    """

    plugins_file = config.PLUGINS_FILE_PATH
    utils.print_step('Begin app detection')

    res = utils.get_command_output('ps -ef')
    if res is None:
        utils.exit_with_message('Unable to read process off the machine')

    try:
        data_file = open(plugins_file)
    except (IOError, OSError) as e:
        utils.exit_with_message(e)
    except Exception as e:
        utils.exit_with_message(
            'Cannot read support_plugins.json.\n'
            'Unexpected error: {}.'.format(e))

    try:
        data = json.load(data_file)
    except Exception as e:
        utils.cprint(
            'Improper JSON format.\n'
            'Error: {}'.format(e))
    finally:
        data_file.close()

    data = data['data']

    plugin_dict = data['plugins']
    support_dict = {}
    support_list = []

    for app in plugin_dict:
        app_dict = plugin_dict[app]
        if check_app(res, app_dict):
            if config.AGENT in app_dict:
                support_list.append(app)
                support_dict[app] = app_dict

    if len(support_list):
        return (support_list, support_dict)
    else:
        utils.eprint('No supported app plugin is detected.')
        sys.exit(0)


def installer_menu(app_list, support_dict):
    """
    provide the menu and prompts for the user to interact with the installer

    Input:
        app_list []:
            list of app detected that plugin support
        support_dict {}:
            dict that associates with each app in app_list

    Output:
        count int:
            the number of successful installation

    installer flow:
      1. show selections
      2. installs a plugin
      3. updates install state
      4. menu changes with install state

    Sample menu:
    Option  Name                 State      Date
    (1)     mysql                Installed  (installation date)
    (2)     apache               Incomplete
    (3)     postgres             New

    if resinstall,
      warn that this will overwrite {conf_file}.
    """
    exit_cmd = [
        'quit', 'q', 'exit']
    count = 0

    # the format of each row in installing menu
    menu_rowf = (
        '{index:{index_pad}} {name:{name_pad}} '
        '{state:{state_pad}} {date}')
    # padding of each parameter
    index_pad = 7
    name_pad = 30
    state_pad = 12
    color = utils.BLACK  # default color

    res = None  # to begin the prompt loop
    utils.cprint()
    utils.cprint(
        'We have detected the following applications that are '
        'supported by our configurators.')

    while res not in exit_cmd:
        utils.cprint()
        utils.cprint(
            'The following are the available configurators:')

        utils.cprint(
            menu_rowf.format(
                index='Option', index_pad=index_pad,
                name='Name', name_pad=name_pad,
                state='State', state_pad=state_pad,
                date='Date'))

        # install_state_dict contains other agents' state as well
        install_state_dict = check_install_state(app_list)
        install_state = install_state_dict[config.AGENT]

        for i, app in enumerate(app_list):
            # formatted string for menu
            index = '({i})'.format(i=i)
            app_installer = '{app}'.format(app=app)
            app_state = install_state[app]['state']

            if 'date' in install_state[app]:
                date = install_state[app]['date']
            else:
                date = ''

            if app_state == NEW:
                state = 'New'
                color = utils.GREEN
            elif app_state == INCOMPLETE:
                state = 'Incomplete'
                color = utils.YELLOW
            elif app_state == INSTALLED:
                state = 'Installed'
                color = utils.BLACK

            utils.print_color_msg(
                menu_rowf.format(
                    index=index, index_pad=index_pad,
                    name=app_installer, name_pad=name_pad,
                    state=state, state_pad=state_pad,
                    date=date), color)

        utils.cprint()
        utils.cprint(
            'To pick a configurator, type in the corresponding number '
            'next to the configurator.\n'
            'To quit out of this installer, type "[Q]uit" or "exit".')
        res = utils.get_input(
            'Which installer would you like to run?').lower()
        if res not in exit_cmd:
            # check if option is within the array list
            option = check_option(res, len(app_list))

            if option is not None:
                app = app_list[option]
                app_dict = support_dict[app]
                utils.cprint(
                    'You have selected ({option}) {app} installer'.format(
                        option=option, app=app))
                app_state = install_state[app]['state']
                if app_state == INSTALLED:
                    utils.print_warn(
                        'You have previously used this configurator\n'
                        'Reinstalling will overwrite the old configuration '
                        'file, {}.'.format(app_dict['conf_name']))
                confirm = utils.ask(
                    'Would you like to proceed with '
                    'the configurator?')
                if confirm:
                    if run_installer(config.AGENT, app_dict):
                        install_state[app]['state'] = INSTALLED
                        count += 1
                    else:
                        install_state[app]['state'] = INCOMPLETE
                    install_state[app]['date'] = '{:%c}'.format(
                        datetime.now())
                    update_install_state(config.AGENT, install_state_dict)
            else:
                utils.print_reminder('Invalid option.')

    return count


def run_installer(agent, app_dict, TEST=False):
    """
    Based on the app selected, instantiate and run the
    configurator.

    Input:
        agent string:
            the collecter chosen for installer
        app_dict {}:
            the dict containing the app's information
        TEST bool:
            used for integration testing
    Output:
    """
    # pick directory based on agent
    if agent == config.COLLECTD:
        plugin_dir = config.COLLECTD_PLUGIN_DIR
    elif agent == config.TELEGRAF:
        plugin_dir = config.TELEGRAF_PLUGIN_DIR

    if TEST:
        plugin_dir += "/test"

    # using python -m, which requires . format instead of /
    plugin_dir = plugin_dir.replace('/', '.')

    Installer = getattr(
        importlib.import_module(
            '{direc}.{mod}'.format(
                direc=plugin_dir,
                mod=app_dict['module'])),
        app_dict['class_name'])
    instance = Installer(
        config.OPERATING_SYSTEM,
        agent,
        app_dict[agent]['plugin_name'],
        app_dict['conf_name'])

    return instance.install()


def test_installer(app_list, support_dict):
    """
    run each detected app with the test installer

    Input:
        app_list []:
            list of app detected that plugin support
        support_dict {}:
            dict that associates with each app in app_list

    Side-effect:
        append module with '_test'
        prepend conf_name with 'test_'
        append class_name with 'Test'
    """
    for app in app_list:
        app_dict = support_dict[app]
        test_conf = 'test_{0}'.format(app_dict['conf_name'])
        app_dict['conf_name'] = test_conf
        app_dict['module'] += '_test'
        app_dict['class_name'] += 'Test'
        run_installer(config.AGENT, support_dict[app], TEST=True)


def check_install_state(app_list):
    """
    check the state of each installer

    Input:
        app_list []:
            a list of app name
    Output:
        install_state {}:
            a dict of app_name and their states

    Flow:
     - check file path exists
     - if exists:
           check each app against the fiel
           keep track of app and their states
    """
    # construct an empty install state if no file found
    empty_state_dict = {}
    empty_state_dict[config.AGENT] = {}
    empty_agent_dict = empty_state_dict[config.AGENT]
    for app in app_list:
        empty_agent_dict[app] = {}
        empty_agent_dict[app]['state'] = NEW

    # get location of install_state file
    if config.DEBUG:
        file_path = config.INSTALL_STATE_FILE
    else:
        if config.AGENT == config.COLLECTD:
            file_path = config.COLLECTD_INSTALL_STATE_FILE_PATH
        elif config.AGENT == config.TELEGRAF:
            file_path = config.TELEGRAF_INSTALL_STATE_FILE_PATH

    file_not_found = False
    try:
        install_file = open(file_path)
    except (IOError, OSError) as e:
        file_not_found = True
    except Exception as e:
        utils.exit_with_message('Error: {}'.format(e))

    if file_not_found:
        return empty_state_dict

    try:
        data = json.load(install_file)
    except Exception as e:
        utils.eprint(
            'Invalid json format.'
            'Error: {}'.format(e))
    finally:
        install_file.close()

    install_state = data['data']
    # create an empty dictionary for the app if key not found
    if config.AGENT not in install_state:
        install_state[config.AGENT] = {}

    agent_data = install_state[config.AGENT]
    for app in app_list:
        if app not in agent_data:
            agent_data[app] = {}
            agent_data[app]['state'] = NEW

    return install_state


def update_install_state(agent, app_state_dict):
    """
    update the app state by modifying the json file

    Input:
        agent string:
            the agent chosen for the collector
        app_state_dict {}:
            dict that contains the app state

    Description:
        update the app_state and write to install_state.json
    """
    comment = {
          "standard_format": "see below",
          "AGENT": {
              "APP_NAME": {
                  "state": "(INSTALLED = 0, INCOMPLETE = 1, NEW = 2)",
                  "date": "time_of_installation"
              }
          }
    }

    # to keep order upon writing the dictionary
    json_content = collections.OrderedDict()
    json_content['_comment'] = comment
    json_content.update({'data': app_state_dict})

    if config.DEBUG:
        file_path = config.INSTALL_STATE_FILE
    else:
        if config.AGENT == config.COLLECTD:
            file_path = config.COLLECTD_INSTALL_STATE_FILE_PATH
        elif config.AGENT == config.TELEGRAF:
            file_path = config.TELEGRAF_INSTALL_STATE_FILE_PATH

    try:
        outfile = open(file_path, 'w')
    except:
        utils.eprint(
            'Cannot write to {}.\n'
            'Installed state is not updated.'.format(file_path))
        outfile = None

    if outfile is not None:
        try:
            json.dump(json_content, outfile, indent=4)
        finally:
            outfile.close()


def check_option(option, max_length):
    """
    check if option is a num or if it is out of range

    Input:
        option string:
            the option number in string
        max_length:
            the max length of the array
    Output:
        res int:
            option string to int
    """
    res = utils.string_to_num(option)
    if res is None:
        return None

    if res < 0 or res >= max_length:
        return None
    return res


def main():
    """
    Provides usage guide and prompt the user for choice of installers
    """
    check_version()

    parser = argparse.ArgumentParser(
        prog='python -m python_installer.gather_metrics',
        description='Python Configuration Installer')
    # os arg
    parser.add_argument(
        '--os',
        choices=['DEBIAN', 'REDHAT'],
        required=True,
        help='Operating system (DEBIAN|REDHAT)',
        metavar='(DEBIAN|REDHAT)')

    # agent arg
    parser.add_argument(
        '--agent',
        choices=['COLLECTD', 'TELEGRAF'],
        required=True,
        help='Agent (COLLECTD|TELEGRAF)',
        metavar='(COLLECTD|TELEGRAF)')

    # app_dir
    parser.add_argument(
        '--app_dir',
        required=True,
        help='The location of WF-PCInstaller where setup.py resides.')

    # log_file
    parser.add_argument(
        '--log_file',
        required=True,
        help='Errors will be logged to this file.')

    # debug
    parser.add_argument(
        '--debug',
        action='store_true',
        default=False,
        help='Turn debug flag on.')

    # --TEST
    parser.add_argument(
        '--TEST',
        action='store_true',
        default=False,
        help='Installs all detected applications with default setting.\n'
        'This is for integeration test.  Default is false.')

    args = parser.parse_args()
    config.OPERATING_SYSTEM = args.os
    config.AGENT = args.agent
    config.APP_DIR = args.app_dir
    config.INSTALL_LOG = args.log_file
    config.DEBUG = args.debug
    config.TEST = args.TEST

    if config.AGENT == config.COLLECTD:
        conf.check_collectd_exists()
        conf.check_collectd_path()

    if config.DEBUG:
        utils.print_warn('DEBUG IS ON')

    (app_list, app_dict) = detect_applications()

    try:
        if config.TEST:
            test_installer(app_list, app_dict)
        else:
            # if at least one installer is ran to completion,
            # then exit with success
            if installer_menu(app_list, app_dict):
                sys.exit(0)
            else:
                sys.exit(1)
    except KeyboardInterrupt:
        utils.eprint('\nQuitting the installer via keyboard interrupt.')
        sys.exit(1)


if __name__ == '__main__':
    main()
