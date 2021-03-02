import os
import subprocess
import httpx
import hashlib
import shutil
import time
import stat
import json
import re

from pathlib import Path

from eth2validatorwizard import __version__
from eth2validatorwizard.constants import *

from prompt_toolkit.shortcuts import button_dialog, radiolist_dialog

def run():
    # Main entry point for the wizard.

    if not show_welcome():
        # User asked to quit
        quit()

    self_update()

    if not has_su_perm():
        # User is not a super user
        show_not_su()
        quit()

    # TODO: Detect if installation is already started and resume if needed

    if not explain_overview():
        # User asked to quit
        quit()

    # TODO: Check for open ports
    # TODO: Check for disk size
    # TODO: Check for disk speed
    # TODO: Check for internet speed
    # TODO: Check time synchronization and configure it if needed

    selected_network = select_network()
    if not selected_network:
        # User asked to quit
        quit()

    if not install_geth(selected_network):
        # User asked to quit or error
        quit()

    if not install_lighthouse(selected_network):
        # User asked to quit or error
        quit()

    generated_keys = generate_keys(selected_network)
    if not generated_keys:
        # User asked to quit or error
        quit()
    
    if not install_lighthouse_validator(selected_network, generated_keys):
        # User asked to quit or error
        quit()

    public_keys = initiate_deposit(selected_network, generated_keys)
    if not public_keys:
        # User asked to quit or error
        quit()

    # TODO: Monitoring setup

    show_whats_next(selected_network, generated_keys, public_keys)

    show_public_keys(selected_network, generated_keys, public_keys)

def show_welcome():
    # Show a welcome message about this wizard

    result = button_dialog(
        title='Eth2 Validator Wizard',
        text=(
'''
Welcome to the Eth2 Validator Wizard!

This setup assistant is meant to guide anyone through the different steps
to become a fully functional validator on the Ethereum 2.0 network. It will
install and configure all the software needed to become a validator.

If you have any question or if you need additional support, make sure
to get in touch with the ethstaker community on:

* Discord: discord.gg/e84CFep
* Reddit: reddit.com/r/ethstaker
'''     ),
        buttons=[
            ('Start', True),
            ('Quit', False)
        ]
    ).run()

    return result

def self_update():
    # TODO: Check for a new version of the wizard and self-update if needed

    pass

def has_su_perm():
    # Check to see if the script has super user (root or sudo) permissions

    return os.geteuid() == 0

def show_not_su():
    # Show a message about the wizard not having super user (root or sudo) permissions

    button_dialog(
        title='Not a super user',
        text=(
'''
The Eth2 Validator Wizard needs to have super user permissions in order
to proceed.

A simple way to give the wizard these permissions is to start it with sudo.
'''     ),
        buttons=[
            ('Quit', False)
        ]
    ).run()

def explain_overview():
    # Explain the overall process of becoming a validator

    result = button_dialog(
        title='Becoming a validator',
        text=(
'''
Here is an overview of the different steps required to become an active
validator on an Ethereum 2.0 network.

* Consolidate 32 ETH for each active validator you want (You can have
an almost unlimited amount of active validators using a single computer
and this setup)
* Install an Eth1 client and let it synchronize
* Install an Eth2 beacon node and let it synchronize
* Generate your validator(s) keys
* Install an Eth2 validator client and import your key(s)
* Perform the 32 ETH deposit for each validator
* Wait for your validator(s) to become active (can take a few hours/days)
'''     ),
        buttons=[
            ('Keep going', True),
            ('Quit', False)
        ]
    ).run()

    return result

def select_network():
    # Prompt for the selection on which network to perform the installation

    result = radiolist_dialog(
        title='Network selection',
        text=(
'''
This wizard supports installing and configuring software for various
Ethereum 2.0 networks. Mainnet is the main network with real value. The
others are mostly for testing and they do not use anything of real value.

For which network would you like to perform this installation?

* Press the tab key to switch between the controls below
'''
        ),
        values=[
            (NETWORK_MAINNET, "Mainnet"),
            (NETWORK_PYRMONT, "Pyrmont")
        ],
        ok_text='Use this',
        cancel_text='Quit'
    ).run()

    return result

