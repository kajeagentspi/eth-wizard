import sys
import json

import logging
import logging.handlers

from pathlib import Path

from typing import Optional

from ethwizard import __version__

log = logging.getLogger(__name__)

def save_state(step_id: str, context: dict) -> bool:
    # Save wizard state

    data_to_save = {
        'step': step_id,
        'context': context
    }

    save_directory = Path(LINUX_SAVE_DIRECTORY)
    if not save_directory.is_dir():
        save_directory.mkdir(parents=True, exist_ok=True)
    save_file = save_directory.joinpath(STATE_FILE)

    with open(str(save_file), 'w', encoding='utf8') as output_file:
        json.dump(data_to_save, output_file)

    return True

def load_state() -> Optional[dict]:
    # Load wizard state

    save_directory = Path(LINUX_SAVE_DIRECTORY)
    if not save_directory.is_dir():
        return None
    save_file = save_directory.joinpath(STATE_FILE)
    if not save_file.is_file():
        return None
    
    loaded_data = None

    try:
        with open(str(save_file), 'r', encoding='utf8') as input_file:
            loaded_data = json.load(input_file)
    except ValueError:
        return None
    
    return loaded_data

def quit_app():
    log.info(f'Quitting eth-wizard')
    quit()

def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    
    log.critical('Uncaught exception', exc_info=(exc_type, exc_value, exc_traceback))

def init_logging():
    # Initialize logging
    log.setLevel(logging.INFO)

    # Handle uncaught exception and log them
    sys.excepthook = handle_exception

    # Console handler to log into the console
    ch = logging.StreamHandler()
    log.addHandler(ch)

    # SysLog handler to log into syslog
    slh = logging.handlers.SysLogHandler(address='/dev/log')

    formatter = logging.Formatter('%(name)s[%(process)d]: %(levelname)s - %(message)s')
    slh.setFormatter(formatter)

    log.addHandler(slh)

    log.info(f'Starting eth-wizard version {__version__}')