def install_geth(network):
    # Install geth for the selected network

    # Check for existing systemd service
    geth_service_exists = False

    process_result = subprocess.run([
        'systemctl', 'show', 'geth.service',
        '--property=ActiveState,LoadState,ExecMainStartTimestamp,FragmentPath'
        ], capture_output=True, text=True)
    process_output = process_result.stdout

    service_details = {
        'load_state': 'unknown',
        'active_state': 'unknown',
        'exec_timestamp': 'unknown',
        'fragment_path': 'unknown'
    }

    search_pairs = {
        'LoadState': 'load_state',
        'ActiveState': 'active_state',
        'ExecMainStartTimestamp': 'exec_timestamp',
        'FragmentPath': 'fragment_path'
    }

    for sproperty, key in search_pairs.items():
        result = re.search(re.escape(sproperty) + r'=(.*?)\n', process_output)
        if result:
            service_details[key] = result.group(1).strip()

    if service_details['load_state'] == 'loaded':
        geth_service_exists = True
    
    if geth_service_exists:
        result = button_dialog(
            title='Geth service found',
            text=(
f'''
The geth service seems to have already created. Here are some details
found:

LoadState: {search_pairs['load_state']}
ActiveState: {search_pairs['active_state']}
ExecMainStartTimestamp: {search_pairs['exec_timestamp']}
FragmentPath: {search_pairs['fragment_path']}

Do you want to skip installing geth and its service?
'''         ),
            buttons=[
                ('Skip', 1),
                ('Install', 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        if result == 1:
            return True

    result = button_dialog(
        title='Geth installation',
        text=(
'''
This next step will install Geth, an Eth1 client.

It uses the official Ethereum Personal Package Archive (PPA) meaning that
it gets integrated with the normal updates for Ubuntu and its related
tools like APT.

Once the installation is completed, it will create a systemd service that
will automatically start Geth on reboot or if it crashes. Geth will be
started and you will slowly start syncing with the Ethereum 1.0 network.
This syncing process can take a few hours or days even with good hardware
and good internet.
'''     ),
        buttons=[
            ('Install', True),
            ('Quit', False)
        ]
    ).run()

    if not result:
        return result
    
    # Check if geth is already installed
    geth_found = False
    geth_package_installed = False
    installed_from_ppa = False
    geth_version = 'unknown'
    geth_location = 'unknown'

    try:
        process_result = subprocess.run([
            'geth', 'version'
            ], capture_output=True, text=True)
        geth_found = True

        process_output = process_result.stdout
        result = re.search(r'Version: (.*?)\n', process_output)
        if result:
            geth_version = result.group(1).strip()
        
        process_result = subprocess.run([
            'whereis', 'geth'
            ], capture_output=True, text=True)

        process_output = process_result.stdout
        result = re.search(r'geth: (.*?)\n', process_output)
        if result:
            geth_location = result.group(1).strip()

        process_result = subprocess.run([
            'dpkg', '-s', 'geth'
            ])
        if process_result.returncode == 0:
            # Geth package is installed
            geth_package_installed = True

            process_result = subprocess.run([
                'apt', 'show', 'geth'
                ], capture_output=True, text=True)
            
            process_output = process_result.stdout
            result = re.search(r'APT-Sources: (.*?)\n', process_output)
            if result:
                apt_sources = result.group(1).strip()
                apt_sources_splits = apt_sources.split(' ')
                if apt_sources_splits[0] == ETHEREUM_APT_SOURCE_URL:
                    installed_from_ppa = True

    except FileNotFoundError:
        pass
    
    install_geth = True

    if geth_found:
        result = button_dialog(
            title='Geth binary found',
            text=(
f'''
The geth binary seems to have already been installed. Here are some
details found:

Version: {geth_version}
Location: {geth_location}
Installed from package: {geth_package_installed}
Installed from official Ethereum PPA: {installed_from_ppa}

Do you want to skip installing the geth binary?
'''         ),
            buttons=[
                ('Skip', 1),
                ('Install', 2),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result
        
        install_geth = (result == 2)

    if install_geth:
        # Install Geth from PPA
        subprocess.run([
            'add-apt-repository', '-y', 'ppa:ethereum/ethereum'])
        subprocess.run([
            'apt', 'update'])
        subprocess.run([
            'apt', '-y', 'install', 'geth'])
    
    # Setup Geth user and directory
    subprocess.run([
        'useradd', '--no-create-home', '--shell', '/bin/false', 'goeth'])
    subprocess.run([
        'mkdir', '-p', '/var/lib/goethereum'])
    subprocess.run([
        'chown', '-R', 'goeth:goeth', '/var/lib/goethereum'])
    
    # Setup Geth systemd service
    with open('/etc/systemd/system/geth.service', 'w') as service_file:
        service_file.write(GETH_SERVICE_DEFINITION[network])
    subprocess.run([
        'systemctl', 'daemon-reload'])
    subprocess.run([
        'systemctl', 'start', 'geth'])
    subprocess.run([
        'systemctl', 'enable', 'geth'])
    
    # TODO: Verify proper Geth installation and syncing

    return True

def install_lighthouse(network):
    # Install Lighthouse for the selected network

    result = button_dialog(
        title='Lighthouse installation',
        text=(
'''
This next step will install Lighthouse, an Eth2 client that includes a
beacon node and a validator client in the same binary.

It will download the official binary from GitHub, verify its PGP signature
and extract it for easy use.

Once installed locally, it will create a systemd service that will
automatically start the Lighthouse beacon node on reboot or if it crashes.
The beacon node will be started and you will slowly start syncing with the
Ethereum 2.0 network. This syncing process can take a few hours or days
even with good hardware and good internet.
'''     ),
        buttons=[
            ('Install', True),
            ('Quit', False)
        ]
    ).run()

    if not result:
        return result
    
    # Getting latest Lighthouse release files
    lighthouse_gh_release_url = GITHUB_REST_API_URL + LIGHTHOUSE_LATEST_RELEASE
    headers = {'Accept': GITHUB_API_VERSION}
    response = httpx.get(lighthouse_gh_release_url, headers=headers)

    if response.status_code != 200:
        # TODO: Better handling for network response issue
        return False
    
    release_json = response.json()

    if 'assets' not in release_json:
        # TODO: Better handling on unexpected response structure
        return False
    
    binary_asset = None
    signature_asset = None

    for asset in release_json['assets']:
        if 'name' not in asset:
            continue
        if 'browser_download_url' not in asset:
            continue
    
        file_name = asset['name']
        file_url = asset['browser_download_url']

        if file_name.endswith('x86_64-unknown-linux-gnu.tar.gz'):
            binary_asset = {
                'file_name': file_name,
                'file_url': file_url
            }
        elif file_name.endswith('x86_64-unknown-linux-gnu.tar.gz.asc'):
            signature_asset = {
                'file_name': file_name,
                'file_url': file_url
            }

    if binary_asset is None or signature_asset is None:
        # TODO: Better handling of missing asset in latest release
        return False
    
    # Downloading latest Lighthouse release files
    download_path = Path(Path.home(), 'eth2validatorwizard', 'downloads')
    download_path.mkdir(parents=True, exist_ok=True)

    binary_path = Path(download_path, binary_asset['file_name'])

    with open(binary_path, 'wb') as binary_file:
        with httpx.stream('GET', binary_asset['file_url']) as http_stream:
            for data in http_stream.iter_bytes():
                binary_file.write(data)
    
    signature_path = Path(download_path, signature_asset['file_name'])

    with open(signature_path, 'wb') as signature_file:
        with httpx.stream('GET', signature_asset['file_url']) as http_stream:
            for data in http_stream.iter_bytes():
                signature_file.write(data)

    # Verify PGP signature
    command_line = ['gpg', '--keyserver', 'pool.sks-keyservers.net', '--recv-keys',
        LIGHTHOUSE_PRIME_PGP_KEY_ID]
    process_result = subprocess.run(command_line)
    if process_result.returncode != 0:
        # GPG failed to download Sigma Prime's PGP key, let's wait and retry a few times
        retry_count = 0
        while process_result.returncode != 0 and retry_count < 5:
            retry_count = retry_count + 1
            print('GPG failed to download the PGP key. We will wait 10 seconds and try again.')
            time.sleep(10)
            process_result = subprocess.run(command_line)
    
    if process_result.returncode != 0:
        # We failed to download Sigma Prime's PGP key after a few retries
        # TODO: Better handling of failed PGP key download
        return False
    
    process_result = subprocess.run([
        'gpg', '--verify', signature_path])
    if process_result.returncode != 0:
        # PGP signature failed
        # TODO: Better handling of failed PGP signature
        return False
    
    # Extracting the Lighthouse binary archive
    subprocess.run([
        'tar', 'xvf', binary_path, '--directory', '/usr/local/bin'])
    
    # Remove download leftovers
    binary_path.unlink()
    signature_path.unlink()

    # Setup Lighthouse beacon node user and directory
    subprocess.run([
        'useradd', '--no-create-home', '--shell', '/bin/false', 'lighthousebeacon'])
    subprocess.run([
        'mkdir', '-p', '/var/lib/lighthouse/beacon'])
    subprocess.run([
        'chown', '-R', 'lighthousebeacon:lighthousebeacon', '/var/lib/lighthouse/beacon'])
    subprocess.run([
        'chmod', '700', '/var/lib/lighthouse/beacon'])
    
    # Setup Lighthouse beacon node systemd service
    with open('/etc/systemd/system/lighthousebeacon.service', 'w') as service_file:
        service_file.write(LIGHTHOUSE_BN_SERVICE_DEFINITION[network])
    subprocess.run([
        'systemctl', 'daemon-reload'])
    subprocess.run([
        'systemctl', 'start', 'lighthousebeacon'])
    subprocess.run([
        'systemctl', 'enable', 'lighthousebeacon'])
    
    # TODO: Verify proper Lighthouse beacon node installation and syncing

    return True

def generate_keys(network):
    # Generate validator keys for the selected network

    currency = NETWORK_CURRENCY[network]

    result = button_dialog(
        title='Generating keys',
        text=(
f'''
This next step will generate the keys needed to be a validator.

It will download the official eth2.0-deposit-cli binary from GitHub,
verify its SHA256 checksum, extract it and start it.

The eth2.0-deposit-cli tool is executed in an interactive way where you
have to answer a few questions. It will help you create a mnemonic from
which all your keys will be derived from. The mnemonic is the ultimate key.
It is VERY IMPORTANT to securely and privately store your mnemonic. It can
be used to recreate your validator keys and eventually withdraw your funds.

When asked how many validators you wish to run, remember that you will have
to do a 32 {currency} deposit for each validator.
'''     ),
        buttons=[
            ('Generate', True),
            ('Quit', False)
        ]
    ).run()

    if not result:
        return result
    
    # Getting latest eth2.0-deposit-cli release files
    eth2_cli_gh_release_url = GITHUB_REST_API_URL + ETH2_DEPOSIT_CLI_LATEST_RELEASE
    headers = {'Accept': GITHUB_API_VERSION}
    response = httpx.get(eth2_cli_gh_release_url, headers=headers)

    if response.status_code != 200:
        # TODO: Better handling for network response issue
        return False
    
    release_json = response.json()

    if 'assets' not in release_json:
        # TODO: Better handling on unexpected response structure
        return False
    
    binary_asset = None
    checksum_asset = None

    for asset in release_json['assets']:
        if 'name' not in asset:
            continue
        if 'browser_download_url' not in asset:
            continue
    
        file_name = asset['name']
        file_url = asset['browser_download_url']

        if file_name.endswith('linux-amd64.tar.gz'):
            binary_asset = {
                'file_name': file_name,
                'file_url': file_url
            }
        elif file_name.endswith('linux-amd64.sha256'):
            checksum_asset = {
                'file_name': file_name,
                'file_url': file_url
            }

    if binary_asset is None or checksum_asset is None:
        # TODO: Better handling of missing asset in latest release
        return False
    
    # Downloading latest eth2.0-deposit-cli release files
    download_path = Path(Path.home(), 'eth2validatorwizard', 'downloads')
    download_path.mkdir(parents=True, exist_ok=True)

    binary_path = Path(download_path, binary_asset['file_name'])
    binary_hash = hashlib.sha256()

    with open(binary_path, 'wb') as binary_file:
        with httpx.stream('GET', binary_asset['file_url']) as http_stream:
            for data in http_stream.iter_bytes():
                binary_file.write(data)
                binary_hash.update(data)

    binary_hexdigest = binary_hash.hexdigest()

    checksum_path = Path(download_path, checksum_asset['file_name'])

    with open(checksum_path, 'wb') as signature_file:
        with httpx.stream('GET', checksum_asset['file_url']) as http_stream:
            for data in http_stream.iter_bytes():
                signature_file.write(data)

    # Verify SHA256 signature
    with open(checksum_path, 'r') as signature_file:
        if binary_hexdigest != signature_file.read(1024).strip():
            # SHA256 checksum failed
            # TODO: Better handling of failed SHA256 checksum
            return False
    
    # Extracting the eth2.0-deposit-cli binary archive
    eth2_deposit_cli_path = Path(Path.home(), 'eth2validatorwizard', 'eth2depositcli')
    eth2_deposit_cli_path.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        'tar', 'xvf', binary_path, '--strip-components', '2', '--directory',
        eth2_deposit_cli_path])
    
    # Remove download leftovers
    binary_path.unlink()
    checksum_path.unlink()

    # Clean potential leftover keys
    validator_keys_path = Path(eth2_deposit_cli_path, 'validator_keys')
    if validator_keys_path.exists():
        if validator_keys_path.is_dir():
            shutil.rmtree(validator_keys_path)
        elif validator_keys_path.is_file():
            validator_keys_path.unlink()
    
    # Launch eth2.0-deposit-cli
    eth2_deposit_cli_binary = Path(eth2_deposit_cli_path, 'deposit')
    subprocess.run([
        eth2_deposit_cli_binary, 'new-mnemonic', '--chain', network],
        cwd=eth2_deposit_cli_path)

    # Verify the generated keys
    deposit_data_path = None
    keystore_paths = []

    with os.scandir(validator_keys_path) as dir_it:
        for entry in dir_it:
            if entry.name.startswith('.') or not entry.is_file():
                continue

            if entry.name.startswith('deposit_data'):
                deposit_data_path = entry.path
            elif entry.name.startswith('keystore'):
                keystore_paths.append(entry.path)
    
    if deposit_data_path is None or len(keystore_paths) == 0:
        # No key generated
        # TODO: Better handling of no keys generated
        return False

    # Clean up eth2.0-deposit-cli tool
    eth2_deposit_cli_binary.unlink()

    return {
        'validator_keys_path': validator_keys_path,
        'deposit_data_path': deposit_data_path,
        'keystore_paths': keystore_paths
    }

def install_lighthouse_validator(network, keys):
    # Import keystore(s) and configure the Lighthouse validator client

    result = button_dialog(
        title='Lighthouse validator client',
        text=(
'''
This next step will import your keystore(s) to be used with the Lighthouse
validator client and it will configure the Lighthouse validator client.

During the importation process, you will be asked to enter the password
you typed during the keys generation step. It is not your mnemonic. Do not
omit typing your password during this importation process.

It will create a systemd service that will automatically start the
Lighthouse validator client on reboot or if it crashes. The validator
client will be started, it will connect to your beacon node and it will be
ready to start validating once your validator(s) get activated.
'''     ),
        buttons=[
            ('Configure', True),
            ('Quit', False)
        ]
    ).run()

    if not result:
        return result
    
    # Setup Lighthouse validator client user and directory
    subprocess.run([
        'useradd', '--no-create-home', '--shell', '/bin/false', 'lighthousevalidator'])
    subprocess.run([
        'mkdir', '-p', '/var/lib/lighthouse/validators'])
    subprocess.run([
        'chown', '-R', 'lighthousevalidator:lighthousevalidator', '/var/lib/lighthouse/validators'])
    subprocess.run([
        'chmod', '700', '/var/lib/lighthouse/validators'])
    
    # Import keystore(s)
    subprocess.run([
        '/usr/local/bin/lighthouse', '--network', network, 'account', 'validator', 'import',
        '--directory', keys['validator_keys_path'], '--datadir', '/var/lib/lighthouse'])

    # TODO: Check for correct keystore(s) import

    # Clean up generated keys
    for keystore_path in keys['keystore_paths']:
        os.unlink(keystore_path)

    # Make sure validators directory is owned by the right user/group
    subprocess.run([
        'chown', '-R', 'lighthousevalidator:lighthousevalidator', '/var/lib/lighthouse/validators'])

    # Setup Lighthouse validator client systemd service
    with open('/etc/systemd/system/lighthousevalidator.service', 'w') as service_file:
        service_file.write(LIGHTHOUSE_VC_SERVICE_DEFINITION[network])
    subprocess.run([
        'systemctl', 'daemon-reload'])
    subprocess.run([
        'systemctl', 'start', 'lighthousevalidator'])
    subprocess.run([
        'systemctl', 'enable', 'lighthousevalidator'])

    # TODO: Verify proper Lighthouse validator client installation and the connection with the beacon node

    return True

def initiate_deposit(network, keys):
    # Initiate and explain the deposit on launchpad

    launchpad_url = LAUNCHPAD_URLS[network]
    currency = NETWORK_CURRENCY[network]

    # Create an easily accessible copy of the deposit file
    deposit_file_copy_path = Path('/tmp', 'deposit_data.json')
    shutil.copyfile(keys['deposit_data_path'], deposit_file_copy_path)
    os.chmod(deposit_file_copy_path, stat.S_IROTH)

    # TODO: Create an alternative way to easily obtain the deposit file with a simple HTTP server

    result = button_dialog(
        title='Deposit on the launch pad',
        text=(
f'''
This next step is to perform the 32 {currency} deposit(s) on the launch pad. In
order to do this deposit, you will need your deposit file which was created
during the key generation step. A copy of your deposit file can be found in

{deposit_file_copy_path}

On the Eth2 Launch Pad website, you will be asked a few questions and it
will explain some of the risks and mitigation strategies. Make sure to read
everything carefully and make sure you understand it all. When you are
ready, go to the following URL in your browser:

{launchpad_url}

When you are done with the deposit(s), click the "I'm done" button below.
'''     ),
        buttons=[
            ('I\'m done', True),
            ('Quit', False)
        ]
    ).run()

    if not result:
        return result

    public_keys = []

    with open(keys['deposit_data_path'], 'r') as deposit_data_file:
        deposit_data = json.loads(deposit_data_file.read(204800))
        
        for validator_data in deposit_data:
            if 'pubkey' not in validator_data:
                continue
            public_key = validator_data['pubkey']
            public_keys.append('0x' + public_key)
    
    if len(public_keys) == 0:
        # TODO: Better handling of no public keys in deposit data file
        return False

    # Verify that the deposit was done correctly using beaconcha.in API
    validator_deposits = get_bc_validator_deposits(network, public_keys)

    if type(validator_deposits) is not list and not validator_deposits:
        # TODO: Better handling of unability to get validator(s) deposits from beaconcha.in
        print('Unability to get validator(s) deposits from beaconcha.in')
        return False

    while len(validator_deposits) == 0:
        # beaconcha.in does not see any validator with the public keys we generated

        result = button_dialog(
            title='No deposit found',
            text=(
f'''
No deposit has been found on the beaconcha.in website for the validator
keys that you generated. In order to become an active validator, you need
to do a 32 {currency} deposit for each validator you created. In order to do
this deposit, you will need your deposit file which was created during the
key generation step. A copy of your deposit file can be found in

{deposit_file_copy_path}

To perform the deposit(s), go to the following URL in your browser:

{launchpad_url}

When you are done with the deposit(s), click the "I'm done" button below.
Note that it can take a few minutes before beaconcha.in sees your
deposit(s).
'''     ),
            buttons=[
                ('I\'m done', True),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result

        validator_deposits = get_bc_validator_deposits(network, public_keys)

        if type(validator_deposits) is not list and not validator_deposits:
            # TODO: Better handling of unability to get validator(s) deposits from beaconcha.in
            print('Unability to get validator(s) deposits from beaconcha.in')
            return False
    
    # Check if all the deposit(s) were done for each validator
    while len(validator_deposits) < len(public_keys):

        result = button_dialog(
            title='Missing deposit(s)',
            text=(
f'''
Only {len(validator_deposits)} deposit(s) has been found for your {len(public_keys)} validators on the
beaconcha.in website. In order to become an active validator, you need
to do a 32 {currency} deposit for each validator you created. In order to do
this deposit, you will need your deposit file which was created during the
key generation step. A copy of your deposit file can be found in

{deposit_file_copy_path}

To perform the deposit(s), go to the following URL in your browser:

{launchpad_url}

When you are done with the deposit(s), click the "I'm done" button below.
Note that it can take a few minutes before beaconcha.in sees your
deposit(s).
'''     ),
            buttons=[
                ('I\'m done', True),
                ('Quit', False)
            ]
        ).run()

        if not result:
            return result

        validator_deposits = get_bc_validator_deposits(network, public_keys)

        if type(validator_deposits) is not list and not validator_deposits:
            # TODO: Better handling of unability to get validator(s) deposits from beaconcha.in
            print('Unability to get validator(s) deposits from beaconcha.in')
            return False

    # Clean up deposit data file
    deposit_file_copy_path.unlink()
    os.unlink(keys['deposit_data_path'])
    
    return public_keys

def get_bc_validator_deposits(network, public_keys):
    # Return the validator deposits from the beaconcha.in API

    pubkey_arg = ','.join(public_keys)
    bc_api_query_url = (BEACONCHA_IN_URLS[network] +
        BEACONCHA_VALIDATOR_DEPOSITS_API_URL.format(indexOrPubkey=pubkey_arg))
    headers = {'accept': 'application/json'}
    response = httpx.get(bc_api_query_url, headers=headers)

    if response.status_code != 200:
        # TODO: Better handling for network response issue
        print(f'Error code {response.status_code} when trying to get {bc_api_query_url}')
        return False
    
    response_json = response.json()

    if (
        'status' not in response_json or
        response_json['status'] != 'OK' or
        'data' not in response_json
        ):
        # TODO: Better handling for response data or structure issue
        print(f'Unexpected response data or structure from {bc_api_query_url}: {response_json}')
        return False
    
    validator_deposits = response_json['data']
    # beaconcha.in API does not return a list for a single validator so
    # we make it a list for ease of use
    if type(validator_deposits) is not list:
        validator_deposits = [validator_deposits]

    return validator_deposits

def show_whats_next(network, keys, public_keys):
    # Show what's next including wait time

    beaconcha_in_url = BEACONCHA_IN_URLS[network]

    button_dialog(
        title='Installation completed',
        text=(
f'''
You just completed all the steps needed to become an active validator on
the {network.capitalize()} Ethereum 2.0 network. You created {len(keys['keystore_paths'])} validator(s)
that will soon be activated.

You can monitor your activation period and all the details about your
validator(s) on the beaconcha.in website at the following URL:

{beaconcha_in_url}

If you have any question or if you need additional support, make sure
to get in touch with the ethstaker community on:

* Discord: discord.gg/e84CFep
* Reddit: reddit.com/r/ethstaker
'''     ),
        buttons=[
            ('Quit', False)
        ]
    ).run()

def show_public_keys(network, keys, public_keys):
    beaconcha_in_url = BEACONCHA_IN_URLS[network]

    newline = '\n'

    print(
f'''
Eth2 Validator Wizard completed!

Network: {network.capitalize()}
Number of validator(s): {len(keys['keystore_paths'])}

Make sure to note or save your public keys somewhere. Your validator public
key(s) are:
{newline.join(public_keys)}

Make sure to check the beaconcha.in website for more details about your
validator(s):
{beaconcha_in_url}
''' )